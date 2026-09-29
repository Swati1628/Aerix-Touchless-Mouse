import math
from time import monotonic

from .config import (
    PINCH_THRESHOLD, PINCH_RELEASE_THRESHOLD, CLICK_COOLDOWN, GESTURE_STABLE_FRAMES,
    MOTION_DEADZONE,
    OPEN_PALM_SWIPE_SECONDS,
    OPEN_PALM_SWIPE_DISTANCE,
)


def distance(a, b):
    return math.sqrt(
        (a.x - b.x) ** 2 + (a.y - b.y) ** 2
        + (getattr(a, "z", 0.0) - getattr(b, "z", 0.0)) ** 2
    )


def palm_center(lm):
    """Stable normalized cursor anchor from the wrist and four palm MCPs."""
    points = (lm[0], lm[5], lm[9], lm[13], lm[17])
    return (sum(point.x for point in points) / len(points),
            sum(point.y for point in points) / len(points))


def _straight_joint(a, joint, b, limit=-0.45):
    first = (a.x-joint.x, a.y-joint.y, getattr(a, "z", 0.0)-getattr(joint, "z", 0.0))
    second = (b.x-joint.x, b.y-joint.y, getattr(b, "z", 0.0)-getattr(joint, "z", 0.0))
    first_length = math.sqrt(sum(value * value for value in first))
    second_length = math.sqrt(sum(value * value for value in second))
    if first_length == 0.0 or second_length == 0.0:
        return False
    return sum(x * y for x, y in zip(first, second)) / (first_length * second_length) < limit


def hand_reference(lm):
    """Palm scale from wrist to middle MCP, stable across camera distance."""
    return max(distance(lm[0], lm[9]), 1e-6)


def finger_up(lm, tip, pip, mcp=None, wrist=0, dip=None):
    """Test finger reach and PIP/DIP straightness using 3D landmark geometry."""
    if mcp is None:
        mcp = pip - 1
    if dip is None:
        dip = tip - 1
    tip_pt, pip_pt, mcp_pt, dip_pt, wrist_pt = lm[tip], lm[pip], lm[mcp], lm[dip], lm[wrist]
    reach = distance(tip_pt, wrist_pt) > distance(pip_pt, wrist_pt) * 1.025
    return (reach and _straight_joint(mcp_pt, pip_pt, dip_pt)
            and _straight_joint(pip_pt, dip_pt, tip_pt))


def fingers_crossed(lm):
    """Practical crossed-finger test: fingertip order reverses past the PIPs."""
    pip_dx, pip_dy = lm[6].x - lm[10].x, lm[6].y - lm[10].y
    tip_dx, tip_dy = lm[8].x - lm[12].x, lm[8].y - lm[12].y
    if abs(pip_dx) >= abs(pip_dy):
        return pip_dx * tip_dx < -0.0004
    return pip_dy * tip_dy < -0.0004


class GestureClassifier:
    def __init__(self):
        self.last_gesture = "none"
        self.stable_count = 0
        self.candidate_gesture = "none"
        self.candidate_count = 0
        self.active_gesture = "none"
        self.previous_gesture = "none"
        self.gesture_entered = False
        self.discrete_gesture_fired = None
        self.last_action_time = 0.0
        # A pinch is one discrete action, not a stream of repeated clicks.
        # This is reset as soon as the pinch pose ends.
        self.active_discrete_action = None
        self.prev_x = None
        self.prev_y = None
        self.palm_started_at = None
        self.palm_origin = None
        self.palm_swipe_fired = False
        self.crossed_fired = False
        self.crossed_count = 0
        self.debug_state = {}
        self.pinch_state = {"index": False, "middle": False, "ring": False}

    def _pinching(self, name, ratio):
        """Latch a pinch inside the start/release band to suppress landmark jitter."""
        active = self.pinch_state[name]
        if active:
            active = ratio <= PINCH_RELEASE_THRESHOLD
        else:
            active = ratio < PINCH_THRESHOLD
        self.pinch_state[name] = active
        return active

    def _reset_palm(self):
        self.palm_started_at = None
        self.palm_origin = None
        self.palm_swipe_fired = False

    def _palm_gesture(self, wrist, now):
        if self.palm_started_at is None:
            self.palm_started_at = now
            self.palm_origin = (wrist.x, wrist.y)
        elapsed = now - self.palm_started_at
        horizontal = wrist.x - self.palm_origin[0]
        self.debug_state.update({
            "palm_elapsed": elapsed,
            "palm_horizontal_distance": horizontal,
        })
        if (not self.palm_swipe_fired and elapsed <= OPEN_PALM_SWIPE_SECONDS
                and abs(horizontal) >= OPEN_PALM_SWIPE_DISTANCE):
            self.palm_swipe_fired = True
            return "tab_next" if horizontal > 0 else "tab_previous"
        # Open palms are reserved for browser swipes. Holding one still is
        # intentionally inert and can never change the Safety Lock state.
        return "palm"

    def classify(self, lm, hand_name="Right"):
        index = finger_up(lm, 8, 6, 5, dip=7)
        middle = finger_up(lm, 12, 10, 9, dip=11)
        ring = finger_up(lm, 16, 14, 13, dip=15)
        pinky = finger_up(lm, 20, 18, 17, dip=19)
        wrist = lm[0]
        reference = hand_reference(lm)
        # The thumb points sideways across the palm, so test its reach away
        # from the index MCP rather than applying the other fingers' Y test.
        thumb = distance(lm[4], lm[5]) / reference > 0.72
        now = monotonic()
        self.debug_state = {
            "fingers": {"T": thumb, "I": index, "M": middle, "R": ring, "P": pinky},
            "pinches": {},
            "crossed": False,
            "hand_size": reference,
        }

        if self.prev_x is None:
            delta_x, delta_y = 0.0, 0.0
        else:
            delta_x, delta_y = wrist.x - self.prev_x, wrist.y - self.prev_y
        self.prev_x, self.prev_y = wrist.x, wrist.y
        if abs(delta_x) < MOTION_DEADZONE:
            delta_x = 0.0
        if abs(delta_y) < MOTION_DEADZONE:
            delta_y = 0.0

        # MediaPipe x/y coordinates are normalized to the image, but their
        # distances still change with hand-to-camera distance. Divide by palm
        # length so pinch thresholds describe hand geometry instead.
        thumb_index = distance(lm[4], lm[8]) / reference
        thumb_middle = distance(lm[4], lm[12]) / reference
        index_middle = distance(lm[8], lm[12]) / reference
        index_pinching = self._pinching("index", thumb_index)
        middle_pinching = self._pinching("middle", thumb_middle)
        thumb_ring = distance(lm[4], lm[16]) / reference
        ring_pinching = self._pinching("ring", thumb_ring)
        if not index_pinching and not middle_pinching and not ring_pinching:
            self.active_discrete_action = None
            self.discrete_gesture_fired = None
        # The thumb-ring pinch alone owns drag activation and hold. Index
        # extension is deliberately irrelevant here; index tip drives cursor.
        select_drag = ring_pinching
        self.debug_state["pinches"] = {
            "index": index_pinching,
            "middle": middle_pinching,
            "ring": ring_pinching,
        }
        self.debug_state["distances"] = {
            "thumb_index": thumb_index,
            "thumb_middle": thumb_middle,
            "index_middle": index_middle,
            "thumb_ring": thumb_ring,
            "select_drag": select_drag,
        }
        self.debug_state["select_drag_distances"] = {"thumb_ring": thumb_ring}

        # A folded middle fingertip near the thumb should never steal an index
        # pinch. The movement pose is explicit and must stay above the pinch
        # threshold before it can be considered a click.
        index_only = (
            index and not middle and not ring and not pinky
            and not index_pinching
        )
        middle_only = (
            middle and not index and not ring and not pinky
        )
        two_finger = index and middle and not ring and not pinky
        open_palm = index and middle and ring and pinky
        crossed = two_finger and fingers_crossed(lm)
        self.debug_state["crossed"] = crossed
        if not crossed:
            self.crossed_count = 0
            self.crossed_fired = False

        # Clicks require the non-pinching fingers to stay clearly extended.
        # The engaged-finger reach test allows a natural bend at the fingertip.
        index_pinch = (
            index_pinching and not middle_pinching and not ring_pinching
            and middle and ring and pinky
        )
        middle_pinch = (
            middle_pinching
            and index and ring and pinky
            and not index_pinching
            and not ring_pinching
        )
        double_click_candidate = (
            index_pinching
            and middle_pinching
            and not ring_pinching
        )

        if select_drag:
            self._reset_palm(); self.crossed_fired = False
            gesture = "select_drag"
        # Click poses precede movement/scroll poses because a bent pinching
        # finger can still satisfy the extended-finger geometry test.
        elif double_click_candidate:
            self._reset_palm(); self.crossed_fired = False
            gesture = "double_click"
        elif index_pinch and hand_name == "Right":
            self._reset_palm(); self.crossed_fired = False
            gesture = "left_click"
        elif middle_pinch and hand_name == "Right":
            self._reset_palm(); self.crossed_fired = False
            gesture = "right_click"
        elif index_pinch and hand_name == "Left":
            self._reset_palm(); self.crossed_fired = False
            gesture = "right_click"
        elif middle_pinch and hand_name == "Left":
            self._reset_palm(); self.crossed_fired = False
            gesture = "left_click"
        elif open_palm:
            self.crossed_fired = False
            gesture = self._palm_gesture(wrist, now)
        elif index and pinky and not middle and not ring:
            self._reset_palm(); self.crossed_fired = False
            gesture = "zoom"
        elif index and middle and ring and not pinky:
            self._reset_palm(); self.crossed_fired = False
            gesture = "hscroll"
        elif index_only:
            self._reset_palm(); self.crossed_fired = False
            gesture = "move"
        elif crossed:
            self._reset_palm()
            self.crossed_count += 1
            if self.crossed_fired:
                gesture = "crossed_hold"
            elif self.crossed_count >= GESTURE_STABLE_FRAMES:
                gesture = "browser_back"
                self.crossed_fired = True
            else:
                gesture = "crossed_candidate"
        elif two_finger:
            self._reset_palm(); self.crossed_fired = False
            self.crossed_count = 0
            gesture = "scroll"
        elif middle_only:
            self._reset_palm(); self.crossed_fired = False
            self.crossed_count = 0
            gesture = "move"
        elif index:
            self._reset_palm(); self.crossed_fired = False
            self.crossed_count = 0
            gesture = "move"
        else:
            self._reset_palm(); self.crossed_fired = False
            self.crossed_count = 0
            gesture = "none"

        if gesture == self.last_gesture:
            self.stable_count += 1
        else:
            self.last_gesture, self.stable_count = gesture, 1
        if gesture == self.candidate_gesture:
            self.candidate_count += 1
        else:
            self.candidate_gesture = gesture
            self.candidate_count = 1
        self.gesture_entered = False
        stable_candidate = self.candidate_count >= GESTURE_STABLE_FRAMES
        discrete_candidate = self.candidate_gesture in {
            "left_click", "right_click", "double_click"
        }
        new_discrete_entry = (
            stable_candidate
            and discrete_candidate
            and self.discrete_gesture_fired != self.candidate_gesture
        )
        new_continuous_entry = (
            stable_candidate
            and not discrete_candidate
            and self.active_gesture != self.candidate_gesture
        )
        if new_discrete_entry or new_continuous_entry:
            self.previous_gesture = self.active_gesture
            self.active_gesture = self.candidate_gesture
            self.gesture_entered = True
            if discrete_candidate:
                self.discrete_gesture_fired = self.candidate_gesture
        self.debug_state.update({
            "stable_count": self.candidate_count,
            "candidate_gesture": self.candidate_gesture,
            "candidate_count": self.candidate_count,
            "active_gesture": self.active_gesture,
            "previous_gesture": self.previous_gesture,
            "gesture_entered": self.gesture_entered,
        })
        confidence = min(1.0, self.candidate_count / GESTURE_STABLE_FRAMES)
        # browser_back is emitted only after crossed_count has already met the
        # stability requirement; its event name changes on that confirming frame.
        if gesture == "browser_back":
            confidence = 1.0
        return gesture, confidence, delta_x, delta_y

    def reset_motion(self):
        self.prev_x = self.prev_y = None
        self._reset_palm(); self.crossed_fired = False
        self.crossed_count = 0
        self.pinch_state = {"index": False, "middle": False, "ring": False}
        self.active_discrete_action = None
        self.discrete_gesture_fired = None
        self.last_gesture = self.candidate_gesture = "none"
        self.stable_count = self.candidate_count = 0
        self.previous_gesture = self.active_gesture = "none"
        self.gesture_entered = False

    def reset_gesture_state(self):
        """Clear gesture transitions without changing pinch hysteresis."""
        self.last_gesture = self.candidate_gesture = "none"
        self.stable_count = self.candidate_count = 0
        self.previous_gesture = self.active_gesture = "none"
        self.gesture_entered = False

    def action_allowed(self, action):
        """Allow one click per pinch, while retaining the click cooldown."""
        if self.active_discrete_action is not None:
            return False
        now = monotonic()
        # A stable double-click ENTER is already one-shot and stays latched
        # until every pinch is released. Do not drop a fresh double-click
        # entry just because a separate click happened inside the single-
        # click cooldown window.
        if action == "double_click" or now - self.last_action_time >= CLICK_COOLDOWN:
            self.last_action_time = now
            self.active_discrete_action = action
            return True
        return False
