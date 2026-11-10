"""Phase 0 smoke test: PFHedge (deep hedging) and purgedcv (purged / combinatorial CV).
Checks that the libraries run on current PyTorch and that purging really separates train from test.
NOT a benchmark: the deep hedger is trained for a handful of epochs on few paths.
Run in its own environment: PFHedge 0.23.0 pins numpy < 2, which conflicts with pyarrow 26 and
the portfolio libraries.   python tools/smoke_ml_libs.py
"""
from __future__ import annotations
import time
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd


def pfhedge_check() -> None:
    import torch
    import pfhedge
    from pfhedge.instruments import BrownianStock, EuropeanOption
    from pfhedge.nn import BlackScholes, Hedger, MultiLayerPerceptron, WhalleyWilmott

    torch.manual_seed(42)
    print(f"torch {torch.__version__}, pfhedge {pfhedge.__version__}, cuda available: {torch.cuda.is_available()}")
    stock = BrownianStock(cost=1e-4)                     # 1 bp proportional cost
    deriv = EuropeanOption(stock)                        # at-the-money call, library defaults
    out = {}
    t0 = time.time()
    for name, model in (("no hedge", None), ("Black-Scholes delta", BlackScholes(deriv)), ("Whalley-Wilmott", WhalleyWilmott(deriv))):
        torch.manual_seed(42)
        if model is None:
            from pfhedge.nn import Naked
            hedger = Hedger(Naked(), inputs=["empty"])
        else:
            hedger = Hedger(model, inputs=model.inputs())
        out[name] = float(hedger.price(deriv, n_paths=20000))
    torch.manual_seed(42)
    mlp = MultiLayerPerceptron()
    hedger = Hedger(mlp, inputs=["log_moneyness", "expiry_time", "volatility", "prev_hedge"])
    hedger.fit(deriv, n_epochs=40, n_paths=5000, verbose=False)
    torch.manual_seed(42)
    out["deep hedger, 40 epochs (under-trained on purpose)"] = float(hedger.price(deriv, n_paths=20000))
    for k, v in out.items():
        print(f"  entropic-risk price, {k}: {v:.5f}")
    print(f"  pfhedge ran in {time.time() - t0:.1f}s on CPU")


def purgedcv_check() -> None:
    import purgedcv
    from purgedcv import CombinatorialPurgedCV, PurgedKFold

    n, horizon = 500, 5
    t = pd.bdate_range("2024-01-01", periods=n)
    pred = pd.Series(t)
    evalt = pd.Series(t).shift(-horizon).fillna(t[-1])   # label of bar i is known at bar i+5
    X = np.zeros((n, 1))
    cv = PurgedKFold(5, prediction_times=pred, evaluation_times=evalt, embargo_observations=5)
    leaks, sizes = 0, []
    for tr, te in cv.split(X):
        te_lo, te_hi = pred.iloc[te].min(), evalt.iloc[te].max()
        overlap = (evalt.iloc[tr] >= te_lo) & (pred.iloc[tr] <= te_hi)   # train label interval touches the test span
        leaks += int(overlap.sum())
        sizes.append((len(tr), len(te)))
    print(f"purgedcv {getattr(purgedcv, '__version__', '0.1.12')}: PurgedKFold folds (train, test) = {sizes}; train labels overlapping a test span = {leaks}")
    cpcv = CombinatorialPurgedCV(6, 2, prediction_times=pred, evaluation_times=evalt, embargo_observations=5)
    print(f"  CombinatorialPurgedCV(6 groups, 2 test): {sum(1 for _ in cpcv.split(X))} splits (expected C(6,2) = 15)")
    rng = np.random.default_rng(3)
    r = rng.normal(0.0004, 0.01, 1000)
    from purgedcv import deflated_sharpe_ratio, probabilistic_sharpe_ratio
    sr = r.mean() / r.std(ddof=1)
    psr = probabilistic_sharpe_ratio(r, 0.0)
    dsr1 = deflated_sharpe_ratio(r, 1, 0.0005)
    dsr100 = deflated_sharpe_ratio(r, 100, 0.0005)
    print(f"  per-bar Sharpe {sr:.4f}: PSR(0) = {psr:.3f}; DSR with 1 trial = {dsr1:.3f}; DSR with 100 trials = {dsr100:.3f} (must fall as trials rise)")


if __name__ == "__main__":
    for fn in (purgedcv_check, pfhedge_check):
        try:
            fn()
        except Exception as e:
            print(f"[FAIL] {fn.__name__}: {type(e).__name__}: {str(e)[:300]}")
