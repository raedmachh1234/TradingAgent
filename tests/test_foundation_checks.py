"""Assumption flags fire where the assumption breaks and stay quiet where it holds."""
import numpy as np
import pytest

from quantbot.foundation import (capm, core, correlation, diversification, expectation, kelly, minvariance,
                                 normal, randomwalk, scaling, sharpe, tails, var, volatility)
from quantbot.foundation import synthetic as s

N = 2000


def rate(check, gen, seeds=30):
    return float(np.mean([any(f.failed for f in check(gen(i))) for i in range(seeds)]))


def iid(i):
    return s.iid_normal(N, seed=1000 + i)


def momentum(i):
    return s.ar1(N, 0.15, seed=2000 + i)


def garch(i):
    return s.garch_t(N, seed=3000 + i)[0]


@pytest.mark.parametrize("check", [randomwalk.check, scaling.check, normal.check, volatility.check,
                                   sharpe.check, tails.check],
                         ids=["ch4", "ch5", "ch6", "ch7", "ch8", "ch16"])
def test_checks_stay_quiet_on_independent_normal_returns(check):
    assert rate(check, iid) <= 0.10


def test_return_checks_fire_on_momentum():
    assert rate(lambda x: [core.independence_flag(4, x)], momentum) >= 0.9
    # the 10-period variance ratio needs more data for the same power
    assert rate(scaling.check, lambda i: s.ar1(4000, 0.15, seed=2500 + i)) >= 0.8


def test_return_checks_ignore_volatility_clustering():
    # GARCH returns are uncorrelated; only their sizes depend on the past
    assert rate(lambda x: [core.independence_flag(4, x)], garch) <= 0.10
    assert rate(scaling.check, garch) <= 0.10


def test_plain_ljung_box_over_rejects_on_garch_and_the_robust_test_does_not():
    plain = np.mean([core.ljung_box(garch(i))[1] < 0.01 for i in range(30)])
    robust = np.mean([core.robust_box_pierce(garch(i))[1] < 0.01 for i in range(30)])
    assert robust <= plain


@pytest.mark.parametrize("check", [normal.check, volatility.check, lambda x: tails.check(x)[1:],
                                   lambda x: randomwalk.check(x)[2:]],
                         ids=["normality", "clustering", "tail count", "step sizes"])
def test_shape_checks_fire_on_fat_tailed_clustered_returns(check):
    assert rate(check, garch) >= 0.9


def test_variance_ratio_is_calibrated_and_signed():
    ps = np.array([core.variance_ratio(iid(i), 5)[2] for i in range(200)])
    assert 0.01 <= float(np.mean(ps < 0.05)) <= 0.10
    vr, z, p = core.variance_ratio(s.ar1(5000, 0.2, seed=1), 5)
    assert vr > 1.2 and z > 3 and p < 1e-3
    vr, z, p = core.variance_ratio(s.ar1(5000, -0.2, seed=2), 5)
    assert vr < 0.8 and z < -3


def test_var_backtest_rejects_normal_var_on_fat_tails_only():
    def kupiec_fails(x):
        return var.check(x, var.rolling_normal_var(x))[0].failed
    assert np.mean([kupiec_fails(iid(i)) for i in range(10)]) <= 0.1
    assert np.mean([kupiec_fails(s.garch_t(4000, seed=4000 + i)[0]) for i in range(10)]) >= 0.8


def test_kupiec_and_christoffersen_known_cases():
    lr, p = var.kupiec(10, 1000, 0.99)  # exactly the expected 1%
    assert lr == pytest.approx(0.0, abs=1e-9) and p > 0.99
    lr, p = var.kupiec(30, 1000, 0.99)
    assert lr > 10 and p < 0.01
    clustered = np.zeros(1000, dtype=int)
    clustered[[100, 101, 102, 500, 501, 502, 800, 801, 802, 803]] = 1
    spread = np.zeros(1000, dtype=int)
    spread[::100] = 1
    assert var.christoffersen(clustered)[1] < 0.01
    assert var.christoffersen(spread)[1] > 0.1


def test_hidden_dependence_is_flagged_and_a_linear_relation_is_not():
    rng = np.random.default_rng(3)
    g, _ = s.garch_t(N, seed=5)
    hidden = np.sign(rng.standard_normal(N)) * np.abs(g) * np.abs(rng.standard_normal(N))
    assert correlation.check(g, hidden)[-1].failed
    m = rng.standard_normal(N)
    assert not correlation.check(m, 0.8 * m + rng.standard_normal(N))[-1].failed
    # the book's example: Y = X^2 has zero covariance with X yet depends on it entirely
    x = rng.choice([-1.0, 0.0, 1.0], N)
    assert correlation.check(x, x**2 + 0.01 * rng.standard_normal(N))[-1].failed


def test_stress_correlation_check():
    assert diversification.check(s.regime_correlated(N, 5, seed=6))[0].failed
    calm = [diversification.check(s.correlated(N, [0.01] * 5, s.equicorrelation(5, 0.4), seed=700 + i),
                                  seed=i)[0].failed for i in range(10)]
    assert sum(calm) <= 1


def test_beta_stability_check():
    rng = np.random.default_rng(8)
    m = rng.standard_normal(N)
    assert not capm.check(1.2 * m + rng.standard_normal(N), m)[0].failed
    jump = np.concatenate([0.5 * m[:N // 2], 1.5 * m[N // 2:]]) + rng.standard_normal(N)
    assert capm.check(jump, m)[0].failed


def test_weight_stability_check():
    vols = np.full(10, 0.04)
    corr = s.equicorrelation(10, 0.5)
    assert minvariance.check(s.correlated(36, vols, corr, seed=9))[0].failed
    assert not minvariance.check(s.correlated(600, vols, corr, seed=10))[0].failed


def test_edge_checks_need_enough_evidence():
    rng = np.random.default_rng(11)
    assert expectation.check(0.05 + 0.5 * rng.standard_normal(60))[0].failed
    assert not expectation.check(0.05 + 0.5 * rng.standard_normal(5000))[0].failed
    assert kelly.check(rng.random(60) < 0.55, 1.0)[0].failed
    assert not kelly.check(rng.random(5000) < 0.55, 1.0)[0].failed


def test_runs_test_sees_streaks_and_alternation():
    streaks = np.repeat([1, 0] * 25, 8)
    z, p = core.runs_test(streaks)
    assert z < 0 and p < 0.01
    z, p = core.runs_test(np.tile([1, 0], 200))
    assert z > 0 and p < 0.01
    assert kelly.check(streaks, 1.0)[1].failed


def test_flags_read_as_one_line():
    line = normal.check(garch(0))[0].line()
    assert line.startswith("ch 6 normal returns: FAILS") and "Jarque-Bera" in line


def test_bad_input_is_refused():
    with pytest.raises(ValueError):
        normal.check([0.01, float("nan"), 0.02] * 10)
    with pytest.raises(ValueError):
        randomwalk.check([0.01, 0.02])
