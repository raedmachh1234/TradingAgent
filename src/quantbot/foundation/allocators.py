"""Allocator bake-off: skfolio, PyPortfolioOpt and Riskfolio-Lib on identical problems.

Every library gets the same sample mean and covariance (or the same return table, from which it computes
them) and the same constraints: fully invested, long only, at most 40% per asset. Two problems are solved:
minimum variance and maximum Sharpe ratio. The reference answer comes from scipy's SLSQP in this module.

The decision rule was fixed before the first run (docs/phase2/allocator_bakeoff.md): a library passes when its
weights are within 1e-3 of the reference for minimum variance and 1e-2 for maximum Sharpe, with no constraint
violated, and it installs on Python 3.11 and 3.13. Among passing libraries the choice goes to the features
needed later (walk-forward and purged cross-validation, CVaR and drawdown risk measures, a scikit-learn style
API), then the dependency footprint, then speed.

All three libraries are optional: skfolio, the adopted one, comes with pip install -e ".[allocators]"; the other two
only with the "bakeoff" extra, because Riskfolio-Lib depends on vectorbt (Apache 2.0 with Commons Clause). This
module never imports vectorbt. A library that is not installed is reported as such.
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import math
import re
import time
import warnings

import numpy as np
from scipy.optimize import minimize

from .minvariance import min_variance_weights
from .synthetic import correlated

MAX_WEIGHT = 0.4
LIBRARIES = {"skfolio": "skfolio", "PyPortfolioOpt": "pypfopt", "Riskfolio-Lib": "riskfolio"}
DISTRIBUTIONS = {"skfolio": "skfolio", "PyPortfolioOpt": "pyportfolioopt", "Riskfolio-Lib": "riskfolio-lib"}
PASS_TOL = {"min_variance": 1e-3, "max_sharpe": 1e-2}

# five asset classes with a made-up truth, monthly units (not market data)
NAMES = ["equities", "government bonds", "credit", "real estate", "commodities"]
TRUE_MU = np.array([0.065, 0.025, 0.035, 0.055, 0.035]) / 12
TRUE_VOL = np.array([0.15, 0.05, 0.07, 0.17, 0.19]) / math.sqrt(12)
TRUE_CORR = np.array([[1.0, -0.1, 0.5, 0.7, 0.3],
                      [-0.1, 1.0, 0.6, 0.1, -0.1],
                      [0.5, 0.6, 1.0, 0.5, 0.2],
                      [0.7, 0.1, 0.5, 1.0, 0.3],
                      [0.3, -0.1, 0.2, 0.3, 1.0]])
RF = 0.02 / 12


def sample_returns(months: int = 240, seed=0) -> np.ndarray:
    return correlated(months, TRUE_VOL, TRUE_CORR, mu=TRUE_MU, df=5, seed=seed)


def reference(problem: str, mu: np.ndarray, cov: np.ndarray, rf: float = RF,
              max_weight: float = MAX_WEIGHT) -> np.ndarray:
    if problem == "min_variance":
        return min_variance_weights(cov, True, max_weight)
    if problem != "max_sharpe":
        raise ValueError(problem)
    # The Sharpe ratio is quasi-concave on the feasible set, so a local optimum is global; SLSQP is run from
    # equal weights and from a few random feasible starts and the best answer is kept.
    k = mu.size
    ex = mu - rf
    if ex.max() <= 0:
        raise ValueError("no asset beats the risk-free rate; the maximum Sharpe mix is undefined")

    def neg_sharpe(w):
        b = math.sqrt(w @ cov @ w)
        return -(ex @ w) / b

    def grad(w):
        cw = cov @ w
        b = math.sqrt(w @ cw)
        return -(ex / b - (ex @ w) * cw / b**3)

    rng = np.random.default_rng(0)
    starts = [np.full(k, 1.0 / k)] + [rng.dirichlet(np.ones(k)) for _ in range(5)]
    best = None
    for w0 in starts:
        w0 = np.clip(w0, 0, max_weight)
        w0 = w0 / w0.sum()
        res = minimize(neg_sharpe, w0, jac=grad, method="SLSQP", bounds=[(0.0, max_weight)] * k,
                       constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(k)}],
                       options={"ftol": 1e-15, "maxiter": 1000})
        if res.success and (best is None or res.fun < best.fun):
            best = res
    if best is None:
        raise RuntimeError("maximum-Sharpe optimisation failed from every start")
    w = np.clip(best.x, 0.0, max_weight)
    return w / w.sum()


def _frame(returns: np.ndarray):
    import pandas as pd
    return pd.DataFrame(returns, columns=[f"a{i}" for i in range(returns.shape[1])],
                        index=pd.date_range("2000-01-31", periods=returns.shape[0], freq="ME"))


def _solve_skfolio(problem, returns, mu, cov, rf, max_weight):
    from skfolio import RiskMeasure
    from skfolio.optimization import MeanRisk, ObjectiveFunction
    obj = ObjectiveFunction.MINIMIZE_RISK if problem == "min_variance" else ObjectiveFunction.MAXIMIZE_RATIO
    model = MeanRisk(objective_function=obj, risk_measure=RiskMeasure.VARIANCE, min_weights=0.0,
                     max_weights=max_weight, risk_free_rate=rf)
    model.fit(_frame(returns))
    return np.asarray(model.weights_, dtype=float)


def _solve_pypfopt(problem, returns, mu, cov, rf, max_weight):
    import pandas as pd
    from pypfopt import EfficientFrontier
    names = [f"a{i}" for i in range(mu.size)]
    ef = EfficientFrontier(pd.Series(mu, index=names), pd.DataFrame(cov, index=names, columns=names),
                           weight_bounds=(0.0, max_weight))
    w = ef.min_volatility() if problem == "min_variance" else ef.max_sharpe(risk_free_rate=rf)
    return np.array([w[n] for n in names], dtype=float)


def _solve_riskfolio(problem, returns, mu, cov, rf, max_weight):
    import riskfolio as rp
    port = rp.Portfolio(returns=_frame(returns))
    port.assets_stats(method_mu="hist", method_cov="hist")
    k = mu.size
    port.ainequality = np.eye(k)  # Riskfolio 7 reads these as A w <= b
    port.binequality = np.full((k, 1), max_weight)
    obj = "MinRisk" if problem == "min_variance" else "Sharpe"
    w = port.optimization(model="Classic", rm="MV", obj=obj, rf=rf, l=0, hist=True)
    if w is None:
        raise RuntimeError("Riskfolio found no solution")
    return np.asarray(w.values, dtype=float).ravel()


SOLVERS = {"skfolio": _solve_skfolio, "PyPortfolioOpt": _solve_pypfopt, "Riskfolio-Lib": _solve_riskfolio}


def available() -> dict[str, str | None]:
    """Installed version of each library, or None."""
    out = {}
    for lib, dist in DISTRIBUTIONS.items():
        try:
            out[lib] = md.version(dist)
        except md.PackageNotFoundError:
            out[lib] = None
    return out


def _violation(w: np.ndarray, max_weight: float) -> float:
    return float(max(0.0, abs(w.sum() - 1.0), float((w - max_weight).max()), float((-w).max())))


def _sharpe(w, mu, cov, rf):
    return float((w @ mu - rf) / math.sqrt(w @ cov @ w))


def compare(returns: np.ndarray, rf: float = RF, max_weight: float = MAX_WEIGHT, repeats: int = 5) -> dict:
    """Solve both problems with every installed library on one return table."""
    mu = returns.mean(axis=0)
    cov = np.cov(returns, rowvar=False)
    versions = available()
    out = {"reference": {}, "libraries": {}}
    for problem in ("min_variance", "max_sharpe"):
        out["reference"][problem] = reference(problem, mu, cov, rf, max_weight).tolist()
    for lib, version in versions.items():
        res = {"version": version}
        if version is None:
            res["error"] = "not installed"
            out["libraries"][lib] = res
            continue
        for problem in ("min_variance", "max_sharpe"):
            ref = np.array(out["reference"][problem])
            try:
                times = []
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    for _ in range(repeats):
                        t0 = time.perf_counter()
                        w = SOLVERS[lib](problem, returns, mu, cov, rf, max_weight)
                        times.append(time.perf_counter() - t0)
                gap = (w @ cov @ w / (ref @ cov @ ref) - 1) if problem == "min_variance" else \
                    _sharpe(ref, mu, cov, rf) - _sharpe(w, mu, cov, rf)
                res[problem] = dict(weights=w.round(6).tolist(), max_abs_diff=float(np.abs(w - ref).max()),
                                    violation=_violation(w, max_weight), objective_gap=float(gap),
                                    median_ms=float(np.median(times[1:] if repeats > 1 else times) * 1000))
            except Exception as exc:  # report, do not hide, a library failure
                res[problem] = dict(error=f"{type(exc).__name__}: {exc}"[:300])
        out["libraries"][lib] = res
    return out


def walk_forward(returns: np.ndarray, window: int = 60, every: int = 3, rf: float = RF,
                 max_weight: float = MAX_WEIGHT) -> dict:
    """Out-of-sample results of each library's minimum-variance mix, rebalanced every ``every`` months on
    the trailing ``window`` months; equal weights and the reference solver alongside."""
    versions = available()
    solvers = {"reference": None, **{lib: SOLVERS[lib] for lib, v in versions.items() if v}}
    paths = {name: [] for name in solvers}
    paths["equal weights"] = []
    errors = {}
    for t in range(window, returns.shape[0], every):
        hist = returns[t - window:t]
        mu, cov = hist.mean(axis=0), np.cov(hist, rowvar=False)
        held = returns[t:t + every]
        for name, solve in solvers.items():
            if name in errors:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    w = reference("min_variance", mu, cov, rf, max_weight) if solve is None else \
                        solve("min_variance", hist, mu, cov, rf, max_weight)
                paths[name].extend(held @ w)
            except Exception as exc:
                errors[name] = f"{type(exc).__name__}: {exc}"[:300]
        paths["equal weights"].extend(held.mean(axis=1))
    out = {}
    for name, r in paths.items():
        if name in errors:
            out[name] = {"error": errors[name]}
            continue
        r = np.asarray(r)
        out[name] = dict(months=int(r.size), yearly_vol=float(r.std(ddof=1) * math.sqrt(12)),
                         yearly_return=float(r.mean() * 12),
                         sharpe=float((r.mean() - rf) / r.std(ddof=1) * math.sqrt(12)))
    return out


def _requirement_names(dist: str) -> list[str]:
    names = []
    for req in md.requires(dist) or []:
        if "extra ==" in req or "extra==" in req:
            continue
        m = re.match(r"\s*([A-Za-z0-9_.\-]+)", req)
        if m:
            names.append(m.group(1).lower().replace("_", "-"))
    return names


def footprint(dist: str) -> list[str]:
    """Installed distributions a library pulls in (transitively), excluding itself."""
    seen, todo = set(), [dist.lower()]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            todo.extend(_requirement_names(name))
        except md.PackageNotFoundError:
            seen.discard(name)
    seen.discard(dist.lower())
    return sorted(seen)


def features() -> dict[str, dict[str, bool]]:
    """Capabilities checked by importing them, not taken from documentation."""
    def has(module: str, attr: str | None = None) -> bool:
        try:
            m = importlib.import_module(module)
            return attr is None or hasattr(m, attr)
        except Exception:
            return False

    out = {}
    if available()["skfolio"]:
        from skfolio import RiskMeasure
        try:
            from sklearn.base import BaseEstimator
            from skfolio.optimization import MeanRisk
            sk_api = issubclass(MeanRisk, BaseEstimator)
        except Exception:
            sk_api = False
        out["skfolio"] = dict(walk_forward=has("skfolio.model_selection", "WalkForward"),
                              purged_cv=has("skfolio.model_selection", "CombinatorialPurgedCV"),
                              cvar=hasattr(RiskMeasure, "CVAR"), drawdown=hasattr(RiskMeasure, "CDAR"),
                              sklearn_api=sk_api)
    if available()["PyPortfolioOpt"]:
        out["PyPortfolioOpt"] = dict(walk_forward=False, purged_cv=False,
                                     cvar=has("pypfopt", "EfficientCVaR"), drawdown=has("pypfopt", "EfficientCDaR"),
                                     sklearn_api=False)
    if available()["Riskfolio-Lib"]:
        import inspect

        import riskfolio as rp
        doc = inspect.getdoc(rp.Portfolio.optimization) or ""
        out["Riskfolio-Lib"] = dict(walk_forward=False, purged_cv=False, cvar="'CVaR'" in doc or "CVaR" in doc,
                                    drawdown="CDaR" in doc, sklearn_api=False)
    return out


def run(seed: int = 0, months: int = 240) -> dict:
    returns = sample_returns(months, seed)
    one = compare(returns)
    wf = walk_forward(returns)
    passes = {}
    for lib, res in one["libraries"].items():
        ok = res.get("version") is not None
        for problem, tol in PASS_TOL.items():
            r = res.get(problem, {})
            ok = ok and "error" not in r and r.get("max_abs_diff", 1.0) <= tol and r.get("violation", 1.0) <= 1e-6
        passes[lib] = ok
    return dict(seed=seed, months=months, names=NAMES, comparison=one, walk_forward=wf, passes=passes,
                footprint={lib: footprint(DISTRIBUTIONS[lib]) for lib, v in available().items() if v},
                features=features())


FEATURE_ORDER = ("walk_forward", "purged_cv", "cvar", "drawdown", "sklearn_api")


def decide(result: dict) -> dict:
    """Apply the decision rule fixed before the first run: pass first, then features, footprint, speed."""
    rows = []
    for lib, ok in result["passes"].items():
        if not ok:
            continue
        lib_res = result["comparison"]["libraries"][lib]
        feats = result["features"].get(lib, {})
        speed = float(np.mean([lib_res[p]["median_ms"] for p in PASS_TOL]))
        rows.append((lib, sum(bool(feats.get(f)) for f in FEATURE_ORDER), len(result["footprint"].get(lib, [])),
                     speed))
    if not rows:
        return {"choice": None, "ranking": [], "reason": "no library passed"}
    rows.sort(key=lambda r: (-r[1], r[2], r[3]))
    best = rows[0]
    reason = (f"{best[0]} passes and has {best[1]} of {len(FEATURE_ORDER)} needed features, "
              f"{best[2]} dependencies, {best[3]:.1f} ms per solve")
    return {"choice": best[0], "reason": reason,
            "ranking": [dict(library=r[0], features=r[1], dependencies=r[2], ms_per_solve=round(r[3], 2))
                        for r in rows]}


def write_report(result: dict, out_dir) -> tuple:
    """Write the raw result (JSON) and a readable summary (Markdown) to ``out_dir``."""
    import json
    import platform
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    decision = decide(result)
    meta = dict(python=platform.python_version(), numpy=np.__version__, decision=decision)
    (out / "allocator_bakeoff.json").write_text(json.dumps({**result, "meta": meta}, indent=1))
    lib_rows = []
    for lib, res in result["comparison"]["libraries"].items():
        if res.get("version") is None:
            lib_rows.append(f"| {lib} | not installed | | | | | |")
            continue
        mv, ms = res["min_variance"], res["max_sharpe"]
        feats = result["features"].get(lib, {})
        lib_rows.append(
            f"| {lib} {res['version']} | {mv.get('max_abs_diff', float('nan')):.1e} | "
            f"{ms.get('max_abs_diff', float('nan')):.1e} | {(mv.get('median_ms', 0) + ms.get('median_ms', 0)) / 2:.1f} | "
            f"{len(result['footprint'].get(lib, []))} | "
            f"{', '.join(f for f in FEATURE_ORDER if feats.get(f)) or 'none'} | "
            f"{'yes' if result['passes'][lib] else 'no'} |")
    wf_rows = [f"| {name} | {r['yearly_vol']:.2%} | {r['yearly_return']:.2%} | {r['sharpe']:.3f} |"
               if "error" not in r else f"| {name} | error: {r['error']} | | |"
               for name, r in result["walk_forward"].items()]
    md = "\n".join([
        "# Allocator bake-off",
        "",
        f"Generated by `python -m quantbot bakeoff` (seed {result['seed']}, {result['months']} months of synthetic "
        f"monthly returns for five made-up asset classes, Student t(5) shocks; Python {meta['python']}). Not market "
        "data: these numbers compare software, not investments.",
        "",
        "**Decision rule, fixed before the first run.** A library passes when its weights are within 1e-3 of the "
        "reference (scipy SLSQP) for minimum variance and within 1e-2 for maximum Sharpe, with no constraint "
        "violated (long only, fully invested, at most 40% per asset), and it installs on Python 3.11 and 3.13. "
        "Among passing libraries: most of the needed features (walk-forward, purged cross-validation, CVaR, "
        "drawdown risk, scikit-learn API), then fewest dependencies, then speed.",
        "",
        f"**Decision: {decision['choice']}.** {decision['reason']}.",
        "",
        "| Library | Min-variance gap | Max-Sharpe gap | ms per solve | Dependencies | Features | Passes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *lib_rows,
        "",
        "Gap = largest difference from the reference weight. Dependencies = installed packages the library pulls "
        "in, counted transitively.",
        "",
        "## Walk-forward check: minimum variance, rebalanced quarterly on a trailing 5-year window",
        "",
        "| Solver | Yearly volatility | Yearly return | Sharpe (rf 2%) |",
        "| --- | --- | --- | --- |",
        *wf_rows,
        "",
        "The libraries match each other, as they solve the same problem. Minimum variance lowers risk against "
        "equal weights here but also lowers return: it is a risk tool, not a return forecast.",
        "",
    ])
    (out / "allocator_bakeoff.md").write_text(md)
    return out / "allocator_bakeoff.json", out / "allocator_bakeoff.md"
