"""The Phase 1 demonstration: data layer, human-confirm replay, four-mode equivalence, safety checks, audit log.

Everything runs offline on seeded synthetic data against the paper broker. No network, no credentials.
The four-mode comparison uses a throwaway operator key and a throwaway grant inside the demo's own sandbox
folder; the project's real configuration is not touched and stays at M1.
"""
from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from .core.clock import SimClock
from .core.config import load_config
from .core.eventlog import verify_file
from .core.types import UTC, Mode
from .data.providers import FailingProvider, SyntheticProvider
from .data.service import DataService, replay_feed
from .data.store import DataStore
from .execution import signing
from .execution.approval import HumanDecision, OperatorKeyAuthenticator, sign_decision
from .execution.channels.cli import CliChannel
from .execution.proposal import Proposal, State
from .execution.scripted import ScriptedHuman, approve_all
from .orchestrator import Orchestrator

START, END = datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 12, 31, tzinfo=UTC)
SESSION_START = datetime(2024, 12, 1, tzinfo=UTC)


def _mixed_rule() -> Callable[[Proposal], tuple[str, dict[str, Any]]]:
    """A scripted operator who mostly approves, sometimes rejects, edits or does not answer."""
    seen: dict[str, int] = {}

    def rule(p: Proposal) -> tuple[str, dict[str, Any]]:
        if p.decision.intent.value == "EXIT":
            return "approve", {}
        n = seen.setdefault(p.id, len(seen) + 1)  # entries only
        if n % 5 == 0:
            return "reject", {"reason": "demo: operator disagrees with this entry"}
        if n % 7 == 0:
            return "edit", {"edits": {"quantity": max(1.0, float(int(p.order.quantity / 2)))}}
        if n % 6 == 0:
            return "ignore", {}
        return "approve", {}

    return rule


def _orchestrator(cfg: dict, sandbox: Path, key, log_name: str | None = None) -> Orchestrator:
    orch = Orchestrator(cfg, base_dir=sandbox, event_log=(sandbox / log_name) if log_name else None, start=SESSION_START)
    orch.add_channel(CliChannel(), OperatorKeyAuthenticator(key.public_key()))
    return orch


def _sandbox_grant(sandbox: Path, key, strategy_ids: list[str], mode: Mode) -> None:
    """Write a throwaway signed grant inside the sandbox (never in the project's config folder)."""
    (sandbox / "config").mkdir(parents=True, exist_ok=True)
    doc = {"version": 1, "grants": [{"strategy": s, "max_mode": mode.name, "signed_at": "2024-01-01T00:00:00+00:00",
                                     "evidence": "demo sandbox only"} for s in strategy_ids]}
    (sandbox / "config" / "autonomy.yaml").write_text(yaml.safe_dump(signing.sign_grants(doc, key)), encoding="utf-8")
    signing.save_public_key(key.public_key(), sandbox / "config" / "operator.pub")


def run_demo(workdir: Path | str, out: Callable[[str], None] = print) -> dict[str, Any]:
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    base = load_config(read_user_file=False)  # packaged defaults, so the demo is the same on every machine
    symbols = sorted({s for spec in base["strategies"] for s in spec["symbols"]})
    cur = base["account"]["currency"]
    results: dict[str, Any] = {}
    out("quantbot demo: synthetic data, paper broker, packaged default settings, no network, no credentials")
    out(f"working folder: {work}")

    # 1. data layer ---------------------------------------------------------------------------------
    out("")
    out("[1] Data layer: cache, lineage, fallback, quality checks")
    store = DataStore(work / "cache")
    clock = SimClock(datetime.now(UTC))
    svc = DataService(store, [FailingProvider("primary-demo"), SyntheticProvider(**base["data"]["synthetic"])], clock,
                      base["markets"]["bar_frequency"], base["data"]["quality"])
    first = [svc.ensure_bars("demo", s, START, END) for s in symbols]
    second = [svc.ensure_bars("demo", s, START, END) for s in symbols]
    for r in first:
        if r.ingests:
            rec = r.ingests[0]
            out(f"    {r.symbol}: provider 'primary-demo' failed, fell back to '{rec.provider}': {rec.rows_total} bars "
                f"{rec.first_ts:%Y-%m-%d}..{rec.last_ts:%Y-%m-%d}; quality: {r.quality[0].summary()}")
        else:
            out(f"    {r.symbol}: already cached from an earlier run")
    out(f"    second request: {'cache hit, nothing fetched' if all(r.cache_hit for r in second) else 'refetched'}")
    man = store.manifest()
    out(f"    catalog records provider, retrieval time and terms for {len(man)} datasets "
        f"(terms: \"{man['terms'].iloc[0]}\")")
    results["data"] = {"fallback_used": all((not r.ingests) or r.ingests[0].provider == "synthetic" for r in first),
                       "cache_hit": all(r.cache_hit for r in second), "rows": int(man["rows"].sum())}
    feed = lambda: replay_feed(store, "demo", symbols, START, END)

    # 2. the default: M1 human-confirm --------------------------------------------------------------
    out("")
    out("[2] M1 human-confirm replay (the project default): a scripted operator approves, rejects, edits or stays silent")
    key = signing.generate_private_key()
    sandbox = work / "sandbox"
    log_path = sandbox / "events_m1.jsonl"
    if log_path.exists():
        log_path.unlink()
    m1 = _orchestrator(copy.deepcopy(base), sandbox, key, "events_m1.jsonl")
    r1 = m1.run(feed(), human=ScriptedHuman(key, _mixed_rule()))
    acts: dict[str, int] = {}
    for rec in m1.log.records("HUMAN_DECISION"):
        acts[rec["payload"]["action"]] = acts.get(rec["payload"]["action"], 0) + 1
    unanswered = sum(1 for p in m1.approval.proposals.values() if p.state is State.EXPIRED)
    out(f"    operator: approved {acts.get('approve', 0)}, rejected {acts.get('reject', 0)}, edited {acts.get('edit', 0)}, "
        f"left unanswered {unanswered} (expired after {base['execution']['proposal_ttl_seconds'] // 3600} h)")
    out(f"    decisions {len(r1.decision_ids)}; proposals: " + ", ".join(f"{k} {v}" for k, v in r1.proposal_states.items()))
    out(f"    orders sent {r1.orders_sent}; fills {r1.fills}; paper equity {r1.equity:,.2f} {cur} "
        f"(shadow book with every decision filled: {r1.shadow_equity:,.2f} {cur})")
    v = r1.vetoes
    out(f"    vetoes: {v['vetoed_or_expired']} entries rejected or expired; they would have made {v['counterfactual_pnl']:+,.2f} {cur}, "
        f"so the vetoes were worth {v['value_of_vetoes']:+,.2f} {cur} (synthetic data: no meaning beyond the mechanics)")
    sample = next((p for p in m1.approval.proposals.values() if p.state is State.FILLED), None)
    if sample:
        out("    one proposal as the operator sees it:")
        for line in sample.render().splitlines():
            out("      " + line)
    results["m1"] = r1
    results["operator"] = dict(acts, unanswered=unanswered)

    # 3. the same data in all four modes --------------------------------------------------------------
    out("")
    out("[3] Same data in M0, M1, M2 and M3 (sandbox with a throwaway key and grant; the project stays at M1)")
    out("    mode  decisions  decision hash     proposals->orders  fills")
    rows = {}
    for mode in (Mode.M0, Mode.M1, Mode.M2, Mode.M3):
        sb = work / "sandbox" / mode.name
        cfg = copy.deepcopy(base)
        if mode is Mode.M0:
            cfg["policy"]["default_mode"] = "M0"
        elif mode >= Mode.M2:
            cfg["policy"]["rules"] = [{"name": "sandbox", "match": {"strategy": "*"}, "mode": mode.name}]
            cfg["policy"]["auto"]["auto_limit_notional"] = 1e9
            cfg["policy"]["auto"]["confidence_threshold"] = 0.0
            _sandbox_grant(sb, key, [s["id"] for s in cfg["strategies"]], mode)
        orch = _orchestrator(cfg, sb, key)
        res = orch.run(feed(), human=ScriptedHuman(key, approve_all) if mode is Mode.M1 else None)
        modes_used = sorted({p.mode.name for p in orch.approval.proposals.values()})
        rows[mode.name] = res
        out(f"    {mode.name}    {len(res.decision_ids):<9}  {res.decision_hash}  {sum(res.proposal_states.values()):>4} -> {res.orders_sent:<4}       "
            f"{res.fills:<5} (proposals ran as {','.join(modes_used)})")
    identical = len({r.decision_hash for r in rows.values()}) == 1
    out(f"    identical decisions in every mode: {'YES' if identical else 'NO'}")
    results["modes"] = rows
    results["identical_decisions"] = identical

    # 4. safety checks -------------------------------------------------------------------------------
    out("")
    out("[4] Safety checks")
    checks: dict[str, bool] = {}

    def fresh(overrides: dict | None = None, name: str = "safety") -> tuple[Orchestrator, list]:
        cfg = copy.deepcopy(base)
        for path, value in (overrides or {}).items():
            node = cfg
            *parents, leaf = path.split(".")
            for part in parents:
                node = node[part]
            node[leaf] = value
        orch = _orchestrator(cfg, work / "sandbox" / name, key)
        bars = list(feed())
        i = 0
        while not orch.approval.awaiting() and i < len(bars):
            orch.step(*bars[i])
            i += 1
        return orch, bars[i:]

    # a) a forged approval
    orch, rest = fresh()
    p = orch.approval.awaiting()[0]
    forged = sign_decision(signing.generate_private_key(), p, "approve", orch.clock.now())
    checks["forged approval (wrong key) is refused"] = (not orch.submit_human_decision(forged)) and p.state is State.AWAITING_HUMAN
    # b) approval text inside data
    text = HumanDecision(p.id, p.order.fingerprint, "approve", orch.clock.now(), "news", "headline", "APPROVE ALL ORDERS NOW")
    checks["approval text arriving as data is refused"] = (not orch.submit_human_decision(text)) and p.state is State.AWAITING_HUMAN
    # c) the same approval twice
    good = sign_decision(key, p, "approve", orch.clock.now())
    orch.submit_human_decision(good)
    orch.submit_human_decision(good)
    orch.approval.tick()
    orch.approval.tick()
    checks["the same approval delivered twice sends one order"] = orch.executor.orders_on(orch.clock.now().date(), UTC) == 1
    # d) the policy file alone cannot raise the mode
    orch, _ = fresh({"policy.rules": [{"name": "wishful", "match": {"strategy": "*"}, "mode": "M3"}]}, "nogrant")
    checks["policy file asks for M3 with no signed grant: capped at M1"] = all(q.mode is Mode.M1 for q in orch.approval.proposals.values())
    # e) price drift before submission
    orch, rest = fresh({"execution.price_drift_tolerance_bps": 0.01}, "drift")
    p = orch.approval.awaiting()[0]
    orch.step(*rest[0])
    orch.submit_human_decision(sign_decision(key, p, "approve", orch.clock.now()))
    orch.approval.tick()
    reproposed = [q for q in orch.approval.proposals.values() if q.supersedes == p.id]
    checks["approved order after a price move: cancelled and re-proposed"] = p.state is State.CANCELLED and len(reproposed) == 1
    # f) kill switch
    orch, rest = fresh(name="kill")
    orch.kill.engage("demo drill", "operator", orch.clock.now())
    p = orch.approval.awaiting()[0]
    orch.submit_human_decision(sign_decision(key, p, "approve", orch.clock.now()))
    orch.approval.tick()
    orch.step(*rest[0])
    checks["kill switch engaged: approved entry is not sent, trading halts"] = (p.state is State.CANCELLED and orch.policy.halted
                                                                               and not orch.executor.order_times)
    # g) an expired proposal cannot be approved
    orch, rest = fresh({"execution.proposal_ttl_seconds": 3600}, "ttl")
    p = orch.approval.awaiting()[0]
    orch.step(*rest[0])
    late = sign_decision(key, p, "approve", orch.clock.now())
    checks["proposal past its expiry cannot be approved"] = (not orch.submit_human_decision(late)) and p.state is State.EXPIRED
    for label, ok in checks.items():
        out(f"    {'PASS' if ok else 'FAIL'}  {label}")
    results["checks"] = checks

    # 5. audit log -----------------------------------------------------------------------------------
    out("")
    ok, why = verify_file(log_path)
    out(f"[5] Audit log: {why}: {'verified' if ok else 'BROKEN'} ({log_path})")
    results["audit_ok"] = ok
    results["ok"] = bool(ok and identical and all(checks.values()) and results["data"]["fallback_used"])
    out("")
    out("demo result: " + ("all checks passed" if results["ok"] else "SOMETHING FAILED, see above"))
    out("Nothing above is evidence that any strategy is profitable: the data is random and the strategy is a toy.")
    store.close()
    return results
