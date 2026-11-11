"""Command line.

    python -m quantbot demo                     the one-command Phase 1 demonstration (the execution gate)
    python -m quantbot demo foundation          the one-command Phase 2 demonstration (the book foundation)
    python -m quantbot bakeoff                  re-run the allocator comparison and rewrite docs/phase2
    python -m quantbot paper                    interactive paper session: you approve, reject or edit each proposal
    python -m quantbot config                   print the effective configuration
    python -m quantbot log verify FILE          verify an audit log's hash chain
    python -m quantbot history check FILE       check your trade-history CSV against the import format
    python -m quantbot keys init                create the operator key pair (private key outside the repository)
    python -m quantbot autonomy sign|verify     sign or check config/autonomy.yaml (the only route above M1)

Private-key handling lives only in this module and in execution/signing.py. The running bot never loads one.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime
from pathlib import Path

import yaml

from .core.config import load_config, load_env_file
from .core.eventlog import verify_file
from .core.types import UTC
from .execution import signing

DEFAULT_PRIVATE_KEY = Path.home() / ".quantbot" / "operator_ed25519.key"


def _cmd_demo(args: argparse.Namespace) -> int:
    if args.which == "foundation":
        from .foundation.demo import run_foundation_demo

        result = run_foundation_demo()
    else:
        from .demo import run_demo

        result = run_demo(Path(args.workdir))
    return 0 if result["ok"] else 1


def _cmd_bakeoff(args: argparse.Namespace) -> int:
    from .foundation import allocators

    missing = [lib for lib, v in allocators.available().items() if v is None]
    if missing:
        print(f"not installed: {', '.join(missing)}. Install them with: pip install -e \".[allocators,bakeoff]\"")
    print("running the allocator bake-off (about half a minute)...")
    result = allocators.run(seed=args.seed)
    json_path, md_path = allocators.write_report(result, args.out)
    decision = allocators.decide(result)
    print(f"decision: {decision['choice']} ({decision['reason']})")
    print(f"wrote {json_path} and {md_path}")
    return 0 if decision["choice"] else 1


def _cmd_config(args: argparse.Namespace) -> int:
    print(yaml.safe_dump(load_config(args.file), sort_keys=False))
    return 0


def _cmd_log(args: argparse.Namespace) -> int:
    ok, why = verify_file(args.file)
    print(("OK: " if ok else "BROKEN: ") + why)
    return 0 if ok else 1


def _cmd_history(args: argparse.Namespace) -> int:
    from .data.trade_history import load_trade_history

    rep = load_trade_history(args.file)
    print(rep.summary())
    return 0 if rep.ok else 1


def _cmd_keys(args: argparse.Namespace) -> int:
    private, public = Path(args.private), Path(args.public)
    if private.exists():
        print(f"refusing to overwrite an existing private key: {private}")
        return 1
    try:
        inside = private.resolve().is_relative_to(Path.cwd().resolve()) and private.suffix != ".key"
    except ValueError:
        inside = False
    if inside:
        print("refusing to write a private key inside the project without a .key suffix (it would not be ignored by git)")
        return 1
    passphrase = None if args.no_passphrase else (getpass.getpass("passphrase for the private key (empty for none): ") or None)
    key = signing.generate_private_key()
    signing.save_private_key(key, private, passphrase)
    signing.save_public_key(key.public_key(), public)
    print(f"private key: {private}  (keep it off this machine's repository; it is what authorises autonomy)")
    print(f"public key:  {public}  fingerprint {signing.fingerprint(key.public_key())}")
    print("optional: set QUANTBOT_OPERATOR_KEY_SHA256 to that fingerprint so a swapped public key is rejected")
    return 0


def _load_key(path: str):
    try:
        return signing.load_private_key(path)
    except TypeError:
        return signing.load_private_key(path, getpass.getpass("passphrase: "))


def _cmd_autonomy(args: argparse.Namespace) -> int:
    cfg = load_config()
    grants_path = Path(args.grants or cfg["autonomy"]["grants_file"])
    doc = yaml.safe_load(grants_path.read_text(encoding="utf-8")) or {}
    if args.action == "verify":
        if not doc.get("grants"):
            print(f"{grants_path}: no grants, so every strategy is capped at M1")
            return 0
        pub = signing.load_public_key(args.public or cfg["autonomy"]["operator_public_key"])
        ok = bool(doc.get("grants")) and signing.verify_grants(doc, pub)
        print(f"{grants_path}: " + ("signature valid" if ok else "NOT valid (no grants, or the signature does not verify)"))
        for g in doc.get("grants", []) if ok else []:
            print(f"  {g['strategy']}: up to {g['max_mode']} signed {g['signed_at']}")
        return 0 if ok else 1
    for g in doc.get("grants", []):
        g.setdefault("signed_at", datetime.now(UTC).isoformat(timespec="seconds"))
    signed = signing.sign_grants(doc, _load_key(args.key))
    grants_path.write_text("# Signed autonomy grants. Any edit after signing invalidates the signature.\n"
                           + yaml.safe_dump(signed, sort_keys=False), encoding="utf-8")
    print(f"signed {len(signed['grants'])} grant(s) in {grants_path}; each takes effect after its cooling-off period")
    return 0


def _cmd_paper(args: argparse.Namespace) -> int:
    """Interactive M1 session on synthetic data: every proposal waits for you at the prompt."""
    from .core.clock import SimClock
    from .data.providers import build_providers
    from .data.service import DataService, replay_feed
    from .data.store import DataStore
    from .execution.approval import OperatorKeyAuthenticator, sign_decision
    from .execution.channels.cli import CliChannel
    from .execution.proposal import State
    from .orchestrator import Orchestrator

    cfg = load_config()
    root = Path(cfg["data"]["root"])
    store = DataStore(root / "cache")
    symbols = sorted({s for spec in cfg["strategies"] for s in spec["symbols"]})
    start, end = datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 12, 31, tzinfo=UTC)
    svc = DataService(store, build_providers(cfg), SimClock(datetime.now(UTC)), cfg["markets"]["bar_frequency"], cfg["data"]["quality"])
    for s in symbols:
        svc.ensure_bars(cfg["data"]["dataset"], s, start, end)
    session_key = signing.generate_private_key()  # paper session only: stands in for the operator key at this terminal
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    orch = Orchestrator(cfg, event_log=root / "sessions" / f"paper-{stamp}.jsonl", kill_file=cfg["execution"]["kill_file"])
    orch.add_channel(CliChannel(), OperatorKeyAuthenticator(session_key.public_key()))
    print("paper session on synthetic data. For each proposal: [a]pprove  [r]eject  [e]dit size  [s]kip  [q]uit")

    def human(o):
        out = []
        for p in o.approval.awaiting():
            if p.state is not State.AWAITING_HUMAN or p.id in seen:
                continue
            seen.add(p.id)
            print("\n" + p.render())
            answer = input("decision [a/r/e/s/q]: ").strip().lower()[:1]
            if answer == "q":
                raise KeyboardInterrupt
            if answer == "a":
                out.append(sign_decision(session_key, p, "approve", o.clock.now()))
            elif answer == "r":
                out.append(sign_decision(session_key, p, "reject", o.clock.now(), reason=input("reason: ").strip()))
            elif answer == "e":
                try:
                    qty = float(input(f"new size (at most {p.order.quantity:g}): "))
                except ValueError:
                    print("not a number; skipped")
                    continue
                out.append(sign_decision(session_key, p, "edit", o.clock.now(), edits={"quantity": qty}))
        return out

    seen: set[str] = set()
    try:
        res = orch.run(replay_feed(store, cfg["data"]["dataset"], symbols, start, end), human=human, max_steps=args.bars)
    except (KeyboardInterrupt, EOFError):
        res = orch.result()
        print("\nstopped.")
    print(f"\nproposals: {res.proposal_states}; orders {res.orders_sent}; fills {res.fills}; refused decisions {res.refused_decisions}")
    print(f"paper equity {res.equity:,.2f} {cfg['account']['currency']}; audit log {orch.log.path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    ap = argparse.ArgumentParser(prog="quantbot", description="Orchestrator for trading sub-bots with one execution gate.")
    sub = ap.add_subparsers(dest="command", required=True)
    d = sub.add_parser("demo", help="run a demonstration: the execution gate (default) or the book foundation")
    d.add_argument("which", nargs="?", choices=["gate", "foundation"], default="gate")
    d.add_argument("--workdir", default="data/demo")
    d.set_defaults(fn=_cmd_demo)
    b = sub.add_parser("bakeoff", help="compare skfolio, PyPortfolioOpt and Riskfolio-Lib and write the report")
    b.add_argument("--out", default="docs/phase2")
    b.add_argument("--seed", type=int, default=0)
    b.set_defaults(fn=_cmd_bakeoff)
    p = sub.add_parser("paper", help="interactive paper session with approvals at the prompt")
    p.add_argument("--bars", type=int, default=None, help="stop after this many bars")
    p.set_defaults(fn=_cmd_paper)
    c = sub.add_parser("config", help="print the effective configuration")
    c.add_argument("--file", default=None)
    c.set_defaults(fn=_cmd_config)
    lg = sub.add_parser("log", help="audit log tools")
    lg.add_argument("action", choices=["verify"])
    lg.add_argument("file")
    lg.set_defaults(fn=_cmd_log)
    h = sub.add_parser("history", help="check a trade-history file against the import format")
    h.add_argument("action", choices=["check"])
    h.add_argument("file")
    h.set_defaults(fn=_cmd_history)
    k = sub.add_parser("keys", help="operator key pair")
    k.add_argument("action", choices=["init"])
    k.add_argument("--private", default=str(DEFAULT_PRIVATE_KEY))
    k.add_argument("--public", default="config/operator.pub")
    k.add_argument("--no-passphrase", action="store_true")
    k.set_defaults(fn=_cmd_keys)
    a = sub.add_parser("autonomy", help="sign or verify autonomy grants")
    a.add_argument("action", choices=["sign", "verify"])
    a.add_argument("--grants", default=None)
    a.add_argument("--key", default=str(DEFAULT_PRIVATE_KEY))
    a.add_argument("--public", default=None)
    a.set_defaults(fn=_cmd_autonomy)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
