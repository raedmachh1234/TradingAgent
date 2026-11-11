"""python -m quantbot demo foundation: the book foundation in one offline run.

[1] the book's 57 worked answers, re-computed through the chapter modules
[2] every assumption check on synthetic markets that keep or break it, with how often each check fires
[3] every chapter method against the naive baseline it replaces
[4] the allocator bake-off, read from docs/phase2/allocator_bakeoff.json (python -m quantbot bakeoff re-runs it)
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

import numpy as np

from . import (CHAPTERS, capm, correlation, diversification, drag, expectation, fixtures, kelly, minvariance,
               montecarlo, normal, randomwalk, scaling, sharpe, synthetic, tails, var, volatility)

DEFAULT_BAKEOFF = Path(__file__).resolve().parents[3] / "docs" / "phase2" / "allocator_bakeoff.json"
DAYS = 2520  # ten years of daily returns
SINGLE = (randomwalk, scaling, normal, volatility, sharpe, drag, montecarlo, tails)
MARKETS = {
    "normal": lambda s: synthetic.iid_normal(DAYS, seed=s),
    "momentum": lambda s: synthetic.ar1(DAYS, 0.15, seed=s),
    "GARCH": lambda s: synthetic.garch_t(DAYS, seed=s)[0],
}
# which assumptions each market breaks; anything not listed should stay quiet
BROKEN = {
    "normal": set(),
    "momentum": {"uncorrelated returns"},
    "GARCH": {"independent step sizes", "normal returns", "constant volatility", "normal tails",
              "VaR has the right exception rate"},
}
UNJUDGED = {("GARCH", "exceptions are independent")}  # a weak test at this sample size: shown, not judged
FIRES, QUIET = 0.8, 0.15


def _single_flags(x: np.ndarray) -> list:
    flags = [f for m in SINGLE for f in m.check(x)]
    return flags + var.check(x, var.rolling_normal_var(x))


def assumption_rates(seeds: int = 20) -> tuple[list[dict], bool]:
    counts: dict[tuple, Counter] = {}
    for market, gen in MARKETS.items():
        for s in range(seeds):
            for f in _single_flags(gen(50_000 + s)):
                key = (f.chapter, f.assumption, f.test)
                counts.setdefault(key, Counter())[market] += int(f.failed)
    rows, ok = [], True
    for key in sorted(counts):
        row = dict(chapter=key[0], assumption=key[1], test=key[2])
        for market in MARKETS:
            rate = counts[key][market] / seeds
            if (market, key[1]) in UNJUDGED:
                verdict = "shown"
            elif key[1] in BROKEN[market]:
                verdict = "as expected" if rate >= FIRES else "MISSED"
            else:
                verdict = "as expected" if rate <= QUIET else "FALSE ALARM"
            ok = ok and verdict in ("as expected", "shown")
            row[market] = (counts[key][market], verdict)
        rows.append(row)
    return rows, ok


def paired_examples() -> list[tuple[str, str, bool, bool]]:
    """(chapter and assumption, situation, flag fired, should fire) for the checks that need more than one series."""
    rng = np.random.default_rng(7)
    out = []
    small, large = 0.05 + 0.5 * rng.standard_normal(60), 0.05 + 0.5 * rng.standard_normal(3000)
    out.append(("ch 3 edge is known", "60 trades, small edge", expectation.check(small)[0].failed, True))
    out.append(("ch 3 edge is known", "3,000 trades, same edge", expectation.check(large)[0].failed, False))
    m = 0.01 * rng.standard_normal(DAYS)
    stable = 1.2 * m + 0.008 * rng.standard_normal(DAYS)
    broken = np.concatenate([0.6 * m[:DAYS // 2], 1.6 * m[DAYS // 2:]]) + 0.008 * rng.standard_normal(DAYS)
    out.append(("ch10 correlation captures the dependence", "linear relation",
                correlation.check(stable, m)[-1].failed, False))
    g, _ = synthetic.garch_t(DAYS, seed=8)
    hidden = np.sign(rng.standard_normal(DAYS)) * np.abs(g) * np.abs(rng.standard_normal(DAYS))
    out.append(("ch10 correlation captures the dependence", "uncorrelated moves, shared volatility",
                correlation.check(g, hidden)[-1].failed, True))
    out.append(("ch11 stable correlation in sell-offs", "correlation jumps in crashes",
                diversification.check(synthetic.regime_correlated(DAYS, 5, seed=9))[0].failed, True))
    out.append(("ch11 stable correlation in sell-offs", "one constant correlation",
                diversification.check(synthetic.correlated(DAYS, [0.01] * 5, synthetic.equicorrelation(5, 0.4),
                                                           seed=10))[0].failed, False))
    vols = np.full(10, 0.15 / np.sqrt(12))
    corr10 = synthetic.equicorrelation(10, 0.5)
    out.append(("ch12 covariance known well enough", "10 assets, 3 years of months",
                minvariance.check(synthetic.correlated(36, vols, corr10, seed=11))[0].failed, True))
    out.append(("ch12 covariance known well enough", "10 assets, 50 years of months",
                minvariance.check(synthetic.correlated(600, vols, corr10, seed=12))[0].failed, False))
    out.append(("ch13 stable beta", "beta 1.2 throughout", capm.check(stable, m)[0].failed, False))
    out.append(("ch13 stable beta", "beta jumps from 0.6 to 1.6", capm.check(broken, m)[0].failed, True))
    out.append(("ch14 edge is known", "60 bets at a 55% win rate",
                kelly.check(rng.random(60) < 0.55, 1.0)[0].failed, True))
    out.append(("ch14 edge is known", "3,000 bets at a 55% win rate",
                kelly.check(rng.random(3000) < 0.55, 1.0)[0].failed, False))
    return out


def run_foundation_demo(out=print, bakeoff_file: Path | None = None, seeds: int = 20) -> dict:
    t0 = time.perf_counter()
    out("quantbot foundation demo: the e-book's 17 chapters as tested modules; synthetic data only, no network")
    out("")
    rows = fixtures.reproduce()
    fixtures_ok = all(r["reproduces"] and r["matches_phase0"] for r in rows)
    out(f"[1] The book's worked answers: {sum(r['reproduces'] for r in rows)} of {len(rows)} reproduce through "
        f"the library, across {len({r['chapter'] for r in rows})} chapters")
    for r in rows:
        if not r["reproduces"]:
            out(f"    MISMATCH {r['id']} {r['quantity']}: library {r['library']:.6g}, book {r['printed']}")
    for qid in ("8.3", "11.2a", "14.2b", "17.1", "17.2"):
        r = next(x for x in rows if x["id"] == qid)
        out(f"    {qid:<6} {r['quantity']:<40} library {r['library']:>12.6g}   book {r['printed']}")
    out("")

    out(f"[2] Assumption checks on {seeds} synthetic markets of each kind, {DAYS} days each")
    out("    normal: independent normal returns, every assumption holds")
    out("    momentum: today's return carries 15% of yesterday's (AR1), so returns are correlated")
    out("    GARCH: volatility clusters and tails are fat, but returns stay uncorrelated")
    rate_rows, rates_ok = assumption_rates(seeds)
    out(f"    {'check':<62} {'normal':>10} {'momentum':>10} {'GARCH':>10}")
    for r in rate_rows:
        label = f"ch{r['chapter']:>2} {r['assumption']} ({r['test']})"
        cells = []
        for market in MARKETS:
            n, verdict = r[market]
            mark = "" if verdict in ("as expected", "shown") else " !"
            cells.append(f"{n:>3}/{seeds}{mark:<2}")
        out(f"    {label[:62]:<62} {cells[0]:>10} {cells[1]:>10} {cells[2]:>10}")
    out(f"    expected: a check fires in at least {FIRES:.0%} of the markets that break its assumption and at most "
        f"{QUIET:.0%} of the others; ! marks a miss. Christoffersen on GARCH is shown, not judged.")
    pairs = paired_examples()
    pairs_ok = all(fired == expected for _, _, fired, expected in pairs)
    out("    checks that need more than one series:")
    for name, situation, fired, expected in pairs:
        state = "FIRES" if fired else "quiet"
        mark = "" if fired == expected else "  ! unexpected"
        out(f"    {name:<44} {situation:<40} {state}{mark}")
    out("")

    out("[3] Each chapter's method against the naive baseline it replaces (synthetic data with a known truth)")
    results = [b for mod in CHAPTERS.values() for b in mod.beat_baseline(seed=0)]
    baselines_ok = all(b.beats for b in results)
    for b in results:
        arrow = "lower" if b.lower_is_better else "higher"
        wins = "" if b.wins is None else f", at least as good in {b.wins:.0%} of cases"
        out(f"    ch{b.chapter:>2} {b.method} vs {b.baseline}: {b.method_score:.4g} vs {b.baseline_score:.4g} "
            f"({b.metric}, {arrow} is better{wins}) {'BEATS' if b.beats else 'LOSES'}")
        if b.note:
            out(f"         {b.note}")
    out("")

    path = Path(bakeoff_file or DEFAULT_BAKEOFF)
    bakeoff_ok = False
    out("[4] Allocator bake-off: skfolio, PyPortfolioOpt and Riskfolio-Lib on identical problems")
    if path.exists():
        data = json.loads(path.read_text())
        decision = data["meta"]["decision"]
        bakeoff_ok = decision["choice"] is not None
        out(f"    from {path.name} (seed {data['seed']}, {data['months']} synthetic months, Python "
            f"{data['meta']['python']}); re-run with: python -m quantbot bakeoff")
        for lib, res in data["comparison"]["libraries"].items():
            if res.get("version") is None:
                out(f"    {lib:<15} not installed")
                continue
            mv, ms = res["min_variance"], res["max_sharpe"]
            out(f"    {lib:<15} {res['version']:<8} gap to reference: min-variance {mv['max_abs_diff']:.1e}, "
                f"max-Sharpe {ms['max_abs_diff']:.1e}; {len(data['footprint'].get(lib, []))} dependencies; "
                f"passes: {'yes' if data['passes'][lib] else 'no'}")
        out(f"    decision: {decision['choice']} ({decision['reason']})")
    else:
        out(f"    no result yet at {path}; run: python -m quantbot bakeoff")
    out("")
    ok = fixtures_ok and rates_ok and pairs_ok and baselines_ok and bakeoff_ok
    out(f"foundation demo result: {'all checks passed' if ok else 'SOME CHECKS FAILED'} "
        f"({time.perf_counter() - t0:.1f} s)")
    out("Nothing above is evidence about any real market or strategy: every series is synthetic.")
    return dict(ok=ok, fixtures_ok=fixtures_ok, rates_ok=rates_ok, pairs_ok=pairs_ok, baselines_ok=baselines_ok,
                bakeoff_ok=bakeoff_ok, fixtures=rows, baselines=results, rates=rate_rows, pairs=pairs)
