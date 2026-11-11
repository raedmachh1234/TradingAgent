"""PolicyEngine: which execution mode applies to one decision.

Order of evaluation, each step able only to lower the mode:
  1. configured rules (per strategy, instrument, order size, regime, time of day); the strictest match wins
  2. the strategy's signed autonomy grant (no valid grant: capped at M1)
  3. what the broker adapter can support
  4. run-time downgrades (to M1, or halt)
  5. the M2 conditions; any failure sends the decision to M1

Nothing in this module can raise a mode. Upgrades exist only as grants signed with the operator's private
key, which this process never holds, and they take effect after a cooling-off period.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

import yaml

from ..brokers.base import BrokerCapabilities
from ..core.types import UTC, Decision, Intent, Mode, canonical_json
from . import signing

Sink = Callable[[str, Any], None]
MATCH_KEYS = {"strategy", "instrument", "intent", "notional_gte", "notional_lt", "regime", "time"}


def _tz(name: str):
    return UTC if str(name).upper() == "UTC" else ZoneInfo(str(name))


def _aware(value: Any) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _in_window(now: datetime, tz, window: str) -> bool:
    a, b = (time.fromisoformat(x.strip()) for x in window.split("-"))
    t = now.astimezone(tz).time().replace(tzinfo=None)
    return a <= t <= b if a <= b else (t >= a or t <= b)


@dataclass(frozen=True)
class PolicyContext:
    now: datetime
    notional: float
    risk_passed: bool
    data_fresh: bool
    reconciled: bool


@dataclass(frozen=True)
class ModeResolution:
    mode: Mode
    configured: Mode
    reasons: tuple[str, ...]
    veto_window_seconds: int = 0


class GrantStore:
    """Signed autonomy grants. Fails closed: anything wrong with the file or the signature means no grants."""

    def __init__(self, grants_path: Path | str | None, public_key_path: Path | str | None, cooling_off_hours: Mapping[str, float],
                 sink: Sink | None = None, pinned_fingerprint: str | None = None) -> None:
        self.grants_path = Path(grants_path) if grants_path else None
        self.public_key_path = Path(public_key_path) if public_key_path else None
        self.cooling = {Mode.parse(k): float(v) for k, v in cooling_off_hours.items()}
        self.sink = sink or (lambda etype, payload: None)
        self.pinned = pinned_fingerprint or os.environ.get("QUANTBOT_OPERATOR_KEY_SHA256") or None
        self.public_key = None
        self.grants: list[dict[str, Any]] = []
        self.status = "not loaded"
        self._first_seen: dict[str, datetime] = {}
        self._file_digest: str | None = None

    def restore(self, records: list[dict[str, Any]]) -> None:
        """Rebuild first-seen times from GRANT_SEEN events of an existing audit log."""
        for r in records:
            if r["type"] == "GRANT_SEEN":
                self._first_seen.setdefault(r["payload"]["grant"], _aware(r["payload"]["first_seen"]))

    def reload(self, now: datetime) -> None:
        self.grants, self.public_key = [], None
        try:
            if not self.grants_path or not self.grants_path.exists():
                self.status = "no grants file"
                return
            raw = self.grants_path.read_bytes()
            doc = yaml.safe_load(raw) or {}
            if not doc.get("grants"):
                self.status = "grants file is empty"
                return
            if not self.public_key_path or not self.public_key_path.exists():
                raise ValueError("no operator public key")
            key = signing.load_public_key(self.public_key_path)
            if self.pinned and signing.fingerprint(key) != self.pinned:
                raise ValueError("operator public key does not match the pinned fingerprint")
            if not signing.verify_grants(doc, key):
                raise ValueError("signature does not verify")
            for g in doc["grants"]:
                if Mode.parse(g["max_mode"]) not in (Mode.M2, Mode.M3) or not g.get("strategy") or not g.get("signed_at"):
                    raise ValueError(f"malformed grant: {g}")
            self.grants, self.public_key = list(doc["grants"]), key
            self.status = f"{len(self.grants)} valid grant(s)"
            digest = hashlib.sha256(raw).hexdigest()
            for g in self.grants:
                gid = hashlib.sha256(canonical_json(g).encode()).hexdigest()[:16]
                if gid not in self._first_seen:
                    self._first_seen[gid] = now
                    self.sink("GRANT_SEEN", {"grant": gid, "strategy": g["strategy"], "max_mode": str(g["max_mode"]),
                                             "first_seen": now, "file_sha256": digest})
        except Exception as exc:  # fail closed, and say so in the audit log
            self.grants, self.public_key = [], None
            self.status = f"grants rejected: {exc}"
            self.sink("GRANT_REJECTED", {"reason": str(exc)})

    def max_mode(self, strategy_id: str, now: datetime) -> tuple[Mode, str]:
        best, why = Mode.M1, f"no signed grant for {strategy_id} ({self.status})"
        for g in self.grants:
            if g["strategy"] != strategy_id:
                continue
            mode = Mode.parse(g["max_mode"])
            gid = hashlib.sha256(canonical_json(g).encode()).hexdigest()[:16]
            start = max(_aware(g["signed_at"]), self._first_seen.get(gid, now))
            effective = start + timedelta(hours=max(self.cooling.get(mode, 0.0), float(g.get("cooling_off_hours", 0) or 0)))
            if g.get("expires_at") and now >= _aware(g["expires_at"]):
                why = f"grant for {mode.name} expired"
            elif now < effective:
                why = f"grant for {mode.name} is cooling off until {effective:%Y-%m-%d %H:%M} UTC"
            elif mode > best:
                best, why = mode, f"signed grant {gid}"
        return best, why


class PolicyEngine:
    def __init__(self, cfg: Mapping[str, Any], grants: GrantStore, adapter: BrokerCapabilities, sink: Sink | None = None) -> None:
        pol = cfg["policy"]
        self.default_mode = Mode.parse(pol["default_mode"])
        self.rules: list[tuple[str, dict[str, Any], Mode]] = []
        for i, r in enumerate(pol["rules"]):
            unknown = set(r.get("match", {})) - MATCH_KEYS
            if unknown:
                raise ValueError(f"policy rule {i} uses unknown match keys: {sorted(unknown)}")
            self.rules.append((str(r.get("name", f"rule{i}")), dict(r.get("match", {})), Mode.parse(r["mode"])))
        self.auto = dict(pol["auto"])
        self.blackouts = [(_aware(b["start"]), _aware(b["end"]), str(b.get("label", ""))) for b in self.auto["event_blackouts"]]
        self.actions = {k: str(v).upper() for k, v in cfg["downgrade"].items() if k != "thresholds"}
        self.grants, self.adapter = grants, adapter
        self.sink = sink or (lambda etype, payload: None)
        self._halted: dict[str, str] = {}             # trigger -> detail
        self._global_cap: dict[str, str] = {}         # trigger -> detail (cap is M1)
        self._strategy_cap: dict[str, dict[str, str]] = {}

    # ---- run-time downgrades (only ever lower) ---------------------------------------------------
    @property
    def halted(self) -> bool:
        return bool(self._halted)

    def downgrade(self, trigger: str, detail: str, now: datetime, strategy_id: str | None = None) -> bool:
        """Apply the configured action for a trigger. Returns True when the state changed."""
        action = self.actions[trigger]
        store = self._halted if action == "HALT" else (self._global_cap if strategy_id is None
                                                       else self._strategy_cap.setdefault(strategy_id, {}))
        if trigger in store:
            return False
        store[trigger] = detail
        self.sink("DOWNGRADE", {"trigger": trigger, "action": action, "scope": strategy_id or "global", "detail": detail, "at": now})
        return True

    def clear_downgrade(self, command: signing.OperatorCommand, verifier: signing.CommandVerifier, now: datetime) -> tuple[bool, str]:
        """Lifting a downgrade is an upgrade, so it needs a signed operator command."""
        ok, why = verifier.verify(command, "clear_downgrade", now)
        if not ok:
            self.sink("DOWNGRADE_CLEAR_REFUSED", {"scope": command.scope, "reason": why})
            return False, why
        if command.scope == "global":
            self._halted.clear(), self._global_cap.clear()
        else:
            self._strategy_cap.pop(command.scope, None)
        self.sink("DOWNGRADE_CLEARED", {"scope": command.scope, "at": now})
        return True, "cleared"

    def downgrades(self) -> dict[str, Any]:
        return {"halted": dict(self._halted), "global_m1": dict(self._global_cap),
                "strategies": {k: dict(v) for k, v in self._strategy_cap.items() if v}}

    # ---- mode resolution -------------------------------------------------------------------------
    def _matches(self, match: Mapping[str, Any], d: Decision, ctx: PolicyContext) -> bool:
        for key, want in match.items():
            if key == "strategy":
                ok = fnmatchcase(d.strategy_id, str(want))
            elif key == "instrument":
                ok = fnmatchcase(d.symbol, str(want))
            elif key == "intent":
                ok = d.intent.value == str(want).upper()
            elif key == "notional_gte":
                ok = ctx.notional >= float(want)
            elif key == "notional_lt":
                ok = ctx.notional < float(want)
            elif key == "regime":
                ok = d.regime in (want if isinstance(want, (list, tuple)) else [want])
            else:  # time: {timezone, inside: "HH:MM-HH:MM"} or {timezone, outside: "HH:MM-HH:MM"}, optional weekdays
                tz = _tz(want.get("timezone", "UTC"))
                ok = True
                if "weekdays" in want:
                    ok = ctx.now.astimezone(tz).weekday() in want["weekdays"]
                if "inside" in want:
                    ok = ok and _in_window(ctx.now, tz, want["inside"])
                if "outside" in want:
                    ok = ok and not _in_window(ctx.now, tz, want["outside"])
            if not ok:
                return False
        return True

    def _in_trading_hours(self, now: datetime) -> bool:
        th = self.auto["trading_hours"]
        tz = _tz(th.get("timezone", "UTC"))
        return now.astimezone(tz).weekday() in th.get("weekdays", range(7)) and any(_in_window(now, tz, w) for w in th["windows"])

    def may_deploy_outside_gate(self, strategy_id: str, now: datetime) -> tuple[bool, str]:
        """A live ProOrder script trades outside the gate, so it needs an effective M3 grant (owner decision 5)."""
        granted, why = self.grants.max_mode(strategy_id, now)
        return granted >= Mode.M3, why

    def resolve(self, d: Decision, ctx: PolicyContext) -> ModeResolution:
        reasons: list[str] = []
        matched = [(name, mode) for name, match, mode in self.rules if self._matches(match, d, ctx)]
        configured = min([m for _, m in matched], default=self.default_mode)
        if matched:
            reasons.append("rules matched: " + ", ".join(f"{n}={m.name}" for n, m in matched))
        mode = configured
        granted, why = self.grants.max_mode(d.strategy_id, ctx.now)
        if mode > granted:
            mode = granted
            reasons.append(f"capped at {granted.name}: {why}")
        if not self.adapter.gate_controlled:
            return ModeResolution(Mode.M0, configured, tuple(reasons + [f"{self.adapter.name} runs outside the gate: observe and reconcile only"]))
        if mode not in self.adapter.supported_modes:
            while mode not in self.adapter.supported_modes and mode > Mode.M0:
                mode = Mode(mode - 1)
            reasons.append(f"{self.adapter.name} supports at most {mode.name}")
        if self._halted:
            cap = Mode.M0 if d.intent is Intent.ENTRY else Mode.M1
            if mode > cap or d.intent is Intent.ENTRY:
                mode = min(mode, cap)
                reasons.append("halted by " + ", ".join(sorted(self._halted)) + ("; entries are observed only" if cap is Mode.M0 else ""))
        caps = dict(self._global_cap, **self._strategy_cap.get(d.strategy_id, {}))
        if caps and mode > Mode.M1:
            mode = Mode.M1
            reasons.append("downgraded to M1 by " + ", ".join(sorted(caps)))
        if mode is Mode.M2:
            fails = []
            if not ctx.risk_passed:
                fails.append("risk gate did not pass")
            if ctx.notional > float(self.auto["auto_limit_notional"]):
                fails.append(f"notional {ctx.notional:.2f} is above the auto limit {self.auto['auto_limit_notional']:g}")
            if d.confidence is None or d.confidence < float(self.auto["confidence_threshold"]):
                fails.append("confidence is below the threshold")
            if not self._in_trading_hours(ctx.now):
                fails.append("outside trading hours")
            hit = [label for a, b, label in self.blackouts if a <= ctx.now <= b]
            if hit:
                fails.append("inside event blackout " + (hit[0] or ""))
            if granted < Mode.M2:
                fails.append("strategy is not promoted")
            if not ctx.data_fresh:
                fails.append("data is not fresh")
            if not ctx.reconciled:
                fails.append("broker is not reconciled")
            if fails:
                mode = Mode.M1
                reasons.append("M2 conditions failed: " + "; ".join(fails))
        veto = int(self.auto.get("veto_window_seconds", 0)) if mode is Mode.M2 else 0
        return ModeResolution(mode, configured, tuple(reasons), veto)
