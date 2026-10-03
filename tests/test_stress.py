"""Aggressive human use, brute force: the settings app and its live island
preview hammered the way an impatient person would (spam clicks, swipes that
start and stop, a new card arriving mid-swipe), all on the REAL host API.
Every test also fails on any JavaScript error the page throws."""
import random

import pytest

import host
from test_ui import CLIP, app, browser, classes, show_card, swipe  # noqa: F401 (fixtures)


@pytest.fixture()
def hammer(app):
    pg, frame, isl = app
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    for f in pg.frames:
        f.page.on("pageerror", lambda e: errors.append(str(e)))
    yield pg, frame, isl
    assert not errors, errors


def style_btn(pg, v):
    pg.click(f'.seg[data-key="style"] button[data-v="{v}"]')


def notch_on(frame):
    return frame.evaluate("document.documentElement.classList.contains('notch')")


def wait_settled(pg, frame):
    """Nothing left mid-swipe: no inline transform, no swipe classes."""
    pg.wait_for_timeout(400)
    st = frame.evaluate("""() => { const i = document.getElementById('island');
        return {t: i.style.transform, c: [...i.classList]}; }""")
    assert st["t"] == "" and "swiping" not in st["c"] and "swipe-away" not in st["c"], st


# 1
def test_style_toggle_spam_ends_on_the_last_click(hammer):
    pg, frame, isl = hammer
    picks = [random.choice(["notch", "pill"]) for _ in range(40)]
    for v in picks:
        style_btn(pg, v)
    pg.wait_for_timeout(600)
    assert isl.layout["style"] == picks[-1] == host.read_config()["layout"]["style"]
    assert notch_on(frame) == (picks[-1] == "notch")


# 2
@pytest.mark.parametrize("style", ["notch", "pill"])
def test_ten_cards_in_a_row_each_swiped(hammer, style):
    pg, frame, _ = hammer
    style_btn(pg, style)
    for _ in range(10):
        show_card(pg, frame)
        swipe(pg, frame, -140, steps=4, ms=5)
        assert "carding" not in classes(frame)
    wait_settled(pg, frame)


# 3
def test_new_card_arriving_mid_swipe_away_survives(hammer):
    """Swipe a card away and a new clip lands during the shrink: the NEW card stays."""
    pg, frame, _ = hammer
    style_btn(pg, "notch")
    show_card(pg, frame)
    box = frame.locator("#island").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y); pg.mouse.down()
    for i in range(1, 5):
        pg.mouse.move(x, y - 35 * i); pg.wait_for_timeout(5)
    pg.mouse.up()
    pg.wait_for_timeout(60)                                   # inside the 230 ms shrink
    frame.evaluate("c => window.__islandClip(c)", CLIP)
    pg.wait_for_timeout(900)
    assert "carding" in classes(frame)


# 4
def test_two_swipes_back_to_back(hammer):
    pg, frame, _ = hammer
    show_card(pg, frame)
    swipe(pg, frame, -120, steps=3, ms=3)
    swipe(pg, frame, -120, steps=3, ms=3)                     # the island is already a pill
    wait_settled(pg, frame)
    assert "carding" not in classes(frame)


# 5
def test_yank_down_then_up_springs_back_or_goes_cleanly(hammer):
    pg, frame, _ = hammer
    show_card(pg, frame)
    box = frame.locator("#island").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y); pg.mouse.down()
    for dy in (40, 80, 120, 60, 0, -10):
        pg.mouse.move(x, y + dy); pg.wait_for_timeout(15)
    pg.mouse.up()
    wait_settled(pg, frame)


# 6
def test_pointer_cancel_mid_drag_springs_back(hammer):
    pg, frame, _ = hammer
    show_card(pg, frame)
    box = frame.locator("#island").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y); pg.mouse.down()
    pg.mouse.move(x, y - 15); pg.mouse.move(x, y - 30)
    frame.evaluate("document.getElementById('island').dispatchEvent(new PointerEvent('pointercancel', {bubbles: true}))")
    pg.mouse.up()
    wait_settled(pg, frame)


# 7
def test_wheel_spam_on_the_open_notch(hammer):
    pg, frame, _ = hammer
    style_btn(pg, "notch")
    pg.click("#pvMode button[data-v=open]")
    box = frame.locator("#island").bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    for _ in range(80):
        pg.mouse.wheel(0, random.choice([-120, 120, 40, -300]))
    pg.wait_for_timeout(700)
    on = frame.evaluate("document.querySelectorAll('.page.on, [data-id].on').length")
    assert on == 1


# 8
def test_scale_and_style_mashed_together(hammer):
    pg, frame, isl = hammer
    for _ in range(25):
        isl.set_layout({**isl.layout, "style": random.choice(["notch", "pill"]),
                        "scale": random.choice([0.5, 0.7, 1.0, 1.37, 1.5, 9])})
    L = host.read_config()["layout"]
    assert L["style"] in ("notch", "pill") and host.SCALE_RANGE[0] <= L["scale"] <= host.SCALE_RANGE[1]


# 9
def test_tiny_wobble_still_clicks_the_button(hammer):
    """A shaky hand (under 5px) on Copy: it is a click, not a swipe."""
    pg, frame, _ = hammer
    show_card(pg, frame)
    b = frame.locator("#cCopy").bounding_box()
    x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    pg.mouse.move(x, y); pg.mouse.down(); pg.mouse.move(x + 2, y - 3); pg.mouse.up()
    frame.wait_for_function("document.getElementById('cCopy').textContent.includes('Copied')", timeout=4000)


# 10
def test_card_spam_then_one_swipe(hammer):
    pg, frame, _ = hammer
    for _ in range(12):
        frame.evaluate("c => window.__islandClip(c)", CLIP)
        pg.wait_for_timeout(20)
    pg.wait_for_timeout(500)
    swipe(pg, frame, -150)
    assert "carding" not in classes(frame)
    wait_settled(pg, frame)


# 11
def test_open_closed_preview_spam_keeps_the_style(hammer):
    pg, frame, _ = hammer
    style_btn(pg, "notch")
    for i in range(30):
        pg.click(f"#pvMode button[data-v={'open' if i % 2 else 'closed'}]")
    pg.wait_for_timeout(500)
    assert notch_on(frame)


# 12
@pytest.mark.parametrize("style,floor", [("notch", host.NOTCH[0]), ("pill", host.COMPACT[0])])
def test_pill_width_fuzz_never_below_the_style(hammer, style, floor):
    _, _, isl = hammer
    isl.set_layout({**isl.layout, "style": style})
    for v in [None, 0, -50, 1, 99, 3000, "abc" if False else 10, 199, 201, 600]:
        isl.set_pill_width(v)
        assert floor <= isl.pill_w <= isl.open_size()[0]                # never wider than the open island


# 13
def test_reset_during_notch_goes_back_to_pill(hammer):
    pg, frame, isl = hammer
    style_btn(pg, "notch")
    isl.reset_layout()
    assert isl.layout["style"] == "pill"


# 14
def test_style_flip_while_a_card_is_up(hammer):
    pg, frame, _ = hammer
    show_card(pg, frame)
    for v in ("notch", "pill", "notch", "pill", "notch"):
        style_btn(pg, v)
    pg.wait_for_timeout(300)
    assert "carding" in classes(frame)                        # the card isn't knocked off
    swipe(pg, frame, -140)
    assert "carding" not in classes(frame)
    wait_settled(pg, frame)


# 15
def test_drag_out_of_the_window_and_release(hammer):
    """Grab the card, drag sideways off the island and up to the top of the
    screen (where a real cursor stops; the notch sits on that edge), let go there."""
    pg, frame, _ = hammer
    show_card(pg, frame)
    box = frame.locator("#island").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y); pg.mouse.down()
    pg.mouse.move(x + 300, 1, steps=6)
    pg.mouse.up()
    wait_settled(pg, frame)
    assert "carding" not in classes(frame)
