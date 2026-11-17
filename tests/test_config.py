import copy
import json

import pytest

from autofisher.config import DEFAULTS, ConfigError, dumps, iter_key_inputs, load_config, save_config, validate


def test_defaults_are_valid():
    assert validate(copy.deepcopy(DEFAULTS)) == []


def test_missing_file_uses_defaults(tmp_path):
    cfg, warnings = load_config(str(tmp_path / "nope.json"))
    assert cfg == DEFAULTS
    assert warnings


def test_partial_config_is_merged_and_unknown_keys_warned(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "_comment": "comments are allowed",
        "reel": {"method": "hold", "input": "space"},
        "cats": 3,
    }))
    cfg, warnings = load_config(str(path))
    assert cfg["reel"]["method"] == "hold"
    assert cfg["reel"]["input"] == "space"
    assert cfg["reel"]["clicks_per_second"] == DEFAULTS["reel"]["clicks_per_second"]
    assert any("cats" in w for w in warnings)


def test_invalid_json_is_reported(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"reel": {"method": "spam",}}')
    with pytest.raises(ConfigError) as e:
        load_config(str(path))
    assert "line 1" in e.value.problems[0]


@pytest.mark.parametrize("patch, expected", [
    ({"bite": {"method": "detect"}}, "bite.detector is required"),
    ({"reel": {"method": "bar"}}, "reel.bar.region is required"),
    ({"reel": {"method": "teleport"}}, "reel.method must be one of"),
    ({"cast": {"input": "F6"}}, "cast.input must be"),
    ({"cast": {"input": "f6"}}, "also a hotkey"),
    ({"hotkeys": {"quit": "f6"}}, "must all be different"),
    ({"click_position": [1, 2, 3]}, "click_position must be [x, y]"),
    ({"bite": {"method": "detect", "detector": {"region": [0, 0, 0, 5], "color": [1, 2, 3]}}},
     "bite.detector.region"),
    ({"bite": {"method": "detect", "detector": {"region": [0, 0, 5, 5], "color": [1, 2, 300]}}},
     "bite.detector.color"),
    ({"after_catch": {"actions": [{"press": "e", "click": None}]}}, "exactly one of"),
    ({"auto_sell": {"enabled": True}}, "auto_sell.actions is empty"),
    ({"reel": {"clicks_per_second": 0}}, "reel.clicks_per_second must be at least"),
])
def test_validation_catches_mistakes(tmp_path, patch, expected):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(patch))
    with pytest.raises(ConfigError) as e:
        load_config(str(path))
    assert any(expected in p for p in e.value.problems), e.value.problems


def test_save_roundtrip_keeps_backup_and_inline_lists(tmp_path):
    path = tmp_path / "config.json"
    cfg = copy.deepcopy(DEFAULTS)
    cfg["click_position"] = [960, 540]
    cfg["bite"]["method"] = "detect"
    cfg["bite"]["detector"] = {"region": [10, 20, 30, 40], "color": [[1, 2, 3], [4, 5, 6]],
                               "tolerance": 30, "min_pixels": 12, "invert": False}
    save_config(cfg, str(path))
    save_config(cfg, str(path))
    assert (tmp_path / "config.json.bak").exists()
    text = path.read_text()
    assert '"click_position": [960, 540]' in text
    assert '"region": [10, 20, 30, 40]' in text
    loaded, warnings = load_config(str(path))
    assert loaded == cfg and warnings == []
    assert json.loads(dumps(cfg)) == cfg


def test_iter_key_inputs():
    cfg = copy.deepcopy(DEFAULTS)
    cfg["reel"]["input"] = "space"
    cfg["after_catch"]["actions"] = [{"press": "e"}, {"wait": 1}, {"hold": "w", "duration": 2}]
    assert list(iter_key_inputs(cfg)) == [
        ("reel.input", "space"),
        ("after_catch.actions[0].press", "e"),
        ("after_catch.actions[2].hold", "w"),
    ]
