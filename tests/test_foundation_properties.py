"""Properties each chapter's formulas must have for any input, checked on seeded random cases."""
import math

import numpy as np
import pytest

from quantbot.foundation import (capm, correlation, diversification, drag, expectation, kelly, minvariance,
                                 montecarlo, normal, randomwalk, returns, scaling, sharpe, tails, timevalue, var,
                                 volatility)
from quantbot.foundation import synthetic as s

RNG = np.random.default_rng(20261111)
CASES = 50


def test_returns_compound_exactly_and_losses_need_bigger_gains():
    for _ in range(CASES):
        r = RNG.uniform(-0.5, 0.5, RNG.integers(1, 30))
        assert math.isclose(returns.compound(r), float(np.prod(1 + r) - 1), rel_tol=1e-9, abs_tol=1e-12)
        assert math.isclose(returns.compound(r), math.expm1(returns.sum_log_returns(r)), rel_tol=1e-9, abs_tol=1e-12)
        loss = RNG.uniform(-0.9, 0)
        assert math.isclose((1 + loss) * (1 + returns.recovery_return(loss)), 1.0)
        assert returns.recovery_return(loss) >= -loss
    with pytest.raises(ValueError):
        returns.compound([0.1, -1.0])


def test_present_and_future_value_are_inverse():
    for _ in range(CASES):
        x, rate, years = RNG.uniform(1, 1e4), RNG.uniform(-0.05, 0.2), RNG.uniform(0, 30)
        assert math.isclose(timevalue.present_value(timevalue.future_value(x, rate, years), rate, years), x)
        assert math.isclose(timevalue.npv([x], rate, [years]), timevalue.present_value(x, rate, years))


def test_expected_value_rules():
    assert expectation.expected_value([1, 2, 3], [0.2, 0.3, 0.5]) == pytest.approx(2.3)
    with pytest.raises(ValueError):
        expectation.expected_value([1, 2], [0.5, 0.6])
    for _ in range(CASES):
        p = RNG.uniform(0, 1)
        assert expectation.bet_ev(p, 1, 1) == pytest.approx(2 * p - 1)


def test_random_walk_distribution_sums_to_one_and_is_symmetric():
    for n in range(0, 25):
        d = randomwalk.end_distribution(n)
        assert math.isclose(sum(d.values()), 1.0)
        assert all(math.isclose(p, d[-k]) for k, p in d.items())
        assert randomwalk.n_end_values(n) == n + 1
    assert randomwalk.arcsine_share(0.5) == pytest.approx(1.0)
    assert randomwalk.arcsine_share(1.0) == 0.0


def test_square_root_rule_composes_and_adjustment_is_neutral_without_autocorrelation():
    for _ in range(CASES):
        v, a, b = RNG.uniform(0.001, 0.05), RNG.uniform(1, 50), RNG.uniform(1, 50)
        assert math.isclose(scaling.scale_vol(scaling.scale_vol(v, a), b), scaling.scale_vol(v, a * b))
    assert scaling.variance_ratio_from([], 10) == 1.0
    x = s.iid_normal(50_000, seed=1)
    assert scaling.scale_vol_adjusted(x, 10) == pytest.approx(scaling.scale_vol(x.std(ddof=1), 10), rel=0.05)


def test_normal_probabilities():
    xs = np.sort(RNG.normal(0, 0.2, CASES))
    probs = [normal.prob_below(x, 0.05, 0.15) for x in xs]
    assert all(a <= b for a, b in zip(probs, probs[1:], strict=False))
    assert normal.return_period(0.25) == 4


def test_volatility_scales_and_ewma_stays_positive():
    for _ in range(CASES):
        r = RNG.normal(0, 0.02, 100)
        c = RNG.uniform(0.1, 10)
        assert math.isclose(volatility.volatility(c * r), c * volatility.volatility(r))
        assert volatility.volatility(r, ddof=0) <= volatility.volatility(r, ddof=1)
    assert (volatility.ewma_variance(RNG.normal(0, 0.02, 500)) > 0).all()


def test_mixing_with_cash_keeps_the_sharpe_ratio_and_lo_factor_reduces_to_sqrt():
    for _ in range(CASES):
        mu, vol, rf, w = RNG.uniform(0.0, 0.2), RNG.uniform(0.05, 0.4), RNG.uniform(0, 0.05), RNG.uniform(0.1, 3)
        assert math.isclose(sharpe.sharpe(*sharpe.mix_with_cash(w, mu, vol, rf), rf=rf), sharpe.sharpe(mu, vol, rf))
    assert sharpe.lo_factor([], 252) == pytest.approx(math.sqrt(252))
    assert sharpe.lo_factor([0.2, 0.04], 252) < math.sqrt(252)  # momentum: sqrt overstates the yearly Sharpe
    assert 0 < sharpe.probabilistic_sharpe(s.iid_normal(1000, mu=0.001, seed=2)) < 1


def test_compound_growth_never_exceeds_the_average_return():
    for _ in range(CASES):
        r = RNG.uniform(-0.5, 0.8, 40)
        assert drag.realized_growth(r) <= r.mean() + 1e-12
        assert drag.growth_rate(r.mean(), r.std()) <= r.mean()


def test_correlation_bounds_and_invariance():
    for _ in range(CASES):
        x = RNG.normal(size=200)
        y = 0.5 * x + RNG.normal(size=200)
        r = correlation.pearson(x, y)
        assert -1 <= r <= 1 and -1 <= correlation.robust_correlation(x, y) <= 1
        assert math.isclose(correlation.pearson(3 * x + 1, 2 * y - 5), r)
    x = RNG.normal(size=100)
    assert correlation.robust_correlation(x, x) == pytest.approx(1.0)


def test_diversification_falls_towards_the_floor():
    for _ in range(CASES):
        sigma, rho = RNG.uniform(0.05, 0.4), RNG.uniform(0, 0.99)
        vols = [diversification.equal_weight_vol(sigma, n, rho) for n in (1, 2, 5, 10, 100, 10_000)]
        assert vols[0] == pytest.approx(sigma)
        assert all(a >= b - 1e-12 for a, b in zip(vols, vols[1:], strict=False))
        assert vols[-1] >= diversification.diversification_floor(sigma, rho) - 1e-12


def test_minimum_variance_weights_are_feasible_and_calmer_than_equal_weights():
    for _ in range(20):
        k = int(RNG.integers(2, 8))
        a = RNG.normal(size=(k, k))
        cov = a @ a.T + 0.1 * np.eye(k)
        cap = max(1.0 / k + 0.05, RNG.uniform(0.2, 1.0))
        w = minvariance.min_variance_weights(cov, True, cap)
        assert w.sum() == pytest.approx(1.0) and (w >= -1e-9).all() and (w <= cap + 1e-9).all()
        eq = np.full(k, 1.0 / k)
        assert w @ cov @ w <= eq @ cov @ eq + 1e-12
        free = minvariance.min_variance_weights(cov, long_only=False)
        assert free @ cov @ free <= w @ cov @ w + 1e-12
    x = s.correlated(120, [0.02] * 6, s.equicorrelation(6, 0.3), seed=3)
    shrunk, delta = minvariance.ledoit_wolf(x)
    assert 0 <= delta <= 1 and (np.linalg.eigvalsh(shrunk) > 0).all()


def test_beta_identities():
    m = RNG.normal(size=500)
    assert capm.beta(m, m) == pytest.approx(1.0)
    assert capm.beta(2 * m + 0.3, m) == pytest.approx(2.0)
    assert capm.capm_expected_return(0.02, 0.0, 0.08) == 0.02


def test_kelly_fraction_maximises_growth():
    for _ in range(CASES):
        p, b = RNG.uniform(0.35, 0.8), RNG.uniform(0.5, 3)
        f = kelly.kelly_fraction(p, b)
        if not 0 < f < 0.95:
            continue
        grid = np.linspace(0, 0.98, 2000)
        best = grid[np.argmax([kelly.log_growth(g, p, b) for g in grid])]
        assert abs(best - f) < 0.002
        n = int(RNG.integers(20, 500))
        wins = int(round(p * n))
        assert kelly.shrunk_kelly(wins, n, b) <= max(kelly.kelly_fraction(wins / n, b), 0) + 1e-12
    assert kelly.shrunk_kelly(40, 100, 1.0) == 0.0  # no edge, no bet


def test_monte_carlo_helpers():
    assert montecarlo.paths_needed(0.4, 0.2, 1000) == pytest.approx(4000)
    w = montecarlo.terminal_wealth(0.05, 0.1, 10, 20_000, seed=4, antithetic=True)
    mean, se = montecarlo.mean_with_se(w)
    assert abs(mean - math.exp(10 * (0.05 + 0.005))) < 4 * se
    x = RNG.normal(size=300)
    boot = montecarlo.block_bootstrap(x, 1000, block=20, seed=5)
    assert boot.size == 1000 and np.isin(boot, x).all()


def test_tail_measures():
    ks = np.linspace(0, 6, 25)
    probs = [tails.prob_below_sigma(k) for k in ks]
    assert all(a > b for a, b in zip(probs, probs[1:], strict=False))
    assert tails.years_between(1 / 252) == pytest.approx(1.0)
    assert tails.hill_tail_index(s.iid_normal(20_000, seed=6)) > tails.hill_tail_index(s.student_t(20_000, 3, seed=7))
    assert tails.excess_kurtosis(s.student_t(50_000, 5, seed=8)) > 1


def test_var_is_monotone_and_expected_shortfall_exceeds_var():
    for conf in (0.9, 0.95, 0.975, 0.99, 0.995):
        assert var.parametric_es(0.01, 1.0, conf) > var.parametric_var(0.01, 1.0, conf)
    assert var.parametric_var(0.01, 1, 0.99) > var.parametric_var(0.01, 1, 0.95)
    x = s.student_t(20_000, 4, seed=9)
    assert var.historical_es(x, 0.99) >= var.historical_var(x, 0.99) > var.historical_var(x, 0.95)
    fhs = var.filtered_historical_var(x, 0.99, window=500)
    assert np.isnan(fhs[:500]).all() and (fhs[500:] > 0).all()
