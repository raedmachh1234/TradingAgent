"""Configuration: open owner inputs are parameters with documented defaults; nothing can default above M1."""
from __future__ import annotations

import pytest
import yaml

from quantbot.core.config import ConfigError, load_config


def test_open_inputs_are_parameters_with_defaults():
    cfg = load_config(read_user_file=False)
    assert cfg["account"]["paper_capital"] == 10000
    assert cfg["account"]["currency"]
    assert cfg["markets"]["instruments"] and cfg["markets"]["bar_frequency"]
    assert cfg["hardware"]["device"] == "cpu"
    assert cfg["budget"]["data_monthly"] == 0
    assert "path" in cfg["trade_history"]
    assert cfg["policy"]["default_mode"] == "M1"


def test_user_file_overrides_and_unknown_keys_are_rejected(tmp_path):
    f = tmp_path / "q.yaml"
    f.write_text(yaml.safe_dump({"account": {"paper_capital": 25000}}))
    assert load_config(f)["account"]["paper_capital"] == 25000
    f.write_text(yaml.safe_dump({"account": {"paper_capitol": 25000}}))  # typo
    with pytest.raises(ConfigError, match="unknown configuration key"):
        load_config(f)
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.yaml")


@pytest.mark.parametrize("mode", ["M2", "M3"])
def test_default_mode_cannot_be_autonomous(mode):
    with pytest.raises(ConfigError, match="signed grants"):
        load_config(overrides={"policy": {"default_mode": mode}}, read_user_file=False)


@pytest.mark.parametrize("override, message", [
    ({"downgrade": {"daily_loss": "M2"}}, "M1 or HALT"),
    ({"account": {"paper_capital": 0}}, "positive"),
    ({"risk": {"max_order_notional": -5}}, "positive"),
    ({"strategies": [{"id": "x", "class": "ma_crossover", "symbols": ["NOPE"]}]}, "unknown instruments"),
    ({"strategies": [{"id": "x", "class": "ma_crossover", "symbols": []}, {"id": "x", "class": "ma_crossover", "symbols": []}]}, "unique"),
])
def test_invalid_settings_are_rejected(override, message):
    with pytest.raises(ConfigError, match=message):
        load_config(overrides=override, read_user_file=False)


def test_lists_are_replaced_not_merged():
    cfg = load_config(overrides={"policy": {"rules": [{"name": "r", "match": {"strategy": "*"}, "mode": "M0"}]}},
                      read_user_file=False)
    assert len(cfg["policy"]["rules"]) == 1
