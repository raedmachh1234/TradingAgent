"""The one-command demo runs end to end and every check in it passes."""
from __future__ import annotations

from quantbot.demo import run_demo


def test_demo(tmp_path):
    lines = []
    result = run_demo(tmp_path, out=lines.append)
    assert result["ok"], "\n".join(lines)
    assert result["identical_decisions"] and result["audit_ok"] and all(result["checks"].values())
    assert result["modes"]["M0"].orders_sent == 0 and result["modes"]["M3"].orders_sent > 0
    ops = result["operator"]
    assert ops["approve"] > 0 and ops["reject"] > 0 and ops["edit"] > 0 and ops["unanswered"] > 0  # all four behaviours shown
    text = "\n".join(lines)
    assert "Nothing above is evidence that any strategy is profitable" in text


def test_foundation_demo():
    from quantbot.foundation.demo import run_foundation_demo

    lines = []
    result = run_foundation_demo(out=lines.append, seeds=10)
    assert result["ok"], "\n".join(lines)
    assert len(result["fixtures"]) == 57 and len(result["baselines"]) == 18
    text = "\n".join(lines)
    assert "57 of 57 reproduce" in text and "decision: skfolio" in text
    assert "every series is synthetic" in text
