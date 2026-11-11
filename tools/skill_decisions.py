"""Phase 0 keep/merge/cut decisions, joined to the static audit and the test run.
Writes docs/phase0/skill_decisions.csv and prints the projection used in the report.
Run: python tools/skill_decisions.py
Decision vocabulary
  KEEP       converted to a typed module
  MERGE      folded into one shared implementation (see `target`)
  CANDIDATE  strategy or signal; becomes a sub-bot spec, enabled only after it passes the backtest gate
  OPTIONAL   regime feature; converted late, enabled only if it improves out-of-sample results
  CUT        not carried over
det: D = deterministic, no network; D* = deterministic given its inputs but fetches live data; L = needs an LLM, web search or image
"""
from __future__ import annotations
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS, DTS, CTS = "trader-skill", "day-trader-skill", "claude-trading-skills"

# (repo, skill, decision, target, det, data, duplicates, backtestable, reason)
D = [
 # ---- trader-skill -------------------------------------------------------------------------
 (TS, "trader-risk", "MERGE", "risk gate", "D", "local files only", "drawdown-circuit-breaker, pre-trade-discipline-gate, day-trader risk", "n/a, runs inside replay",
  "Sequential batch check bound to an order fingerprint; rule core of the single risk gate"),
 (TS, "trader-broker", "KEEP", "proposal schema", "D", "none; Alpaca stock-order field names", "day-trader broker", "n/a",
  "Keep ticket schema and fingerprint binding as the proposal payload; drop chat 'yes' parsing (ApprovalService replaces it); extend fields for stop, target and CFD size"),
 (TS, "trader-budget", "MERGE", "position sizing", "D", "local files only", "position-sizer, futures-position-sizer, day-trader budget", "n/a",
  "Cash buffer and per-name cap become constraints of the one sizing module"),
 (TS, "trader-news", "MERGE", "news ingestion", "D*", "SEC 8-K feed (public); Yahoo RSS (personal use)", "market-news-analyst", "only what we archive from now on",
  "Keep SEC 8-K and RSS ingestion; Yahoo feed replaced or kept as non-live fallback; LLM may only classify headlines"),
 (TS, "trader-analyst", "KEEP", "fundamentals reader", "D*", "SEC XBRL company facts (public, 10 requests/s, User-Agent required)", "us-stock-analysis", "yes, by filing date",
  "Useful only if US equities are in scope"),
 (TS, "trader-copycat", "KEEP", "13F parser (edgar13f.py only)", "D*", "SEC EDGAR (public); OpenFIGI", "institutional-flow-tracker", "yes, by filing date (45-day lag)",
  "One 13F implementation; 'copy an investor' is a candidate strategy, not an enabled feature"),
 (TS, "trader-pelosi", "CUT", "", "D*", "House Clerk PDFs; needs pdftotext", "", "", "Per brief; fragile PDF parsing and long disclosure lag"),
 (TS, "trader-tax", "CUT", "", "D", "local files only", "kanchi-dividend-us-tax-accounting", "", "US tax-lot and wash-sale rules; jurisdiction-specific"),
 (TS, "trader-alerts", "KEEP", "market calendar (NYSE table only)", "D", "holiday table in code; prices via Yahoo and Stooq", "_market_calendar.py copied into 8 skills", "n/a",
  "Keep the NYSE holiday and half-day table as an offline fixture for the one calendar module; drop price alerts"),
 (TS, "trader-rebalance", "KEEP", "rebalancer", "D", "local files only", "portfolio-manager", "n/a, runs inside replay", "Drift-band rebalancer; feeds the capital allocator"),
 (TS, "trader-screener", "MERGE", "screener engine", "D", "local metrics file", "every screener in claude-trading-skills", "yes, if metrics are point-in-time",
  "Smallest generic rule engine; becomes the single screener engine"),
 # ---- day-trader-skill (optional) ----------------------------------------------------------
 (DTS, "trader-risk", "MERGE", "risk gate", "D", "local files only", "trader-skill risk", "n/a, runs inside replay",
  "Later rewrite: entries vs exits asymmetry and a pinned clock; preferred merge source"),
 (DTS, "trader-broker", "MERGE", "proposal schema", "D", "none", "trader-skill broker", "n/a", "Diff against v1 and take the stricter rules"),
 (DTS, "trader-budget", "MERGE", "position sizing", "D", "local files only", "trader-skill budget", "n/a", "Diff against v1 and take the stricter rules"),
 (DTS, "trader-timemachine", "KEEP", "replay simulator (method)", "D*", "Yahoo 5-minute bars (unofficial)", "", "yes",
  "Seeded bootstrap replay plus the same rule on past sessions; re-implemented on our data layer with standard errors"),
 (DTS, "trader-entry", "CANDIDATE", "ORB sub-bot", "D*", "Yahoo intraday bars (unofficial)", "", "yes, with licensed intraday data",
  "Opening-range breakout on completed bars, long only; must pass the backtest gate"),
 (DTS, "trader-exit", "CANDIDATE", "ORB sub-bot", "D*", "Yahoo intraday bars (unofficial)", "", "yes, with licensed intraday data",
  "Stop and target planner (range, percent, ATR); part of the ORB candidate"),
 (DTS, "trader-scanner", "CUT", "", "D*", "Nasdaq Trader lists; Yahoo", "trader-screener", "", "Universe scan tied to Yahoo; screener engine plus data layer replace it"),
 (DTS, "trader-alerts", "CUT", "", "D", "Yahoo and Stooq", "trader-skill alerts", "", "Duplicate; calendar table taken from trader-skill"),
 (DTS, "trader-analyst", "CUT", "", "D*", "SEC XBRL", "trader-skill analyst (1 line differs)", "", "Duplicate"),
 (DTS, "trader-news", "CUT", "", "D*", "SEC, Yahoo RSS", "trader-skill news", "", "Duplicate; diff for improvements during the merge"),
 (DTS, "trader-pelosi", "CUT", "", "D*", "House Clerk", "trader-skill pelosi (1 line differs)", "", "Per brief"),
 # ---- claude-trading-skills ----------------------------------------------------------------
 (CTS, "backtest-expert", "KEEP", "research checklist", "D", "none", "edge-strategy-reviewer", "n/a",
  "Keep the red-flag checks; replace the heuristic 0-100 score with deflated Sharpe, PBO and confidence intervals"),
 (CTS, "breadth-chart-analyst", "CUT", "", "L", "chart images, OpenCV", "market-breadth-analyzer", "no", "Reads chart images"),
 (CTS, "breakout-trade-planner", "CUT", "", "D", "consumes vcp-screener output", "", "", "Only useful downstream of VCP, which is cut pending backtest"),
 (CTS, "canslim-screener", "CUT", "", "D*", "FMP key required; bs4 scraping", "", "needs point-in-time fundamentals", "Cut pending backtest; re-enters only through the candidate gate"),
 (CTS, "contrarian-setup-gate", "CUT", "", "D", "none", "", "", "Final step of the COT chain"),
 (CTS, "cot-contrarian-detector", "CUT", "", "D*", "FMP key required", "", "", "COT chain; CFTC publishes the data free if revisited"),
 (CTS, "crypto-regime-analyzer", "CUT", "", "D*", "CoinGecko, Binance", "", "", "Beta; per brief"),
 (CTS, "data-quality-checker", "CUT", "", "D", "none", "", "", "Validates blog and markdown documents, not market data; the data layer gets its own checks"),
 (CTS, "dividend-growth-pullback-screener", "CUT", "", "D*", "FMP required, FINVIZ", "", "", "Per brief"),
 (CTS, "downtrend-duration-analyzer", "CUT", "", "D*", "FMP key required", "", "", "Descriptive histograms only"),
 (CTS, "drawdown-circuit-breaker", "MERGE", "risk gate", "D", "none; reads the journal", "trader-risk, pre-trade-discipline-gate", "n/a, runs inside replay",
  "Daily loss, losing-streak cooldown, weekly and monthly limits; counts realized P&L only, so mark-to-market equity is added"),
 (CTS, "dual-axis-skill-reviewer", "CUT", "", "L", "none", "", "", "Meta tooling"),
 (CTS, "earnings-calendar", "KEEP", "event calendar", "D*", "FMP key required (/stable endpoints)", "earnings-trade-analyzer", "if the calendar is archived",
  "Feeds the event-blackout rule; needs a second provider as fallback"),
 (CTS, "earnings-trade-analyzer", "CANDIDATE", "PEAD sub-bot", "D*", "FMP key required", "pead-screener", "with paid point-in-time data",
  "Five-factor post-earnings score; one earnings-event module with pead-screener"),
 (CTS, "economic-calendar-fetcher", "KEEP", "event calendar", "D*", "FMP key required", "fxmacrodata-calendar", "if the calendar is archived",
  "Event blackout; FRED release dates added as a free fallback"),
 (CTS, "edge-candidate-agent", "CUT", "", "D", "FMP optional", "", "", "Idea-generation pipeline"),
 (CTS, "edge-concept-synthesizer", "CUT", "", "D", "none", "", "", "Idea-generation pipeline"),
 (CTS, "edge-hint-extractor", "CUT", "", "L", "none", "", "", "Idea-generation pipeline with optional LLM ideation"),
 (CTS, "edge-pipeline-orchestrator", "CUT", "", "D", "none", "", "", "Idea-generation pipeline"),
 (CTS, "edge-signal-aggregator", "CUT", "", "D", "none", "", "", "Aggregates cut skills"),
 (CTS, "edge-strategy-designer", "CUT", "", "D", "none", "", "", "Idea-generation pipeline"),
 (CTS, "edge-strategy-reviewer", "KEEP", "research checklist", "D", "none", "backtest-expert", "n/a",
  "Eight deterministic criteria and a bias checklist applied to a strategy spec; becomes the pre-registration lint"),
 (CTS, "exposure-coach", "OPTIONAL", "regime features", "D", "none; combines other outputs", "stanley-druckenmiller-investment", "yes",
  "Hard-coded weights; enabled only if it improves out-of-sample results"),
 (CTS, "finviz-screener", "CUT", "", "D", "FINVIZ", "", "", "Builds FinViz URLs and opens a browser"),
 (CTS, "ftd-detector", "OPTIONAL", "regime features", "D*", "FMP key required (index OHLCV)", "ibd-distribution-day-monitor", "yes",
  "Not in your lists: state machine on index OHLCV, cheap to test on any EOD source"),
 (CTS, "futures-position-sizer", "MERGE", "position sizing", "D", "contract-spec table in code", "position-sizer", "n/a",
  "Not in your lists: contract multiplier and tick table; needed for futures and index CFDs"),
 (CTS, "fxmacrodata-calendar", "CUT", "", "D*", "FXMacroData key", "economic-calendar-fetcher", "", "Beta; small vendor; can return as a provider behind the calendar interface"),
 (CTS, "ibd-distribution-day-monitor", "OPTIONAL", "regime features", "D*", "FMP key required (QQQ/SPY OHLCV)", "ftd-detector", "yes",
  "Not in your lists: deterministic rule on index OHLCV"),
 (CTS, "institutional-flow-tracker", "CUT", "", "D*", "FMP key required", "edgar13f.py", "", "Same 13F data through a paid aggregator; edgar13f reads the primary source"),
 (CTS, "kanchi-dividend-review-monitor", "CUT", "", "D", "FMP", "", "", "Per brief"),
 (CTS, "kanchi-dividend-sop", "CUT", "", "L", "FMP, web search", "", "", "Per brief"),
 (CTS, "kanchi-dividend-us-tax-accounting", "CUT", "", "D", "none", "trader-tax", "", "Per brief"),
 (CTS, "macro-regime-detector", "OPTIONAL", "regime features", "D*", "yfinance required; FMP optional", "exposure-coach", "yes",
  "Cross-asset ratios from ETF closes; rerouted through the data layer"),
 (CTS, "manifoldbt-backtester", "CUT", "", "D", "external Rust engine", "", "", "Beta; per brief"),
 (CTS, "market-breadth-analyzer", "OPTIONAL", "regime features", "D*", "author CSV on GitHub Pages (MIT repo)", "uptrend-analyzer", "if CSV history is archived",
  "Own breadth computation added as fallback"),
 (CTS, "market-environment-analysis", "CUT", "", "L", "web search", "", "no", "Narrative"),
 (CTS, "market-news-analyst", "CUT", "", "L", "web search", "trader-news", "no", "Narrative; no code"),
 (CTS, "market-top-detector", "CUT", "", "L", "FMP, author CSV, web-searched inputs", "ftd-detector, ibd-distribution-day-monitor", "no",
  "Composite of other regime inputs plus web-searched values"),
 (CTS, "mt5-robot-tester", "CUT", "", "D", "local MT5", "", "", "Beta; per brief"),
 (CTS, "news-reaction-failure-analyzer", "CUT", "", "L", "FMP, web search", "", "no", "Needs LLM-curated news judgement"),
 (CTS, "options-strategy-advisor", "KEEP", "options math (black_scholes.py)", "D", "none for pricing", "", "n/a",
  "Pricer and Greeks match an independent implementation to 1e-14; prerequisite for deep hedging"),
 (CTS, "pair-trade-screener", "CANDIDATE", "pairs sub-bot", "D*", "FMP key required", "", "yes",
  "Fix before use: ADF p-values on estimated residuals, no multiple-testing control, full-sample hedge ratio, silent exceptions"),
 (CTS, "parabolic-short-trade-planner", "CUT", "", "D*", "FMP, Alpaca", "", "", "Per brief"),
 (CTS, "pead-screener", "CANDIDATE", "PEAD sub-bot", "D*", "FMP key required", "earnings-trade-analyzer", "with paid point-in-time data",
  "Converted only if a point-in-time backtest passes"),
 (CTS, "portfolio-manager", "CUT", "", "L", "Alpaca MCP, web search", "trader-rebalance", "no", "Per brief"),
 (CTS, "position-sizer", "MERGE", "position sizing", "D", "none", "trader-budget, futures-position-sizer", "n/a",
  "Fixed-fractional, ATR and Kelly; Kelly is a point estimate with no uncertainty haircut and only optional caps, so it is rewritten"),
 (CTS, "pre-trade-discipline-gate", "MERGE", "risk gate", "D", "none", "trader-risk, drawdown-circuit-breaker", "n/a, runs inside replay",
  "Blocks planless, oversized, revenge and regime-blocked entries"),
 (CTS, "residual-edge-analyzer", "KEEP", "attribution (method)", "D", "none", "", "n/a",
  "OLS, Newey-West and rolling stability written as pure-Python linear algebra; re-implemented on statsmodels; beta"),
 (CTS, "scenario-analyzer", "CUT", "", "L", "web search", "", "no", "Narrative; no code"),
 (CTS, "sector-analyst", "CUT", "", "L", "chart images, author CSV", "uptrend-analyzer", "no", "Reads chart images"),
 (CTS, "signal-postmortem", "MERGE", "journal and outcome store", "D*", "FMP optional (prices)", "trader-memory-core", "n/a",
  "Outcome labelling of past signals; becomes the D+1 labeller of the feedback loop"),
 (CTS, "skill-designer", "CUT", "", "L", "none", "", "", "Meta tooling"),
 (CTS, "skill-idea-miner", "CUT", "", "L", "none", "", "", "Meta tooling"),
 (CTS, "skill-integration-tester", "CUT", "", "D", "none", "", "", "Meta tooling"),
 (CTS, "stanley-druckenmiller-investment", "CUT", "", "D", "outputs of 8 other skills", "exposure-coach", "no", "Narrative synthesis of cut skills"),
 (CTS, "stockbee-20pct-study", "CUT", "", "D*", "FMP key required", "", "", "Beta; per brief"),
 (CTS, "stockbee-episodic-pivot-analyzer", "CUT", "", "D*", "catalyst file, FMP", "", "", "Beta; per brief"),
 (CTS, "stockbee-exhaustion-hammer-screener", "CUT", "", "D*", "FMP key required", "", "", "Beta; per brief"),
 (CTS, "stockbee-momentum-burst-screener", "CUT", "", "D*", "FMP key required", "", "", "Beta; per brief"),
 (CTS, "stockbee-setup-fluency-trainer", "CUT", "", "D*", "FMP optional", "", "", "Beta; per brief"),
 (CTS, "strategy-pivot-designer", "CUT", "", "D", "none", "", "", "Not in your lists: generates new variants when backtests stall, which invites overfitting"),
 (CTS, "technical-analyst", "CUT", "", "L", "chart images", "", "no", "Reads chart images"),
 (CTS, "theme-detector", "CUT", "", "D*", "FINVIZ Elite, FMP, yfinance, curl_cffi", "", "needs point-in-time data", "Cut pending backtest"),
 (CTS, "trade-hypothesis-ideator", "CUT", "", "L", "none", "", "no", "Not in your lists: LLM ideation"),
 (CTS, "trade-performance-coach", "CUT", "", "L", "none", "weekly-performance-digest", "no", "Not in your lists: beta, LLM coaching"),
 (CTS, "trader-memory-core", "MERGE", "journal and outcome store", "D", "local files; FMP optional", "signal-postmortem", "n/a",
  "Thesis lifecycle state machine and JSON schema; storage moves to the append-only event log"),
 (CTS, "trading-skills-navigator", "CUT", "", "D", "none", "", "", "Meta tooling"),
 (CTS, "uptrend-analyzer", "OPTIONAL", "regime features", "D*", "author CSV (repo has no LICENSE file)", "market-breadth-analyzer", "if CSV history is archived",
  "Data licence unclear; own computation as fallback"),
 (CTS, "us-market-bubble-detector", "CUT", "", "L", "web-searched inputs", "", "no", "Narrative"),
 (CTS, "us-stock-analysis", "CUT", "", "L", "web search", "trader-analyst", "no", "Narrative; no code"),
 (CTS, "us-undervalued-growth-screener", "CUT", "", "D*", "FMP, SEC, company IR", "", "", "Beta; 14,635 lines; per brief"),
 (CTS, "value-dividend-screener", "CUT", "", "D*", "FMP required, FINVIZ", "", "", "Per brief"),
 (CTS, "vcp-screener", "CUT", "", "D*", "FMP key required", "", "needs survivorship-free universe", "Cut pending backtest"),
 (CTS, "weekly-performance-digest", "KEEP", "journal reports", "D", "none", "trade-performance-coach", "n/a",
  "Win rate, expectancy, profit factor, R-multiple, MAE/MFE from the journal; confidence intervals added"),
]

def main() -> None:
    audit = {(r["repo"], r["skill"]): r for r in csv.DictReader(open(ROOT / "docs/phase0/skill_audit_raw.csv"))}
    passed = {}
    for ln in open(ROOT / "docs/phase0/cts_test_summary.txt"):
        k, v = ln.rstrip("\n").split("\t")
        passed[k] = v.split(" passed")[0].split(", ")[-1] if " passed" in v else "?"
    missing = set(audit) - {(d[0], d[1]) for d in D}
    extra = {(d[0], d[1]) for d in D} - set(audit)
    assert not missing and not extra, (missing, extra)
    assert len(D) == len({(d[0], d[1]) for d in D})
    cols = ["repo", "skill", "decision", "target", "det", "data", "duplicates", "backtestable", "reason", "prod_loc", "test_loc", "tests_passed_here", "third_party"]
    rows = []
    for d in D:
        a = audit[(d[0], d[1])]
        tp = passed.get(d[1], "") if d[0] == CTS else a["n_tests"]
        rows.append(dict(zip(cols, list(d) + [int(a["prod_loc"]), int(a["test_loc"]), tp, a["third_party"]])))
    with open(ROOT / "docs/phase0/skill_decisions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n"); w.writeheader(); w.writerows(rows)
    for repo in (TS, CTS, DTS):
        agg = defaultdict(lambda: [0, 0, 0])
        for r in rows:
            if r["repo"] == repo:
                a = agg[r["decision"]]; a[0] += 1; a[1] += r["prod_loc"]; a[2] += r["test_loc"]
        tot = [sum(v[i] for v in agg.values()) for i in range(3)]
        print(repo, {k: tuple(v) for k, v in sorted(agg.items())}, "total", tuple(tot))
        cut = agg["CUT"]
        print(f"  cut share of code lines: {cut[1]/tot[1]:.1%}; skills cut {cut[0]}/{tot[0]}")
    def deps(pred):
        s = set()
        for r in rows:
            if r["repo"] == CTS and pred(r):
                s |= set(filter(None, r["third_party"].split(";")))
        return s
    allp, kept = deps(lambda r: True), deps(lambda r: r["decision"] != "CUT")
    print("third-party imports, all skills:", sorted(allp))
    print("still imported by non-cut skills:", sorted(kept))
    print("dropped with the cut list:", sorted(allp - kept))
    det = defaultdict(int)
    for r in rows:
        if r["repo"] == CTS: det[r["det"]] += 1
    print("claude-trading-skills determinism classes:", dict(det))

if __name__ == "__main__":
    main()
