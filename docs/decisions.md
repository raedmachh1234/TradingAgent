# Owner decisions log

Every decision the owner made, and where it is applied. Newest first.

## 2026-11-10: Phase 0 approved, five decisions for Phase 1

| # | Decision | How it is applied | Where |
| --- | --- | --- | --- |
| 1 | Work in `C:\Users\PCS\Desktop\TradingBot-Project`; git with a .gitignore for `.env`, `data/`, `models/`, `*.key`; commit at the end of every phase; never push; no secrets | One commit per phase; the ignore rules plus a test that scans for secrets. The code was built, tested and committed in the cloud sandbox, because the local Linux workspace on the owner's computer could not start (too little free disk space). The files were then copied into the folder; the remote file tools may not write inside `.git`, so the history is delivered as `data/quantbot-history.bundle`, with the commands to attach it in `data/ATTACH_GIT_HISTORY.txt` | `.gitignore`, `tests/test_no_secrets.py` |
| 2 | Keep/merge/cut table approved, including the additions; cut skills archived, not deleted | 59 cut skills archived unchanged as one zip each, with a one-line reason; the 37 survivors kept as pristine sources until converted | `_archive/INDEX.md`, `third_party/sources/` |
| 3 | A legal path to live trading from the country of residence, including the no-TIN case; criteria and questionnaire only if web search is unavailable; paper or demo adapter until a live account exists | Country not given (answer: "skip for now") and web search disabled, so criteria, tax-ID guidance and a questionnaire only; no broker chosen. Phase 1 runs only against the paper broker | `docs/broker_selection.md`, `src/quantbot/brokers/paper.py` |
| 4 | Own orchestrator with thin broker adapters, Python 3.11; NautilusTrader only if the broker is Interactive Brokers | `requires-python >= 3.11`; tests pass on 3.11.18 and 3.13.18; no framework dependency | `pyproject.toml` |
| 5 | A live ProOrder script runs outside the gate, so it is M3: only after M3 promotion, hard limits in the script, a manual-stop runbook and a daily read-only reconciliation import; M1 on ProRealTime is a ticket placed by hand | Adapters declare `gate_controlled`; a live-script adapter is observe-and-reconcile only; deploying one needs an effective signed M3 grant; the ProRealTime ticket adapter supports M0 and M1 only; runbook drafted. The script generator and the reconciliation import are broker-phase work | `brokers/base.py`, `execution/policy.py`, `tests/test_policy.py`, `docs/runbooks/proorder_manual_stop.md` |

**Open inputs.** Capital, markets, hardware, budget and trade history are configuration parameters with
documented defaults; paper capital is 10,000 in the account currency. Defaults live in
`src/quantbot/default_config.yaml`, and you override them in `config/quantbot.yaml`.

**Trade history.** The file format is in `docs/trade_history_format.md`. I will ask for the file again at the
start of the ML phase.

**Approval channel.** You stated no preference. Phase 0 proposed Telegram for the push with Approve and Reject
buttons, plus the CLI for edits and administration, and you did not object. Both are built.

## 2026-11-10: Phase 0 brief

The original brief: gated stages backtest, paper, shadow, small live; four execution modes; the
strategy never touches the broker; the bot can never raise its own autonomy. See the Phase 0 report.
