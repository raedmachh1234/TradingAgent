"""Shared pieces of the book foundation: assumption flags, baseline results and the tests behind them.

Every statistical test here is written from its published formula. Nothing is copied from the e-book,
whose code licence is unknown; only its formulas and worked answers are used (see tests/fixtures).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

ALPHA = 0.01  # significance level for every assumption flag


@dataclass(frozen=True)
class Flag:
    """The outcome of one assumption check. ``failed`` is True when the data contradicts the assumption."""

    chapter: int
    assumption: str
    test: str
    statistic: float
    p_value: float | None
    failed: bool
    detail: str

    def line(self) -> str:
        p = "" if self.p_value is None else f", p={self.p_value:.3g}"
        state = "FAILS" if self.failed else "holds"
        return f"ch{self.chapter:>2} {self.assumption}: {state} ({self.test}: {self.statistic:.3g}{p}) {self.detail}"


@dataclass(frozen=True)
class BaselineResult:
    """A chapter method against the naive baseline it replaces, on synthetic data with a known truth."""

    chapter: int
    method: str
    baseline: str
    metric: str
    method_score: float
    baseline_score: float
    lower_is_better: bool = True
    wins: float | None = None  # share of the simulated cases in which the method did at least as well
                               # (None when the comparison is a single aggregate number)
    note: str = ""

    @property
    def beats(self) -> bool:
        if self.lower_is_better:
            return self.method_score < self.baseline_score
        return self.method_score > self.baseline_score


def as_array(x, *, min_size: int = 3) -> np.ndarray:
    a = np.asarray(x, dtype=float).ravel()
    if a.size < min_size:
        raise ValueError(f"need at least {min_size} observations, got {a.size}")
    if not np.isfinite(a).all():
        raise ValueError("data contains NaN or infinite values")
    return a


def rng_from(seed) -> np.random.Generator:
    return seed if isinstance(seed, np.random.Generator) else np.random.default_rng(seed)


def autocorrelations(x, lags: int) -> np.ndarray:
    """Sample autocorrelations at lags 1..lags (the usual biased estimator, divided by the full sum of squares)."""
    a = as_array(x)
    d = a - a.mean()
    denom = float(d @ d)
    if denom == 0.0:
        return np.zeros(lags)
    return np.array([float(d[k:] @ d[:-k]) / denom for k in range(1, lags + 1)])


def ljung_box(x, lags: int = 10) -> tuple[float, float]:
    """Ljung-Box Q statistic and its chi-square p-value: are the first ``lags`` autocorrelations all zero?"""
    a = as_array(x, min_size=lags + 3)
    n = a.size
    r = autocorrelations(a, lags)
    q = n * (n + 2) * float(np.sum(r**2 / (n - np.arange(1, lags + 1))))
    return q, float(stats.chi2.sf(q, lags))


def robust_box_pierce(x, lags: int = 10) -> tuple[float, float]:
    """Box-Pierce test of zero autocorrelation with each lag's variance estimated from the data, so volatility
    clustering alone does not make returns look predictable (the plain Ljung-Box test over-rejects then).
    Q* = n * sum_k rho_k^2 / tau_k with tau_k = n * sum_t d_t^2 d_{t-k}^2 / (sum_t d_t^2)^2."""
    a = as_array(x, min_size=lags + 3)
    n = a.size
    d = a - a.mean()
    sq = d**2
    s2 = float(sq.sum())
    if s2 == 0.0:
        return 0.0, 1.0
    rho = autocorrelations(a, lags)
    tau = np.array([n * float(sq[k:] @ sq[:-k]) / s2**2 for k in range(1, lags + 1)])
    q = n * float(np.sum(rho**2 / tau))
    return q, float(stats.chi2.sf(q, lags))


def mcleod_li(x, lags: int = 10) -> tuple[float, float]:
    """Ljung-Box on squared deviations: does today's size of move predict tomorrow's (volatility clustering)?"""
    a = as_array(x, min_size=lags + 3)
    return ljung_box((a - a.mean()) ** 2, lags)


def jarque_bera(x) -> tuple[float, float, float, float]:
    """Jarque-Bera normality test. Returns (statistic, p-value, skewness, excess kurtosis)."""
    a = as_array(x, min_size=8)
    res = stats.jarque_bera(a)
    return float(res.statistic), float(res.pvalue), float(stats.skew(a)), float(stats.kurtosis(a))


def variance_ratio(x, q: int) -> tuple[float, float, float]:
    """Lo-MacKinlay variance ratio VR(q) with the heteroskedasticity-robust z statistic.

    VR(q) = 1 + 2 * sum_{k<q} (1 - k/q) * rho_k is 1 for independent returns, above 1 under momentum and
    below 1 under mean reversion. Returns (VR, z*, two-sided p-value).
    """
    a = as_array(x, min_size=q + 10)
    n = a.size
    d = a - a.mean()
    s2 = float(d @ d)
    rho = autocorrelations(a, q - 1)
    k = np.arange(1, q)
    vr = 1.0 + 2.0 * float(np.sum((1.0 - k / q) * rho))
    sq = d**2
    delta = np.array([n * float(sq[j:] @ sq[:-j]) / s2**2 for j in k])
    theta = float(np.sum((2.0 * (q - k) / q) ** 2 * delta))  # asymptotic variance of sqrt(n) (VR - 1)
    z = math.sqrt(n) * (vr - 1.0) / math.sqrt(theta) if theta > 0 else 0.0
    return vr, z, float(2 * stats.norm.sf(abs(z)))


def runs_test(signs) -> tuple[float, float]:
    """Wald-Wolfowitz runs test on a two-valued sequence (wins and losses). Returns (z, two-sided p)."""
    s = np.asarray(signs).astype(bool).ravel()
    n1, n2 = int(s.sum()), int((~s).sum())
    n = n1 + n2
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0
    runs = 1 + int(np.count_nonzero(s[1:] != s[:-1]))
    mean = 2.0 * n1 * n2 / n + 1.0
    var = 2.0 * n1 * n2 * (2.0 * n1 * n2 - n) / (n**2 * (n - 1))
    z = (runs - mean) / math.sqrt(var) if var > 0 else 0.0
    return z, float(2 * stats.norm.sf(abs(z)))


def correlation_p_value(r: float, n: int) -> float:
    """Two-sided p-value for a Pearson correlation of r over n pairs (t test with n - 2 degrees of freedom)."""
    if n < 4:
        return 1.0
    r = max(min(r, 0.999999), -0.999999)
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return float(2 * stats.t.sf(abs(t), n - 2))


def independence_flag(chapter: int, x, lags: int = 10, alpha: float = ALPHA) -> Flag:
    """Are returns uncorrelated with their own past? Robust to volatility clustering, which chapter 7's
    clustering_flag covers separately."""
    q, p = robust_box_pierce(x, lags)
    return Flag(chapter, "uncorrelated returns", f"robust Box-Pierce, {lags} lags", q, p, p < alpha,
                "past returns predict future ones" if p < alpha else "")


def clustering_flag(chapter: int, x, lags: int = 10, alpha: float = ALPHA) -> Flag:
    q, p = mcleod_li(x, lags)
    return Flag(chapter, "constant volatility", f"McLeod-Li, {lags} lags", q, p, p < alpha,
                "calm and wild periods cluster" if p < alpha else "")


def normality_flag(chapter: int, x, alpha: float = ALPHA) -> Flag:
    jb, p, skew, kurt = jarque_bera(x)
    detail = f"skew {skew:+.2f}, excess kurtosis {kurt:.2f}"
    return Flag(chapter, "normal returns", "Jarque-Bera", jb, p, p < alpha, detail)
