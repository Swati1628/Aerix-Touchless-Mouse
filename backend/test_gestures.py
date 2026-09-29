"""Deterministic gesture-state checks; run with: python -m backend.test_gestures"""
from types import SimpleNamespace

import backend.gestures as gestures
import backend.main as main
import backend.mouse_controller as mouse_controller
from backend.main import AppState
from backend.config import HSCROLL_SENSITIVITY, SCROLL_SENSITIVITY


CLOCK = [0.0]
gestures.monotonic = lambda: CLOCK[0]


def point(x, y):
    return SimpleNamespace(x=x, y=y)


def hand(kind, wrist=(0.5, 0.8)):
    landmarks = [point(0.5, 0.7) for _ in range(21)]
    landmarks[0] = point(*wrist)
    landmarks[4] = point(0.15, 0.70)

    # Start folded: bent PIP joints and tips closer to the wrist.
    for mcp, pip, tip, x in ((5, 6, 8, .38), (9, 10, 12, .50), (13, 14, 16, .62), (17, 18, 20, .74)):
        landmarks[mcp], landmarks[pip], landmarks[tip] = point(x, .65), point(x, .50), point(x + .08, .58)

    def extend(mcp, pip, tip, x):
        landmarks[mcp], landmarks[pip], landmarks[tip] = point(x, .65), point(x, .45), point(x, .20)

    if kind in {"index_only", "index_only_middle_pinch", "index_pinch", "double_pinch", "ring_pinch", "two", "two_middle_pinch", "cross", "hscroll", "palm", "select_drag"}:
        extend(5, 6, 8, .38)
    if kind in {"two", "two_middle_pinch", "double_pinch", "ring_pinch", "ring_folded_index", "index_pinch", "middle_pinch", "cross", "hscroll", "palm", "select_drag"}:
        extend(9, 10, 12, .50)
    if kind in {"hscroll", "palm", "double_pinch", "ring_pinch", "ring_folded_index", "index_pinch", "middle_pinch", "two_middle_pinch", "select_drag"}:
        extend(13, 14, 16, .62)
    if kind in {"palm", "double_pinch", "ring_pinch", "ring_folded_index", "index_pinch", "middle_pinch", "two_middle_pinch", "select_drag"}:
        extend(17, 18, 20, .74)
    if kind in {"middle_pinch", "two_middle_pinch"}:
        extend(5, 6, 8, .38)
    if kind == "cross":
        landmarks[5], landmarks[6], landmarks[8] = point(.38, .65), point(.38, .45), point(.60, .20)
        landmarks[9], landmarks[10], landmarks[12] = point(.50, .65), point(.50, .45), point(.26, .20)
    if kind == "index_only_middle_pinch":
        extend(5, 6, 8, .38)
        # Keep middle/ring/pinky folded, but make the folded middle tip touch
        # the thumb. This reproduces the former right-click false positive.
        landmarks[4] = point(landmarks[12].x, landmarks[12].y)
    if kind == "middle_pinch":
        # Genuine right-click gesture: thumb + middle pinch.
        extend(9, 10, 12, .50)
        landmarks[4] = point(landmarks[12].x, landmarks[12].y)
    if kind == "two_middle_pinch":
        # A natural middle-finger pinch need not fold the index finger.
        landmarks[4] = point(landmarks[12].x, landmarks[12].y)
    if kind == "index_pinch":
        # Thumb + index pinch while every other finger is extended.
        landmarks[4] = point(landmarks[8].x, landmarks[8].y)
    if kind == "double_pinch":
        landmarks[4] = point(.5, .20)
        landmarks[8] = point(.5, .20)
        landmarks[12] = point(.5, .20)
    if kind in {"ring_pinch", "ring_folded_index"}:
        landmarks[4] = point(landmarks[16].x, landmarks[16].y)
    if kind == "select_drag":
        # Thumb + ring pinch while the other fingers stay extended.
        landmarks[4] = point(landmarks[16].x, landmarks[16].y)
    for pip, dip, tip in ((6, 7, 8), (10, 11, 12), (14, 15, 16), (18, 19, 20)):
        landmarks[dip] = point(
            (landmarks[pip].x + landmarks[tip].x) / 2,
            (landmarks[pip].y + landmarks[tip].y) / 2,
        )
    return landmarks


def classifier_at(time_value):
    CLOCK[0] = time_value
    return gestures.GestureClassifier()


def run():
    # Motion deltas produce signed whole wheel detents. Upward hand movement
    # becomes a positive vertical scroll; rightward movement becomes positive
    # horizontal scrolling.
    # main.py negates vertical landmark Y: an upward hand delta (-.02)
    # therefore becomes a positive "scroll up" wheel action.
    assert mouse_controller.motion_to_wheel_steps(-(-.02), SCROLL_SENSITIVITY) == 2
    assert mouse_controller.motion_to_wheel_steps(-(.02), SCROLL_SENSITIVITY) == -2
    assert mouse_controller.motion_to_wheel_steps(.02, HSCROLL_SENSITIVITY) == 2
    assert mouse_controller.motion_to_wheel_steps(0.0, SCROLL_SENSITIVITY) == 0

    # On Windows, hscroll must emit HWHEEL, never the vertical WHEEL path.
    controller = mouse_controller.MouseController.__new__(mouse_controller.MouseController)
    wheel_events = []
    controller._send_windows_wheel = lambda horizontal, steps: wheel_events.append((horizontal, steps))
    original_platform = mouse_controller.sys.platform
    mouse_controller.sys.platform = "win32"
    try:
        assert controller.scroll(2)
        assert controller.hscroll(-3)
    finally:
        mouse_controller.sys.platform = original_platform
    assert wheel_events == [(False, 2), (True, -3)]

    # Index-only has exclusive priority over pinch recognition. In particular,
    # a folded middle fingertip near the thumb must not emit a right click.
    classifier = classifier_at(-1.0)
    gesture = classifier.classify(hand("index_only_middle_pinch"), "Right")[0]
    assert gesture == "move"
    assert gesture != "right_click"
    assert gesture != "left_click"

    # Pinch mappings remain reachable despite index-only move priority.
    classifier = classifier_at(-.9)
    assert classifier.classify(hand("index_pinch"), "Right")[0] == "left_click"
    classifier = classifier_at(-.8)
    assert classifier.classify(hand("middle_pinch"), "Left")[0] == "left_click"
    classifier = classifier_at(-.7)
    assert classifier.classify(hand("middle_pinch"), "Right")[0] == "right_click"
    classifier = classifier_at(-.65)
    assert classifier.classify(hand("two_middle_pinch"), "Right")[0] == "right_click"
    classifier = classifier_at(-.6)
    assert classifier.classify(hand("index_pinch"), "Left")[0] == "right_click"

    # Thumb + ring enters drag, with the remaining fingers extended.
    classifier = classifier_at(-.55)
    assert classifier.classify(hand("ring_pinch"), "Right")[0] == "select_drag"
    classifier = classifier_at(-.551)
    assert classifier.classify(hand("ring_folded_index"), "Right")[0] == "select_drag"
    assert classifier.debug_state["pinches"]["ring"]
    assert not classifier.debug_state["fingers"]["I"]
    classifier = classifier_at(-.551)
    assert classifier.classify(hand("double_pinch"), "Right")[0] == "double_click"
    classifier = classifier_at(-.54)
    assert classifier.classify(hand("index_pinch"), "Right")[0] == "left_click"
    classifier = classifier_at(-.53)
    assert classifier.classify(hand("two"), "Right")[0] == "scroll"

    # The click event is emitted on stable gesture ENTER only. Holding the
    # pinch cannot re-enter, and a release permits a later fresh ENTER.
    classifier = classifier_at(-.52)
    entered = []
    for _ in range(5):
        classifier.classify(hand("index_pinch"), "Right")
        entered.append(classifier.gesture_entered)
    assert entered == [False, False, True, False, False]
    for _ in range(3):
        classifier.classify(hand("index_only"), "Right")
    CLOCK[0] += 0.5
    entered = []
    for _ in range(3):
        classifier.classify(hand("index_pinch"), "Right")
        entered.append(classifier.gesture_entered)
    assert entered == [False, False, True]

    # A dispatched left-click action calls PyAutoGUI exactly once.
    controller = mouse_controller.MouseController.__new__(mouse_controller.MouseController)
    left_click_calls = []
    original_click = mouse_controller.pyautogui.click
    mouse_controller.pyautogui.click = lambda: left_click_calls.append("left")
    try:
        controller.left_click()
    finally:
        mouse_controller.pyautogui.click = original_click
    assert left_click_calls == ["left"]

    # The main-loop dispatcher receives a stable left-click action and calls
    # the controller once; its second frame is latched instead of re-clicking.
    classifier = classifier_at(8.0)
    for time_value in (8.0, 8.1, 8.2):
        CLOCK[0] = time_value
        gesture, confidence, _, _ = classifier.classify(hand("index_pinch"), "Right")
    dispatched_clicks = []
    app = AppState.__new__(AppState)
    app.classifier = classifier
    app.mouse = SimpleNamespace(
        left_click=lambda: dispatched_clicks.append("left"),
        right_click=lambda: dispatched_clicks.append("right"),
        double_click=lambda: dispatched_clicks.append("double"),
    )
    assert app.dispatch_discrete_action(gesture, confidence, "Right")
    CLOCK[0] = 8.8
    assert not app.dispatch_discrete_action(gesture, confidence, "Right")
    assert dispatched_clicks == ["left"]

    # A stable thumb + index + middle pinch reaches the dedicated controller
    # API exactly once; PyAutoGUI is mocked to avoid clicking the live desktop.
    classifier = classifier_at(30.0)
    for time_value in (30.0, 30.1, 30.2, 30.3):
        CLOCK[0] = time_value
        gesture, confidence, _, _ = classifier.classify(hand("double_pinch"), "Right")
    assert gesture == "double_click" and confidence == 1.0
    classifier.last_action_time = 30.25  # Recent unrelated click must not drop this ENTER.
    double_click_calls = []
    original_double_click = mouse_controller.pyautogui.doubleClick
    mouse_controller.pyautogui.doubleClick = lambda **kwargs: double_click_calls.append(kwargs)
    try:
        controller = mouse_controller.MouseController.__new__(mouse_controller.MouseController)
        app = AppState.__new__(AppState)
        app.classifier = classifier
        app.mouse = controller
        app.click_safety = SimpleNamespace(
            evaluate_click=lambda: SimpleNamespace(allowed=True),
            block=lambda decision: None,
        )
        assert app.dispatch_discrete_action(gesture, confidence, "Right")
        assert not app.dispatch_discrete_action(gesture, confidence, "Right")
    finally:
        mouse_controller.pyautogui.doubleClick = original_double_click
    assert double_click_calls == [{"button": "left", "interval": 0.08}]

    # A short but real release rearms double-click even if the generic active
    # gesture label has not yet settled to "none".
    classifier.classify(hand("index_only"), "Right")
    repeated_entries = []
    for time_value in (30.4, 30.5, 30.6):
        CLOCK[0] = time_value
        gesture, confidence, _, _ = classifier.classify(hand("double_pinch"), "Right")
        repeated_entries.append(classifier.gesture_entered)
    assert gesture == "double_click" and confidence == 1.0
    assert repeated_entries == [False, False, True]
    mouse_controller.pyautogui.doubleClick = lambda **kwargs: double_click_calls.append(kwargs)
    try:
        assert app.dispatch_discrete_action(gesture, confidence, "Right")
    finally:
        mouse_controller.pyautogui.doubleClick = original_double_click
    assert double_click_calls == [
        {"button": "left", "interval": 0.08},
        {"button": "left", "interval": 0.08},
    ]

    # Drag button transitions use the left button once each despite repeated
    # enter/release calls; no real desktop input is generated in this test.
    drag_button_calls = []
    original_mouse_down = mouse_controller.pyautogui.mouseDown
    original_mouse_up = mouse_controller.pyautogui.mouseUp
    mouse_controller.pyautogui.mouseDown = lambda **kwargs: drag_button_calls.append(("down", kwargs))
    mouse_controller.pyautogui.mouseUp = lambda **kwargs: drag_button_calls.append(("up", kwargs))
    try:
        controller = mouse_controller.MouseController.__new__(mouse_controller.MouseController)
        controller.dragging = False
        controller.begin_drag()
        controller.begin_drag()
        controller.release()
        controller.release()
    finally:
        mouse_controller.pyautogui.mouseDown = original_mouse_down
        mouse_controller.pyautogui.mouseUp = original_mouse_up
    assert drag_button_calls == [
        ("down", {"button": "left"}),
        ("up", {"button": "left"}),
    ]

    # Stable movement never consumes the click cooldown. A stable pinch is
    # accepted once, then remains latched until its pose ends.
    classifier = classifier_at(10.0)
    for time_value in (10.0, 10.1, 10.2, 10.3):
        CLOCK[0] = time_value
        assert classifier.classify(hand("index_only"), "Right")[0] == "move"
    CLOCK[0] = 10.4
    gesture, confidence, _, _ = classifier.classify(hand("index_pinch"), "Right")
    assert gesture == "left_click" and confidence < 1.0
    CLOCK[0] = 10.5
    gesture, confidence, _, _ = classifier.classify(hand("index_pinch"), "Right")
    assert gesture == "left_click" and confidence < 1.0
    CLOCK[0] = 10.6
    gesture, confidence, _, _ = classifier.classify(hand("index_pinch"), "Right")
    assert gesture == "left_click" and confidence == 1.0
    assert classifier.action_allowed(gesture)
    CLOCK[0] = 11.2
    assert not classifier.action_allowed(gesture)
    CLOCK[0] = 11.3
    assert classifier.classify(hand("index_only"), "Right")[0] == "move"
    CLOCK[0] = 11.4
    assert classifier.classify(hand("index_pinch"), "Right")[0] == "left_click"
    CLOCK[0] = 11.5
    assert classifier.classify(hand("index_pinch"), "Right")[0] == "left_click"
    CLOCK[0] = 11.6
    gesture, confidence, _, _ = classifier.classify(hand("index_pinch"), "Right")
    assert confidence == 1.0 and classifier.action_allowed(gesture)

    # The intended right-hand thumb + middle pinch remains a right click.
    classifier = classifier_at(-0.5)
    assert classifier.classify(hand("middle_pinch"), "Right")[0] == "right_click"

    # Moving V sign remains vertical scroll.
    classifier = classifier_at(0.0)
    assert classifier.classify(hand("two"))[0] == "scroll"
    CLOCK[0] = .20
    assert classifier.classify(hand("two", wrist=(.50, .68)))[0] == "scroll"
    CLOCK[0] = 1.0
    assert classifier.classify(hand("two", wrist=(.50, .68)))[0] == "scroll"

    # Three fingers (index + middle + ring) is horizontal scroll, not
    # vertical scroll, and carries horizontal hand motion for the action.
    classifier = classifier_at(1.2)
    assert classifier.classify(hand("hscroll"))[0] == "hscroll"
    CLOCK[0] = 1.4
    gesture, _, delta_x, delta_y = classifier.classify(hand("hscroll", wrist=(.53, .8)))
    assert gesture == "hscroll"
    assert delta_x > 0 and delta_y == 0.0

    # A stationary V sign remains vertical scrolling indefinitely; it can no
    # longer enter any drag classifier path.
    classifier = classifier_at(2.0)
    assert classifier.classify(hand("two"))[0] == "scroll"
    CLOCK[0] = 2.70
    assert classifier.classify(hand("two"))[0] == "scroll"

    # Thumb + ring starts and holds drag even with the index folded.
    events = []
    class SelectDragMouse:
        dragging = False
        def begin_drag(self):
            if not self.dragging:
                self.dragging = True
                events.append("down")
        def release(self):
            if self.dragging:
                self.dragging = False
                events.append("up")
    app = AppState.__new__(AppState)
    app.mouse = SelectDragMouse()
    app.classifier = SimpleNamespace(debug_state={"pinches": {"ring": True}, "fingers": {"I": False}})
    app.click_safety = SimpleNamespace(
        evaluate_click=lambda: SimpleNamespace(allowed=True),
        block=lambda decision: None,
    )
    app.drag_candidate = False
    original_monotonic = main.time.monotonic
    main.time.monotonic = lambda: CLOCK[0]
    try:
        CLOCK[0] = 20.0
        assert app.update_select_drag(1.0, "Right")
        CLOCK[0] = 20.49
        assert app.update_select_drag(1.0, "Right")
        assert events == ["down"]
        app.reset_select_drag()
    finally:
        main.time.monotonic = original_monotonic
    assert events == ["down", "up"]
    assert not app.drag_candidate

    # Palm swipes fire once in each direction.
    classifier = classifier_at(3.0)
    assert classifier.classify(hand("palm"))[0] == "palm"
    CLOCK[0] = 3.25
    assert classifier.classify(hand("palm", wrist=(.62, .8)))[0] == "tab_next"
    CLOCK[0] = 3.40
    assert classifier.classify(hand("palm", wrist=(.62, .8)))[0] == "palm"

    classifier = classifier_at(4.0)
    classifier.classify(hand("palm"))
    CLOCK[0] = 4.25
    assert classifier.classify(hand("palm", wrist=(.38, .8)))[0] == "tab_previous"

    # A stationary palm is intentionally inert; only palm swipes act.
    classifier = classifier_at(5.0)
    classifier.classify(hand("palm"))
    CLOCK[0] = 5.90
    assert classifier.classify(hand("palm"))[0] == "palm"

    # Crossed fingers fire browser back once; a normal V never does.
    classifier = classifier_at(6.0)
    assert classifier.classify(hand("cross"))[0] == "browser_back"
    CLOCK[0] = 6.10
    assert classifier.classify(hand("cross"))[0] == "crossed_hold"
    classifier = classifier_at(7.0)
    assert classifier.classify(hand("two"))[0] != "browser_back"
    print("Gesture classifier checks passed.")


if __name__ == "__main__":
    run()
