import math

import numpy as np

from autofisher.bot import BarController, FishingBot, Presser, ZoneTrigger
from autofisher.config import MOUSE, validate
from autofisher.controls import Controls

from fakes import (GREEN, RED, TRACK, WATER, WHITE, YELLOW, Canvas, FakeClock, FakeInput,
                   FishingGame, make_cfg)


def make_bot(cfg, render, clock=None, inputs=None, focus=None):
    assert validate(cfg) == []
    clock = clock or FakeClock()
    inputs = inputs or FakeInput(clock)
    controls = Controls(start_paused=False, log=lambda s: None)
    logs = []
    bot = FishingBot(cfg, Canvas(render), inputs, controls, clock=clock, sleeper=clock.sleep,
                     focus_check=focus, log=logs.append)
    return bot, clock, inputs, controls, logs


def blank():
    img = np.empty((200, 400, 3), dtype=np.uint8)
    img[:] = WATER
    return img


# ------------------------------------------------------------------ controllers

def test_bar_controller_chases_fish_and_respects_direction():
    ctl = BarController(positive=True, deadzone=2, lookahead=0)
    assert ctl.update(fish=100, bar=50, now=0.0) is True
    assert ctl.update(fish=10, bar=50, now=0.1) is False
    up = BarController(positive=False, deadzone=2, lookahead=0)
    assert up.update(fish=10, bar=50, now=0.0) is True  # fish is "above": hold to move up


def test_bar_controller_lets_go_early_when_bar_is_flying_toward_fish():
    ctl = BarController(positive=True, deadzone=2, lookahead=0.2, smoothing=0)
    ctl.update(fish=100, bar=40, now=0.0)
    assert ctl.update(fish=100, bar=80, now=0.1) is False  # 400 px/s -> would overshoot


def test_zone_trigger_fires_inside_zone_once_per_cooldown():
    z = ZoneTrigger(margin=1, lookahead=0, cooldown=0.5)
    assert not z.update(10, (50, 70), 0.0)
    assert z.update(60, (50, 70), 0.1)
    assert not z.update(61, (50, 70), 0.2)  # cooling down
    assert z.update(62, (50, 70), 0.7)
    assert not z.update(None, (50, 70), 1.5)


def test_presser_releases_after_hold_time():
    clock = FakeClock()
    inputs = FakeInput(clock)
    p = Presser(inputs, MOUSE, hold=0.03)
    p.press(0.0)
    p.press(0.01)  # ignored while held
    p.update(0.02)
    assert inputs.is_held(MOUSE)
    p.update(0.03)
    assert not inputs.is_held(MOUSE)
    assert inputs.downs() == 1


# ------------------------------------------------------------------ full loop

def test_default_config_casts_waits_and_spam_clicks():
    cfg = make_cfg()  # click to cast, wait 3s, spam 12 cps for 8s
    bot, clock, inputs, _, logs = make_bot(cfg, blank)
    bot.run(max_cycles=2)
    assert bot.stats.reels == 2
    first_reel_start = 0.05 + 0.5 + 3.0
    clicks = inputs.downs(since=first_reel_start, until=first_reel_start + 8.0)
    assert 94 <= clicks <= 97, clicks
    assert not inputs._held
    assert len([l for l in logs if "reels: " in l]) == 2


def test_bar_minigame_end_to_end():
    clock = FakeClock()
    inputs = FakeInput(clock)
    game = FishingGame(clock, inputs)
    cfg = make_cfg(
        bite__method="detect",
        bite__detector={"region": FishingGame.BITE_REGION, "color": list(RED), "tolerance": 20, "min_pixels": 20},
        bite__on_bite=[{"click": "default"}],
        reel__method="bar",
        reel__bar__region=FishingGame.BAR_REGION,
        reel__bar__fish_color=list(YELLOW),
        reel__bar__bar_color=list(GREEN),
        reel__bar__hold_moves="right",
        after_catch__wait=0.5,
    )
    bot, *_ = make_bot(cfg, game.render, clock=clock, inputs=inputs)
    tracked = [0, 0]  # once the bar has had a second to catch up, the fish should stay inside it

    def measure(dt):
        if game.phase == "reeling" and clock.now - game.t0 > 1.0:
            tracked[1] += 1
            tracked[0] += abs(game.fish() - game.bar) <= game.BAR_HALF

    clock.on_advance.append(measure)
    bot.run(max_cycles=3)
    assert game.caught == 3 and game.lost == 0
    assert bot.stats.reels == 3 and bot.stats.missed == 0
    assert tracked[0] / tracked[1] > 0.95


def test_bite_timeout_recasts():
    cfg = make_cfg(
        bite__method="detect",
        bite__timeout=5.0,
        bite__detector={"region": [0, 0, 10, 10], "color": list(RED), "min_pixels": 5},
        bite__on_timeout=[{"press": "e"}],
    )
    bot, clock, inputs, _, logs = make_bot(cfg, blank)
    bot.run(max_cycles=2)
    assert bot.stats.no_bites == 2
    assert inputs.downs("e") == 2
    assert any("No bite" in l for l in logs)


def test_spam_until_reel_screen_disappears_and_missed_minigame():
    shown = {"until": 0.0}
    clock = FakeClock()

    def render():
        img = blank()
        if clock.now < shown["until"]:
            img[150:160, 10:110] = WHITE  # "progress bar"
        return img

    cfg = make_cfg(
        reel__active_detector={"region": [0, 140, 200, 30], "color": list(WHITE), "min_pixels": 50},
        reel__start_timeout=2.0,
        reel__end_grace=0.3,
    )
    bot, clock, inputs, _, logs = make_bot(cfg, render, clock=clock)
    reel_start = 0.05 + 0.5 + 3.0
    shown["until"] = reel_start + 4.0
    bot.run(max_cycles=2)
    assert bot.stats.reels == 1      # first cycle: bar visible for 4s, then ends
    assert bot.stats.missed == 1     # second cycle: never visible -> missed
    assert any("never showed up" in l for l in logs)


def test_zone_minigame_hits_only_inside_the_zone():
    clock = FakeClock()
    inputs = FakeInput(clock)
    state = {"hits": 0, "misses": 0, "start": None}
    region = [20, 50, 300, 16]

    def marker():
        t = clock.now - state["start"]
        return 150 + 140 * math.sin(2.0 * t)  # sweeps back and forth

    def on_input(kind, name):
        if kind == "down" and name == "space" and state["start"] is not None:
            if 120 <= marker() <= 150:
                state["hits"] += 1
            else:
                state["misses"] += 1

    inputs.on_event.append(on_input)

    def render():
        img = blank()
        if state["start"] is None and clock.now >= 3.0:
            state["start"] = clock.now
        if state["start"] is not None and state["hits"] < 4:
            x, y, w, h = region
            img[y:y + h, x:x + w] = TRACK
            img[y:y + h, x + 120:x + 151] = GREEN
            m = int(round(marker()))
            img[y:y + h, x + m - 1:x + m + 2] = WHITE
        return img

    cfg = make_cfg(
        reel__method="zone", reel__input="space",
        reel__zone__region=region, reel__zone__marker_color=list(WHITE), reel__zone__target_color=list(GREEN),
    )
    bot, *_ = make_bot(cfg, render, clock=clock, inputs=inputs)
    bot.run(max_cycles=1)
    assert state["hits"] == 4 and state["misses"] == 0, (state, inputs.events[:8])
    assert bot.stats.reels == 1


def test_target_mode_clicks_on_popups():
    clock = FakeClock()
    inputs = FakeInput(clock)
    spots = [(60, 60), (300, 150), (200, 40)]
    state = {"i": 0, "next_at": 3.0, "good": 0, "bad": 0}

    def visible():
        return state["i"] < len(spots) and clock.now >= state["next_at"]

    def on_input(kind, name):
        if kind == "down" and name == MOUSE and visible():
            sx, sy = spots[state["i"]]
            x, y = inputs.pos
            if abs(x - sx) <= 8 and abs(y - sy) <= 8:
                state["good"] += 1
                state["i"] += 1
                state["next_at"] = clock.now + 0.3
            else:
                state["bad"] += 1

    inputs.on_event.append(on_input)

    def render():
        img = blank()
        if visible():
            sx, sy = spots[state["i"]]
            img[sy - 8:sy + 9, sx - 8:sx + 9] = RED
        return img

    cfg = make_cfg(reel__method="target", reel__target__region=[0, 0, 400, 200],
                   reel__target__color=list(RED), reel__end_grace=1.0)
    bot, *_ = make_bot(cfg, render, clock=clock, inputs=inputs)
    bot.run(max_cycles=1)
    assert state["good"] == 3 and state["bad"] == 0
    assert bot.stats.reels == 1


def test_quit_mid_reel_releases_everything():
    cfg = make_cfg(reel__method="hold", reel__input="space", reel__duration=30.0)
    clock = FakeClock()
    bot, clock, inputs, controls, _ = make_bot(cfg, blank, clock=clock)
    clock.on_advance.append(lambda dt: controls.request_quit() if clock.now >= 10.0 else None)
    bot.run()
    assert inputs.downs("space") == 1
    assert not inputs._held
    assert 10.0 <= clock.now < 10.1


def test_waits_while_roblox_not_focused_then_restarts():
    clock = FakeClock()
    focused = lambda: not (2.0 <= clock.now < 6.0)  # noqa: E731
    cfg = make_cfg(reel__method="hold", reel__duration=8.0)
    bot, clock, inputs, controls, logs = make_bot(cfg, blank, clock=clock, focus=focused)
    held_while_unfocused = []
    clock.on_advance.append(lambda dt: held_while_unfocused.append(bool(inputs._held))
                            if 2.3 <= clock.now < 6.0 else None)
    bot.run(max_cycles=2)
    assert not any(held_while_unfocused)
    assert any("not the active window" in l for l in logs)
    # the interrupted cycle is abandoned; the next one casts again after focus returns
    casts_after = [t for t, k, n in inputs.events if k == "down" and t >= 6.0]
    assert casts_after and casts_after[0] < 6.6


def test_failsafe_corner_pauses():
    cfg = make_cfg()
    bot, clock, inputs, controls, logs = make_bot(cfg, blank)
    clock.on_advance.append(lambda dt: setattr(inputs, "pos", (0, 0)) if clock.now >= 1.0 else None)
    bot.run(max_cycles=1)
    assert not controls.running
    assert any("fail-safe" in l for l in logs)


def test_auto_sell_runs_every_n_reels():
    cfg = make_cfg(reel__duration=0.5, bite__wait_seconds=0.5,
                   auto_sell__enabled=True, auto_sell__every=2,
                   auto_sell__actions=[{"press": "g"}, {"wait": 0.5}, {"click": [10, 20]}])
    bot, clock, inputs, *_ = make_bot(cfg, blank)
    bot.run(max_cycles=5)
    assert bot.stats.reels == 5
    assert inputs.downs("g") == 2


def test_power_bar_cast_releases_when_detected():
    clock = FakeClock()

    def render():
        img = blank()
        if inputs.is_held(MOUSE) and clock.now >= 1.2:
            img[10:20, 10:20] = GREEN
        return img

    inputs = FakeInput(clock)
    cfg = make_cfg(cast__release_when={"region": [0, 0, 40, 40], "color": list(GREEN), "min_pixels": 50})
    bot, *_ = make_bot(cfg, render, clock=clock, inputs=inputs)
    bot.cast()
    downs = [t for t, k, n in inputs.events if n == MOUSE and k == "down"]
    ups = [t for t, k, n in inputs.events if n == MOUSE and k == "up"]
    assert len(downs) == 1 and 1.2 <= ups[0] < 1.25
