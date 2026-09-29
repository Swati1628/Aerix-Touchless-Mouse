import json
import math
from pathlib import Path

import cv2
import numpy as np

from .config import CALIBRATION_MIN_AREA, CALIBRATION_MIN_POINT_DISTANCE


class Calibration:
    """Maps four camera-space landmarks to the four screen corners."""

    TARGETS = ("Top Left", "Top Right", "Bottom Right", "Bottom Left")

    def __init__(self):
        self.active = False
        self.points = []
        self.index_points = []
        self.transform = None
        self.index_transform = None
        self.last_error = None
        self.storage_path = Path(__file__).resolve().parent.parent / "calibration_points.json"
        self._load()

    def _load(self):
        try:
            saved_data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            # Version 3 captures both palm-center and index-tip coordinates at
            # each target, allowing normal movement and dragging to use their
            # own stable anchors through the same screen-mapping pipeline.
            if not isinstance(saved_data, dict) or saved_data.get("version") != 3:
                self.points = []
                self.index_points = []
                self.last_error = "Cursor anchors changed. Please recalibrate all four corners."
                return
            saved_points = saved_data.get("points", [])
            points = [(float(x), float(y)) for x, y in saved_points]
            index_points = [(float(x), float(y)) for x, y in saved_data.get("index_points", [])]
            if self._valid_points(points) and self._valid_points(index_points):
                self.points = points
                self.index_points = index_points
                self.transform = self._create_transform(points)
                self.index_transform = self._create_transform(index_points)
            else:
                self.points = []
                self.index_points = []
                self.last_error = (
                    "Saved calibration is invalid. Please calibrate all four "
                    "corners again."
                )
        except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
            self.points = []

    def _save(self):
        self.storage_path.write_text(
            json.dumps({
                "version": 3,
                "points": self.points,
                "index_points": self.index_points,
            }), encoding="utf-8"
        )

    @staticmethod
    def _create_transform(points):
        source = np.array(points, dtype=np.float32)
        destination = np.array(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            dtype=np.float32,
        )
        return cv2.getPerspectiveTransform(source, destination)

    @staticmethod
    def _valid_points(points):
        """Return True only for a usable TL, TR, BR, BL camera quadrilateral."""
        if len(points) != 4:
            return False

        try:
            source = np.asarray(points, dtype=np.float64)
        except (TypeError, ValueError):
            return False

        if source.shape != (4, 2) or not np.isfinite(source).all():
            return False

        # A calibration point should be a MediaPipe normalized image point.
        # Allow a little spill outside the visible image, but reject corrupt data.
        if (source < -0.25).any() or (source > 1.25).any():
            return False

        # Do not allow repeated / nearly identical captures.
        for index, point in enumerate(source):
            for other in source[index + 1:]:
                if np.linalg.norm(point - other) < CALIBRATION_MIN_POINT_DISTANCE:
                    return False

        tl, tr, br, bl = source
        # The UI captures points in this explicit order. Reject crossed or
        # inverted quadrilaterals instead of silently building a bad homography.
        if not (tl[0] < tr[0] and bl[0] < br[0] and tl[1] < bl[1] and tr[1] < br[1]):
            return False

        area = 0.5 * abs(
            np.dot(source[:, 0], np.roll(source[:, 1], -1))
            - np.dot(source[:, 1], np.roll(source[:, 0], -1))
        )
        return area >= CALIBRATION_MIN_AREA

    def start(self):
        self.active = True
        self.points.clear()
        self.index_points.clear()
        self.transform = None
        self.index_transform = None
        self.last_error = None
        self._save()

    def reset(self):
        self.start()

    def capture(self, point, index_point=None):
        self.last_error = None

        if not self.active:
            self.last_error = "Start calibration before confirming a point."
            return self.status()

        if point is None:
            self.last_error = "No hand detected. Keep your index finger visible and try again."
            return self.status()
        if index_point is None:
            index_point = point

        try:
            captured = (float(point[0]), float(point[1]))
        except (TypeError, ValueError, IndexError):
            self.last_error = "Invalid fingertip position. Keep your hand visible and try again."
            return self.status()

        if not all(math.isfinite(value) for value in captured):
            self.last_error = "Invalid fingertip position. Keep your hand visible and try again."
            return self.status()

        self.points.append(captured)
        try:
            index_captured = (float(index_point[0]), float(index_point[1]))
        except (TypeError, ValueError, IndexError):
            self.points.pop()
            self.last_error = "Invalid index fingertip position. Please try again."
            return self.status()
        if not all(math.isfinite(value) for value in index_captured):
            self.points.pop()
            self.last_error = "Invalid index fingertip position. Please try again."
            return self.status()
        self.index_points.append(index_captured)

        if len(self.points) == len(self.TARGETS):
            if self._valid_points(self.points) and self._valid_points(self.index_points):
                self.transform = self._create_transform(self.points)
                self.index_transform = self._create_transform(self.index_points)
                self.active = False
                self._save()
            else:
                self.points.clear()
                self.index_points.clear()
                self.transform = None
                self.index_transform = None
                self.last_error = (
                    "Calibration points must be four distinct corners in the "
                    "order Top Left, Top Right, Bottom Right, Bottom Left. "
                    "Please try again."
                )
                self._save()

        return self.status()

    def map_point(self, x, y, source="palm"):
        transform = self.index_transform if source == "index_tip" else self.transform
        if transform is None:
            # Cursor control must never fall back to uncalibrated camera
            # coordinates. The caller treats None as "calibration required".
            return None

        point = np.array([[[x, y]]], dtype=np.float32)
        mapped = cv2.perspectiveTransform(point, transform)[0][0]
        if not np.isfinite(mapped).all():
            return None
        return (
            float(np.clip(mapped[0], 0.0, 1.0)),
            float(np.clip(mapped[1], 0.0, 1.0)),
        )

    def status(self):
        point_count = len(self.points)
        return {
            "active": self.active,
            "points": point_count,
            "current_point": self.TARGETS[point_count] if self.active else None,
            "complete": self.transform is not None and self.index_transform is not None,
            "required": self.transform is None or self.index_transform is None,
            "error": self.last_error,
        }
