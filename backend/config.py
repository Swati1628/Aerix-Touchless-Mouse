from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "models" / "hand_landmarker.task"

CAMERA_INDEX = 0
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720

MAX_HANDS = 1
HAND_DETECTION_CONFIDENCE = 0.5
HAND_TRACKING_CONFIDENCE = 0.5
PINCH_THRESHOLD = 0.36  # tip distance / wrist-to-middle-MCP palm length
PINCH_RELEASE_THRESHOLD = 0.46  # hysteresis release ratio, above pinch start
CLICK_COOLDOWN = 0.35
GESTURE_STABLE_FRAMES = 3
CLICK_CONFIDENCE_THRESHOLD = 1.0
DEBUG_GESTURES = True
CLICK_DEBUG_LOG_INTERVAL_SECONDS = 0.15
DEFAULT_MODE = "gesture"

# ---------------------------------------------------------
# CURSOR STABILITY
# ---------------------------------------------------------

# Keep the mapped cursor target inside a small normalized inset before
# converting it to pixels. PyAutoGUI's fail-safe remains enabled; this
# avoids requesting an exact screen corner from noisy tracking data.
CURSOR_SAFE_MIN = 0.015
CURSOR_SAFE_MAX = 0.985

# Reject a single implausibly large mapped-point jump by limiting the
# per-frame cursor step. The smoothing factor keeps ordinary movement
# responsive while removing landmark jitter.
CURSOR_MAX_STEP = 0.035
CURSOR_SMOOTHING = 0.38
CURSOR_DEADZONE = 0.002

# A valid four-corner calibration needs a meaningful camera-space area
# and distinct points. Values are normalized MediaPipe coordinates.
CALIBRATION_MIN_POINT_DISTANCE = 0.04
CALIBRATION_MIN_AREA = 0.02

# ---------------------------------------------------------
# SCROLL / ZOOM
# ---------------------------------------------------------

# Minimum vertical movement (normalized 0-1 coords) between
# frames before a scroll/zoom tick is fired. Filters out
# hand jitter so a still hand doesn't scroll/zoom on its own.
MOTION_DEADZONE = 0.004

# Converts normalized hand movement into mouse-wheel detents. A moving hand
# always emits at least one detent after the motion deadzone is crossed.
SCROLL_SENSITIVITY = 120

# Multiplies the raw vertical delta into a zoom "amount"
# (sent as ctrl+scroll ticks). Higher = faster zoom.
ZOOM_SENSITIVITY = 700

# Converts normalized horizontal hand movement into horizontal wheel detents.
HSCROLL_SENSITIVITY = 120

# Hold / swipe gesture thresholds in normalized camera coordinates.
OPEN_PALM_SWIPE_SECONDS = 0.65
OPEN_PALM_SWIPE_DISTANCE = 0.10

# ---------------------------------------------------------
# HAND-LOST SAFETY
# ---------------------------------------------------------

# Number of consecutive frames with no hand detected before
# we treat the hand as "lost" and force-release drag / stop
# any in-progress action. Small buffer avoids false trips
# from a single dropped camera frame.
HAND_LOST_FRAMES = 5
