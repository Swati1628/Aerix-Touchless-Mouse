from pathlib import Path

import cv2
import mediapipe as mp

from .config import (
    MODEL_PATH,
    MAX_HANDS,
    HAND_DETECTION_CONFIDENCE,
    HAND_TRACKING_CONFIDENCE,
)


class HandTracker:

    def __init__(self):

        if not Path(MODEL_PATH).exists():
            raise FileNotFoundError(
                f"MediaPipe model not found: {MODEL_PATH}\n"
                "Put hand_landmarker.task in the models folder."
            )

        base_options = mp.tasks.BaseOptions(
            model_asset_path=str(MODEL_PATH)
        )

        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=MAX_HANDS,
            min_hand_detection_confidence=HAND_DETECTION_CONFIDENCE,
            min_hand_presence_confidence=HAND_DETECTION_CONFIDENCE,
            min_tracking_confidence=HAND_TRACKING_CONFIDENCE,
        )

        self.landmarker = (
            mp.tasks.vision.HandLandmarker.create_from_options(
                options
            )
        )

        self.timestamp_ms = 0

    def process(self, frame):

        rgb = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB
        )

        image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb
        )

        self.timestamp_ms += 33

        return self.landmarker.detect_for_video(
            image,
            self.timestamp_ms
        )

    def draw(self, frame, result):

        if not result.hand_landmarks:
            return

        connections = [
            (0, 1), (1, 2), (2, 3), (3, 4),

            (0, 5), (5, 6), (6, 7), (7, 8),

            (0, 9), (9, 10), (10, 11), (11, 12),

            (0, 13), (13, 14), (14, 15), (15, 16),

            (0, 17), (17, 18), (18, 19), (19, 20),

            (5, 9),
            (9, 13),
            (13, 17),
        ]

        h, w = frame.shape[:2]

        for landmarks in result.hand_landmarks:

            points = []

            # -----------------------------
            # DRAW LANDMARK POINTS
            # -----------------------------

            for p in landmarks:

                x = int(p.x * w)
                y = int(p.y * h)

                x = max(0, min(x, w - 1))
                y = max(0, min(y, h - 1))

                points.append((x, y))

                cv2.circle(
                    frame,
                    (x, y),
                    4,
                    (0, 255, 0),
                    -1
                )

            # -----------------------------
            # DRAW HAND CONNECTIONS
            # -----------------------------

            for a, b in connections:

                cv2.line(
                    frame,
                    points[a],
                    points[b],
                    (0, 255, 0),
                    2
                )

    def close(self):

        self.landmarker.close()