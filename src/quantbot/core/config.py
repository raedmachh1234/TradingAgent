"""Configuration: packaged defaults, an optional user file, optional overrides. Unknown keys are errors."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping

import yaml

from .types import Instrument

DEFAULTS_PATH = Path(__file__).resolve().parents[1] / "default_config.yaml"
# Sections whose content is a free-form list or mapping, replaced wholesale rather than merged key by key.
OPEN_PATHS = {"strategies", "markets.instruments", "policy.rules", "policy.auto.event_blackouts",
              "risk.blocked_symbols", "approval.channels", "approval.telegram.allowed_user_ids", "data.providers",
              "policy.auto.trading_hours"}


class ConfigError(ValueError):
    pass


def _merge(base: dict[str, Any], extra: Mapping[str, Any], path: str = "") -> dict[str, Any]:
    for key, value in extra.items():
        here = f"{path}.{key}" if path else str(key)
        if key not in base:
            raise ConfigError(f"unknown configuration key: {here}")
        if isinstance(base[key], dict) and here not in OPEN_PATHS:
            if not isinstance(value, Mapping):
                raise ConfigError(f"{here} must be a mapping")
            _merge(base[key], value, here)
        else:
            base[key] = copy.deepcopy(value)
    return base


def load_config(user_file: Path | str | None = None, overrides: Mapping[str, Any] | None = None, *,
                read_user_file: bool = True) -> dict[str, Any]:
    """Defaults, then the user file (config/quantbot.yaml if present), then explicit overrides.

    read_user_file=False gives the packaged defaults only (tests and the demo, so they never depend on
    someone's personal settings).
    """
    with open(DEFAULTS_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    candidate = Path(user_file) if user_file else Path(os.environ.get("QUANTBOT_CONFIG", "config/quantbot.yaml"))
    if user_file is None and not read_user_file:
        pass
    elif candidate.exists():
        with open(candidate, "r", encoding="utf-8") as f:
            _merge(cfg, yaml.safe_load(f) or {})
    elif user_file:
        raise ConfigError(f"configuration file not found: {candidate}")
    if overrides:
        _merge(cfg, overrides)
    validate(cfg)
    return cfg


def validate(cfg: Mapping[str, Any]) -> None:
    def positive(path: str) -> None:
        node: Any = cfg
        for part in path.split("."):
            node = node[part]
        if not isinstance(node, (int, float)) or isinstance(node, bool) or node <= 0:
            raise ConfigError(f"{path} must be a positive number, got {node!r}")

    for p in ("account.paper_capital", "risk.max_order_notional", "risk.max_risk_per_trade_pct", "risk.max_position_pct",
              "risk.max_gross_exposure_pct", "risk.daily_loss_limit_pct", "risk.max_drawdown_pct", "risk.max_orders_per_minute",
              "risk.max_orders_per_day", "execution.proposal_ttl_seconds", "execution.price_drift_tolerance_bps"):
        positive(p)
    if str(cfg["policy"]["default_mode"]).upper() not in ("M0", "M1"):
        raise ConfigError("policy.default_mode may only be M0 or M1; higher modes come from signed grants, never from a default")
    for trig, action in cfg["downgrade"].items():
        if trig != "thresholds" and str(action).upper() not in ("M1", "HALT"):
            raise ConfigError(f"downgrade.{trig} must be M1 or HALT")
    ids = [s["id"] for s in cfg["strategies"]]
    if len(ids) != len(set(ids)):
        raise ConfigError("strategy ids must be unique")
    known = {i["symbol"] for i in cfg["markets"]["instruments"]}
    for s in cfg["strategies"]:
        missing = set(s.get("symbols", [])) - known
        if missing:
            raise ConfigError(f"strategy {s['id']} trades unknown instruments: {sorted(missing)}")


def instruments(cfg: Mapping[str, Any]) -> dict[str, Instrument]:
    return {i["symbol"]: Instrument(**i) for i in cfg["markets"]["instruments"]}


def load_env_file(path: Path | str = ".env") -> list[str]:
    """Minimal .env reader: KEY=VALUE lines become environment variables unless already set. Returns the keys read."""
    keys: list[str] = []
    p = Path(path)
    if not p.exists():
        return keys
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))
        keys.append(key)
    return keys
