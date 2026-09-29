import math
import sys
import traceback

import pyautogui

from .config import (
    CURSOR_MAX_STEP,
    CURSOR_SAFE_MAX,
    CURSOR_SAFE_MIN,
    CURSOR_SMOOTHING,
    CURSOR_DEADZONE,
)


WINDOWS_WHEEL_DELTA = 120
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000


def motion_to_wheel_steps(delta, sensitivity):
    """Convert a non-zero normalized hand delta into signed wheel detents."""
    if not math.isfinite(delta) or not math.isfinite(sensitivity) or delta == 0:
        return 0
    steps = max(1, round(abs(delta) * sensitivity))
    return steps if delta > 0 else -steps


class MouseController:
    def __init__(self):
        self.w, self.h = pyautogui.size()
        self.dragging = False

        # Keep the cursor away from the extreme screen corners.
        self.edge_margin = 20
        self.filtered_x = None
        self.filtered_y = None
        self.last_position = None

    def reset_tracking(self):
        """Forget the previous cursor target after tracking is lost."""
        self.filtered_x = None
        self.filtered_y = None

    def move(self, x, y):
        if not math.isfinite(x) or not math.isfinite(y):
            return False

        x = max(CURSOR_SAFE_MIN, min(CURSOR_SAFE_MAX, x))
        y = max(CURSOR_SAFE_MIN, min(CURSOR_SAFE_MAX, y))

        if self.filtered_x is None or self.filtered_y is None:
            # Start from the real cursor position. A first-frame landmark
            # glitch must pass through the same step limiter as every other
            # frame instead of teleporting the cursor across the display.
            current_x, current_y = pyautogui.position()
            self.filtered_x = max(CURSOR_SAFE_MIN, min(CURSOR_SAFE_MAX, current_x / self.w))
            self.filtered_y = max(CURSOR_SAFE_MIN, min(CURSOR_SAFE_MAX, current_y / self.h))

        delta_x = x - self.filtered_x
        delta_y = y - self.filtered_y
        distance = math.hypot(delta_x, delta_y)

        if distance < CURSOR_DEADZONE:
            return True

        if distance > CURSOR_MAX_STEP:
            scale = CURSOR_MAX_STEP / distance
            delta_x *= scale
            delta_y *= scale

        self.filtered_x += delta_x * CURSOR_SMOOTHING
        self.filtered_y += delta_y * CURSOR_SMOOTHING

        screen_x = max(
            self.edge_margin,
            min(
                self.w - 1 - self.edge_margin,
                int(self.filtered_x * self.w)
            )
        )

        screen_y = max(
            self.edge_margin,
            min(
                self.h - 1 - self.edge_margin,
                int(self.filtered_y * self.h)
            )
        )
        self.last_position = (screen_x, screen_y)

        try:
            pyautogui.moveTo(screen_x, screen_y)
        except pyautogui.FailSafeException:
            # Keep PyAutoGUI's fail-safe enabled, but do not let its
            # protective exception terminate the camera-processing thread.
            return False

        return True

    def left_click(self):
        try:
            pyautogui.click()
        except Exception as exc:  # pragma: no cover - runtime OS interaction
            print(f"PyAutoGUI left_click failed: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            raise

    def right_click(self):
        try:
            pyautogui.rightClick()
        except Exception as exc:  # pragma: no cover - runtime OS interaction
            print(f"PyAutoGUI right_click failed: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            raise

    def double_click(self):
        print("MOUSE CONTROLLER: double_click()")
        try:
            pyautogui.doubleClick(button="left", interval=0.08)
        except Exception as exc:  # pragma: no cover - runtime OS interaction
            print(f"PyAutoGUI double_click failed: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            raise

    @staticmethod
    def _wheel_steps(amount):
        """Return a signed whole number of wheel detents, or zero."""
        if not math.isfinite(amount) or amount == 0:
            return 0
        steps = max(1, round(abs(amount)))
        return steps if amount > 0 else -steps

    def _send_windows_wheel(self, horizontal, steps):
        """Send a real Windows wheel event to the window below the cursor."""
        import ctypes

        flag = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
        wheel_delta = ctypes.c_ulong(steps * WINDOWS_WHEEL_DELTA).value
        ctypes.windll.user32.mouse_event(flag, 0, 0, wheel_delta, 0)

    def scroll(self, amount=5):
        """Vertical scroll at the cursor. Positive = up, negative = down."""
        steps = self._wheel_steps(amount)
        if not steps:
            return False
        if sys.platform.startswith("win"):
            self._send_windows_wheel(horizontal=False, steps=steps)
        else:
            pyautogui.scroll(steps)
        return True

    def hscroll(self, amount=5):
        """Horizontal scroll at the cursor. Positive = right, negative = left."""
        steps = self._wheel_steps(amount)
        if not steps:
            return False
        if sys.platform.startswith("win"):
            # PyAutoGUI's Windows hscroll currently calls its vertical scroll
            # backend. Send MOUSEEVENTF_HWHEEL directly instead.
            self._send_windows_wheel(horizontal=True, steps=steps)
        elif hasattr(pyautogui, "hscroll"):
            pyautogui.hscroll(steps)
        else:
            pyautogui.keyDown("shift")
            pyautogui.scroll(steps)
            pyautogui.keyUp("shift")
        return True

    def zoom(self, amount=1):
        """Zoom in/out via ctrl+scroll."""
        pyautogui.keyDown("ctrl")
        pyautogui.scroll(int(amount))
        pyautogui.keyUp("ctrl")

    def begin_drag(self):
        """Hold the button down once; repeated drag frames are harmless."""
        if not self.dragging:
            pyautogui.mouseDown(button="left")
            self.dragging = True
            print("MOUSEDOWN: EXECUTED")

    def next_tab(self):
        pyautogui.hotkey("ctrl", "tab")

    def previous_tab(self):
        pyautogui.hotkey("ctrl", "shift", "tab")

    def browser_back(self):
        pyautogui.hotkey("alt", "left")

    def release(self):
        if self.dragging:
            pyautogui.mouseUp(button="left")
            self.dragging = False
            print("MOUSEUP: EXECUTED")
