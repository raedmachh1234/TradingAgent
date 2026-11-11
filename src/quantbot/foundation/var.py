"""Chapter 17, value at risk and expected shortfall.

Assumptions: the parametric formulas VaR = z * sigma * V and ES = pdf(z) / (1 - c) * sigma * V hold for normal,
independent returns. The check backtests a VaR series: Kupiec's test of how often losses exceed it, and
Christoffersen's test of whether the exceedances cluster.
Baseline beaten: normal VaR from a rolling one-year standard deviation, against filtered historical
simulation (EWMA volatility times the empirical quantile of standardised returns), on GARCH data with fat
tails.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
from scipy import stats

from .core import ALPHA, BaselineResult, Flag, as_array, rng_from
from .synthetic import garch_t
from .volatility import ewma_variance

CHAPTER = 17
TITLE = "VaR and expected shortfall"
ASSUMPTION = "normal, independent returns"
BASELINE = "normal VaR from a rolling one-year sd"

_N = NormalDist()


def z_score(conf: float) -> float:
    if not 0.5 < conf < 1:
        raise ValueError("confidence must be between 0.5 and 1")
    return _N.inv_cdf(conf)


def es_multiplier(conf: float) -> float:
    """Expected shortfall of a standard normal in standard deviations: pdf(z) / (1 - c)."""
    return _N.pdf(z_score(conf)) / (1 - conf)


def parametric_var(sigma: float, value: float, conf: float = 0.99, mu: float = 0.0) -> float:
    return (z_score(conf) * sigma - mu) * value


def parametric_es(sigma: float, value: float, conf: float = 0.99, mu: float = 0.0) -> float:
    return (es_multiplier(conf) * sigma - mu) * value


def historical_var(returns, conf: float = 0.99) -> float:
    """Loss (as a positive return) exceeded on a share 1 - conf of past days."""
    return float(-np.quantile(as_array(returns, min_size=20), 1 - conf))


def historical_es(returns, conf: float = 0.99) -> float:
    x = as_array(returns, min_size=20)
    cut = np.quantile(x, 1 - conf)
    return float(-x[x <= cut].mean())


def filtered_historical_var(returns, conf: float = 0.99, lam: float = 0.94, window: int = 1000) -> np.ndarray:
    """One-day VaR forecasts: tomorrow's EWMA volatility times the (1 - conf) quantile of past standardised
    returns. out[t] uses returns up to t - 1; NaN until ``window`` returns are available."""
    x = as_array(returns, min_size=window + 2)
    var_f = ewma_variance(x, lam, init=float(np.var(x[:50])))
    z = x / np.sqrt(var_f)
    out = np.full(x.size, np.nan)
    for t in range(window, x.size):
        out[t] = -math.sqrt(var_f[t]) * np.quantile(z[t - window:t], 1 - conf)
    return out


def kupiec(exceptions: int, n: int, conf: float) -> tuple[float, float]:
    """Kupiec proportion-of-failures test: is the exception rate consistent with 1 - conf? (LR, p)."""
    if n == 0:
        return 0.0, 1.0
    x = exceptions

    def loglik(q: float) -> float:  # log-likelihood of x exceptions in n days at exception rate q
        out = 0.0
        if n - x > 0:
            out += (n - x) * math.log1p(-q) if q < 1 else -math.inf
        if x > 0:
            out += x * math.log(q) if q > 0 else -math.inf
        return out

    lr = max(-2 * (loglik(1 - conf) - loglik(x / n)), 0.0)
    return lr, float(stats.chi2.sf(lr, 1))


def christoffersen(hits) -> tuple[float, float]:
    """Christoffersen test of independence: does an exception today make one tomorrow more likely? (LR, p)."""
    h = np.asarray(hits).astype(int).ravel()
    pairs = list(zip(h[:-1], h[1:], strict=True))
    n00 = sum(1 for a, b in pairs if a == 0 and b == 0)
    n01 = sum(1 for a, b in pairs if a == 0 and b == 1)
    n10 = sum(1 for a, b in pairs if a == 1 and b == 0)
    n11 = sum(1 for a, b in pairs if a == 1 and b == 1)

    def term(count, q):
        return count * math.log(q) if count > 0 else 0.0

    pi = (n01 + n11) / max(len(pairs), 1)
    pi0 = n01 / max(n00 + n01, 1)
    pi1 = n11 / max(n10 + n11, 1)
    l0 = term(n00 + n10, 1 - pi) + term(n01 + n11, pi)
    l1 = term(n00, 1 - pi0) + term(n01, pi0) + term(n10, 1 - pi1) + term(n11, pi1)
    lr = max(-2 * (l0 - l1), 0.0)
    return lr, float(stats.chi2.sf(lr, 1))


def backtest(returns, var_forecasts, conf: float = 0.99) -> dict:
    x = np.asarray(returns, dtype=float)
    v = np.asarray(var_forecasts, dtype=float)
    ok = ~np.isnan(v)
    hits = (x[ok] < -v[ok]).astype(int)
    n, e = int(ok.sum()), int(hits.sum())
    lr_uc, p_uc = kupiec(e, n, conf)
    lr_ind, p_ind = christoffersen(hits)
    return dict(n=n, exceptions=e, rate=e / n if n else float("nan"), kupiec_lr=lr_uc, kupiec_p=p_uc,
                christoffersen_lr=lr_ind, christoffersen_p=p_ind)


def rolling_normal_var(returns, conf: float = 0.99, window: int = 250) -> np.ndarray:
    x = as_array(returns, min_size=window + 2)
    out = np.full(x.size, np.nan)
    z = z_score(conf)
    for t in range(window, x.size):
        seg = x[t - window:t]
        out[t] = z * seg.std(ddof=1) - seg.mean()
    return out


def check(returns, var_forecasts, conf: float = 0.99, alpha: float = ALPHA) -> list[Flag]:
    """Backtest a VaR series against the returns it was meant to cover."""
    b = backtest(returns, var_forecasts, conf)
    return [
        Flag(CHAPTER, "VaR has the right exception rate", "Kupiec", b["kupiec_lr"], b["kupiec_p"],
             b["kupiec_p"] < alpha, f"{b['exceptions']} exceptions in {b['n']} days, expected "
             f"{(1 - conf) * b['n']:.1f}"),
        Flag(CHAPTER, "exceptions are independent", "Christoffersen", b["christoffersen_lr"],
             b["christoffersen_p"], b["christoffersen_p"] < alpha, "exceptions cluster"
             if b["christoffersen_p"] < alpha else ""),
    ]


def beat_baseline(seed=0, runs: int = 6, days: int = 5000, conf: float = 0.99) -> list[BaselineResult]:
    """GARCH returns with t(5) shocks: 99% one-day VaR from both methods, scored by how far the exception
    rate lands from 1% (Kupiec and Christoffersen results in the note)."""
    rng = rng_from(seed)
    d_fhs, d_norm, k_fhs, k_norm = [], [], [], []
    for _ in range(runs):
        r, _h = garch_t(days, sigma=0.01, alpha=0.08, beta=0.9, df=5, seed=rng)
        fhs = filtered_historical_var(r, conf)
        nrm = rolling_normal_var(r, conf)
        nrm[np.isnan(fhs)] = np.nan  # score both on the same days
        bf, bn = backtest(r, fhs, conf), backtest(r, nrm, conf)
        d_fhs.append(abs(bf["rate"] - (1 - conf)))
        d_norm.append(abs(bn["rate"] - (1 - conf)))
        k_fhs.append(bf["kupiec_p"] < ALPHA or bf["christoffersen_p"] < ALPHA)
        k_norm.append(bn["kupiec_p"] < ALPHA or bn["christoffersen_p"] < ALPHA)
    a, b = np.array(d_fhs), np.array(d_norm)
    return [BaselineResult(CHAPTER, "filtered historical simulation", BASELINE,
                           "distance of the exception rate from 1% (percentage points)", float(a.mean() * 100),
                           float(b.mean() * 100), wins=float(np.mean(a < b)),
                           note=f"{runs} runs of {days} days; backtest rejected in {sum(k_fhs)} runs for the "
                                f"method, {sum(k_norm)} for the baseline")]
