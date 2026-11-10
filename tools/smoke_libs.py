"""Phase 0 smoke test of candidate third-party libraries (import + one minimal example each).
Synthetic, seeded data only. This checks that a library installs and runs on Python 3.11,
not that it is fit for purpose. Run inside the smoke environment: python tools/smoke_libs.py
"""
from __future__ import annotations
import importlib.metadata as md
import math
import sys
import traceback
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
N = 750
idx = pd.bdate_range("2023-01-02", periods=N)
common = rng.normal(0.0003, 0.008, N)
rets = pd.DataFrame({f"A{i}": common * b + rng.normal(0.0002, 0.01, N) for i, b in enumerate([1.0, 0.8, 1.2, 0.3, 0.0])}, index=idx)
prices = 100 * (1 + rets).cumprod()
RESULTS = []


def ver(name: str) -> str:
    try:
        return md.version(name)
    except Exception:
        return "?"


def check(label: str, dist: str):
    def deco(fn):
        try:
            out = fn()
            RESULTS.append((label, ver(dist), "OK", str(out)))
        except Exception as e:  # report, never hide
            RESULTS.append((label, ver(dist), "FAIL", f"{type(e).__name__}: {str(e)[:140]}"))
            traceback.print_exc(limit=1, file=sys.stderr)
        return fn
    return deco


@check("statsmodels (ADF, Engle-Granger)", "statsmodels")
def _():
    from statsmodels.tsa.stattools import adfuller, coint
    x = np.cumsum(rng.normal(0, 1, 1000))
    y = 0.7 * x + rng.normal(0, 1, 1000)          # cointegrated by construction
    z = np.cumsum(rng.normal(0, 1, 1000))         # independent random walk
    return f"coint p (true pair)={coint(y, x)[1]:.4f}, coint p (independent walks)={coint(z, x)[1]:.3f}, ADF p (random walk)={adfuller(x)[1]:.3f}"


@check("arch (GARCH(1,1))", "arch")
def _():
    from arch import arch_model
    from arch.univariate import Normal
    am = arch_model(None, p=1, q=1)
    am.distribution = Normal(seed=7)                  # arch draws from the distribution's own generator
    sim = am.simulate([0.0, 0.05, 0.08, 0.90], 10000)
    res = arch_model(sim["data"], p=1, q=1).fit(disp="off")
    p = res.params
    return f"true alpha=0.08 beta=0.90 -> fitted alpha={p['alpha[1]']:.3f} beta={p['beta[1]']:.3f}"


@check("skfolio (min-variance, HRP)", "skfolio")
def _():
    from skfolio.optimization import HierarchicalRiskParity, MeanRisk
    w1 = MeanRisk().fit(rets).weights_
    w2 = HierarchicalRiskParity().fit(rets).weights_
    return f"min-risk weights sum={w1.sum():.3f} max={w1.max():.2f}; HRP weights sum={w2.sum():.3f} max={w2.max():.2f}"


@check("PyPortfolioOpt (Ledoit-Wolf, min vol, HRP)", "pyportfolioopt")
def _():
    from pypfopt import EfficientFrontier, HRPOpt, risk_models
    S = risk_models.CovarianceShrinkage(prices).ledoit_wolf()
    ef = EfficientFrontier(None, S, weight_bounds=(0, 0.4))
    w = ef.min_volatility()
    h = HRPOpt(rets).optimize()
    return f"min-vol weights sum={sum(w.values()):.3f} max={max(w.values()):.2f}; HRP sum={sum(h.values()):.3f}"


@check("Riskfolio-Lib (HRP)", "riskfolio-lib")
def _():
    import riskfolio as rp
    port = rp.HCPortfolio(returns=rets)
    w = port.optimization(model="HRP", codependence="pearson", rm="MV", linkage="single", leaf_order=True)
    return f"HRP weights sum={float(w.sum().iloc[0]):.3f} max={float(w.max().iloc[0]):.2f}"


@check("py_vollib (Black-Scholes)", "py_vollib")
def _():
    from py_vollib.black_scholes import black_scholes
    from py_vollib.black_scholes.implied_volatility import implied_volatility
    c = black_scholes("c", 100, 100, 1.0, 0.05, 0.2)
    iv = implied_volatility(c, 100, 100, 1.0, 0.05, "c")
    return f"call={c:.6f} (reference 10.450584), implied vol round-trip={iv:.6f}"


@check("QuantLib (analytic European)", "QuantLib")
def _():
    import QuantLib as ql
    today = ql.Date(10, 11, 2026)
    ql.Settings.instance().evaluationDate = today
    dc = ql.Actual365Fixed()
    opt = ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Call, 100.0), ql.EuropeanExercise(today + 365))
    proc = ql.BlackScholesMertonProcess(
        ql.QuoteHandle(ql.SimpleQuote(100.0)),
        ql.YieldTermStructureHandle(ql.FlatForward(today, 0.0, dc)),
        ql.YieldTermStructureHandle(ql.FlatForward(today, 0.05, dc)),
        ql.BlackVolTermStructureHandle(ql.BlackConstantVol(today, ql.NullCalendar(), 0.2, dc)))
    opt.setPricingEngine(ql.AnalyticEuropeanEngine(proc))
    return f"call={opt.NPV():.6f} (reference 10.450584), delta={opt.delta():.4f}"


@check("vectorbt (MA crossover with fees)", "vectorbt")
def _():
    import vectorbt as vbt
    px = prices["A0"]
    fast, slow = px.rolling(10).mean(), px.rolling(50).mean()
    entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    exits = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    pf = vbt.Portfolio.from_signals(px, entries.shift(1, fill_value=False), exits.shift(1, fill_value=False), fees=0.001, slippage=0.0005, freq="1D")
    return f"synthetic series: trades={pf.trades.count()}, total return={pf.total_return():.3%} (no meaning, synthetic)"


@check("backtrader (SMA cross)", "backtrader")
def _():
    import backtrader as bt
    df = pd.DataFrame({"open": prices["A0"], "high": prices["A0"] * 1.005, "low": prices["A0"] * 0.995, "close": prices["A0"], "volume": 1e6})

    class S(bt.Strategy):
        def __init__(self):
            self.x = bt.ind.CrossOver(bt.ind.SMA(period=10), bt.ind.SMA(period=50))

        def next(self):
            if not self.position and self.x > 0:
                self.buy()
            elif self.position and self.x < 0:
                self.close()

    c = bt.Cerebro()
    c.adddata(bt.feeds.PandasData(dataname=df))
    c.addstrategy(S)
    c.broker.setcommission(commission=0.001)
    c.run()
    return f"final value={c.broker.getvalue():.2f} from 10000 (synthetic)"


@check("bt (monthly equal weight)", "bt")
def _():
    import bt
    s = bt.Strategy("ew", [bt.algos.RunMonthly(), bt.algos.SelectAll(), bt.algos.WeighEqually(), bt.algos.Rebalance()])
    res = bt.run(bt.Backtest(s, prices))
    return f"total return={res.stats.loc['total_return'].iloc[0]:.3%} (synthetic)"


@check("hftbacktest (import)", "hftbacktest")
def _():
    import hftbacktest
    names = [n for n in ("HashMapMarketDepthBacktest", "BacktestAsset", "ROIVectorMarketDepthBacktest") if hasattr(hftbacktest, n)]
    return f"import ok; API present: {', '.join(names)}"


@check("NautilusTrader (import, engine construct)", "nautilus_trader")
def _():
    from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
    from nautilus_trader.config import LoggingConfig
    eng = BacktestEngine(config=BacktestEngineConfig(trader_id="TESTER-001", logging=LoggingConfig(bypass_logging=True)))
    eng.dispose()
    return "BacktestEngine constructed and disposed"


@check("exchange_calendars (XNYS)", "exchange_calendars")
def _():
    import exchange_calendars as xc
    cal = xc.get_calendar("XNYS")
    s = cal.sessions_in_range("2026-01-01", "2026-12-31")
    return f"2026 sessions={len(s)}; Thanksgiving 2026-11-26 open={cal.is_session('2026-11-26')}; 2026-11-27 close={cal.session_close('2026-11-27').tz_convert('America/New_York').strftime('%H:%M')}"


@check("DuckDB + Parquet round trip", "duckdb")
def _():
    import os, tempfile
    import duckdb
    d = tempfile.mkdtemp()
    p = os.path.join(d, "px.parquet")
    prices.reset_index(names="ts").to_parquet(p)
    n, mx = duckdb.sql(f"select count(*), max(ts) from '{p}'").fetchall()[0]  # DuckDB 2.x: relations have no fetchone()
    return f"rows={n}, max ts={str(mx)[:10]}"


if __name__ == "__main__":
    print(f"python {sys.version.split()[0]}, numpy {np.__version__}, pandas {pd.__version__}")
    for label, v, status, out in RESULTS:
        print(f"[{status}] {label} {v}: {out}")
    print(f"{sum(r[2] == 'OK' for r in RESULTS)}/{len(RESULTS)} OK")
