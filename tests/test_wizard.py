import numpy as np

from autofisher.config import validate
from autofisher.wizard import Wizard

from fakes import FakeClock, FakeInput


class SwitchableScreen:
    """Shows a red '!' at (100..110, 50..60) only while `visible` is True."""

    def __init__(self):
        self.visible = True

    def frame(self):
        img = np.zeros((300, 400, 3), dtype=np.uint8)
        if self.visible:
            img[50:60, 100:110] = (255, 0, 0)
        return img

    def grab(self, region):
        x, y, w, h = region
        return self.frame()[y:y + h, x:x + w]

    def pixel(self, x, y):
        return tuple(int(v) for v in self.frame()[y, x])


def run_wizard(answers, captures, screen):
    answers = iter(answers)
    captures = iter(captures)
    out = []

    def capture():
        x, y, after = next(captures)
        rgb = screen.pixel(x, y)
        if after is not None:
            screen.visible = after
        return x, y, rgb

    wiz = Wizard(screen, FakeInput(FakeClock()), input_fn=lambda q: next(answers),
                 out=out.append, capture_fn=capture)
    return wiz.run(), out


def test_wizard_detect_bite_and_bar_reel():
    screen = SwitchableScreen()
    answers = [
        "y",            # fixed click spot
        "1",            # cast: click
        "",             # wait after cast (default)
        "2",            # bite: something appears
        "the ! mark",   # what
        "n",            # no extra colour sample
        "",             # timeout default
        "y", "1",       # hook with mouse
        "3",            # reel: bar
        "1",            # move bar with mouse
        "n", "n",       # one colour sample each for fish and bar
        "1",            # holding moves right
        "3",            # after catch: click a button
        "1.5",          # wait before recasting
        "y", "25",      # auto sell every 25
        "key g", "wait 1", "click", "bogus", "done",
    ]
    captures = [
        (200, 150, None),                                 # click spot
        (95, 45, None), (115, 65, None), (105, 55, None),  # bite box corners + colour (visible)
        (0, 0, False),                                     # "now it's gone"
        (10, 200, True), (300, 220, None),                 # bar region corners
        (105, 55, None), (0, 0, None),                     # fish colour, bar colour
        (390, 290, None),                                  # after-catch close button
        (5, 5, None),                                      # sell click
    ]
    cfg, out = run_wizard(answers, captures, screen)
    assert validate(cfg) == []
    assert cfg["click_position"] == [200, 150]
    det = cfg["bite"]["detector"]
    assert cfg["bite"]["method"] == "detect"
    assert det["region"] == [95, 45, 21, 21]
    assert det["color"] == [255, 0, 0]
    assert det["invert"] is False
    assert 1 <= det["min_pixels"] <= 100  # 100 red px visible, 0 when gone
    assert cfg["bite"]["on_bite"] == [{"click": "default"}]
    assert cfg["reel"]["method"] == "bar"
    assert cfg["reel"]["bar"]["region"] == [10, 200, 291, 21]
    assert cfg["after_catch"] == {"actions": [{"click": [390, 290]}], "wait": 1.5}
    assert cfg["auto_sell"] == {"enabled": True, "every": 25,
                                "actions": [{"press": "g"}, {"wait": 1.0}, {"click": [5, 5]}]}
    assert any("Didn't understand" in line for line in out)


def test_wizard_simple_timed_setup_and_bad_answers():
    screen = SwitchableScreen()
    answers = [
        "n",              # no fixed click spot
        "9", "4", "e",    # bad choice, then hold a key 'e'
        "1", "0.8",       # release after a fixed time
        "0.2",
        "1", "abc", "4",  # bite: just wait (bad number first)
        "n",
        "6", "5",         # reel: nothing, 5 s
        "2", "space",     # after catch: press space
        "",               # wait default
        "n",              # no auto sell
    ]
    cfg, out = run_wizard(answers, [], screen)
    assert validate(cfg) == []
    assert cfg["click_position"] is None
    assert cfg["cast"]["input"] == "e" and cfg["cast"]["hold_seconds"] == 0.8
    assert cfg["bite"] == {**cfg["bite"], "method": "wait", "wait_seconds": 4.0}
    assert cfg["reel"]["method"] == "wait" and cfg["reel"]["duration"] == 5.0
    assert cfg["after_catch"]["actions"] == [{"press": "space"}]
    assert any("number from 1 to" in line for line in out)
    assert any("Please type a number" in line for line in out)
