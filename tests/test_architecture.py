"""Structural rules, checked on the source: strategies cannot reach a broker, the bot never loads a private key,
and only the Telegram channel talks to the network."""
from __future__ import annotations

import ast
from pathlib import Path

from quantbot.brokers.base import BrokerAdapter
from quantbot.execution.executor import Executor
from quantbot.strategy.base import StrategyContext

SRC = Path(__file__).resolve().parents[1] / "src" / "quantbot"


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg = path.relative_to(SRC.parent).with_suffix("").parts[:-1]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(pkg[: len(pkg) - node.level + 1])
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            out.add(mod)
            out |= {f"{mod}.{a.name}" for a in node.names}
    return out


def names_used(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}


def py_files(*parts: str) -> list[Path]:
    return sorted((SRC.joinpath(*parts)).rglob("*.py"))


FORBIDDEN_FOR_STRATEGIES = ("quantbot.brokers", "quantbot.execution", "quantbot.risk", "quantbot.orchestrator",
                            "quantbot.portfolio", "quantbot.data.store", "quantbot.cli", "quantbot.demo",
                            "urllib", "socket", "http", "requests", "subprocess")


def test_strategy_code_cannot_import_brokers_the_gate_or_the_network():
    files = py_files("strategy") + py_files("strategies")
    assert len(files) >= 4
    for f in files:
        bad = {m for m in imports(f) if m.startswith(FORBIDDEN_FOR_STRATEGIES)}
        assert not bad, f"{f.name} imports {sorted(bad)}"


def test_strategies_see_only_a_read_only_context():
    public = {n for n in dir(StrategyContext) if not n.startswith("_")}
    assert public == {"now", "capital", "allow_short", "bars", "closes", "position", "instrument"}
    assert StrategyContext.__slots__  # no attribute can be added to smuggle a broker in


def test_only_the_executor_holds_a_broker_and_does_not_expose_it():
    from quantbot.brokers.paper import PaperBroker
    from quantbot.core.bus import EventBus
    from quantbot.core.clock import SimClock
    from quantbot.core.eventlog import EventLog
    from quantbot.risk.gate import RiskGate, RiskLimits
    from quantbot.risk.killswitch import KillSwitch
    from quantbot.core.config import load_config

    ex = Executor(PaperBroker({}), RiskGate(RiskLimits.from_config(load_config(read_user_file=False)["risk"]), KillSwitch()),
                  SimClock(), EventBus(EventLog(), SimClock()))
    public_values = [getattr(ex, n) for n in dir(ex) if not n.startswith("_") and not callable(getattr(ex, n))]
    assert not any(isinstance(v, BrokerAdapter) for v in public_values)


def test_the_running_bot_never_loads_a_private_key():
    allowed = {"cli.py", "demo.py", "signing.py", "scripted.py", "approval.py"}
    for f in SRC.rglob("*.py"):
        if f.name in allowed:
            continue
        used = names_used(f)
        assert not used & {"load_private_key", "generate_private_key", "Ed25519PrivateKey", "sign_payload", "sign_grants",
                            "sign_command", "sign_decision"}, f.name


def test_only_the_telegram_channel_uses_the_network():
    for f in SRC.rglob("*.py"):
        net = {m for m in imports(f) if m.split(".")[0] in ("urllib", "socket", "http", "requests", "aiohttp", "httpx")}
        if f.name == "telegram.py":
            continue
        assert not net, f"{f.name} imports {sorted(net)}"


def test_only_the_approval_layer_and_wiring_import_the_approval_service():
    users = {f.relative_to(SRC).as_posix() for f in SRC.rglob("*.py") if any("execution.approval" in m for m in imports(f))}
    assert users <= {"orchestrator.py", "cli.py", "demo.py", "execution/gate.py", "execution/scripted.py",
                     "execution/channels/base.py", "execution/channels/cli.py", "execution/channels/telegram.py"}


ALLOWED_IN_FOUNDATION = ("__future__", "collections", "dataclasses", "importlib", "inspect", "itertools", "json",
                         "math", "pathlib", "platform", "re", "statistics", "time", "typing", "warnings",
                         "numpy", "scipy", "pandas", "quantbot.foundation",
                         # optional allocator libraries, imported only inside the bake-off adapters
                         "skfolio", "pypfopt", "riskfolio", "sklearn")


def test_the_foundation_is_pure_math():
    """The book foundation cannot reach brokers, the gate, data stores or the network: it only computes."""
    files = py_files("foundation")
    assert len(files) >= 20
    for f in files:
        bad = {m for m in imports(f) if not m.startswith(ALLOWED_IN_FOUNDATION)}
        assert not bad, f"{f.name} imports {sorted(bad)}"
