# quantbot

Orchestrator for multiple trading sub-bots with one execution gate (observe, human-confirm,
auto-with-limits, full-auto). **Status: Phase 0 complete (audit, research, plan). No trading code yet.**

Nothing in this repository is financial advice, and nothing here has been shown to be profitable.

## Phase 0: what is here

| Path | What it is |
| --- | --- |
| `THIRD_PARTY.md` | Base repositories, their dependencies, candidate libraries, models: licence and last commit as verified on 2026-11-10 |
| `docs/phase0/skill_audit_raw.csv` | Static audit of all 96 skills: lines of code, tests, third-party imports, hosts, environment keys |
| `docs/phase0/skill_decisions.csv` | Keep / merge / candidate / optional / cut for every skill, with target module and reason |
| `docs/phase0/cts_test_summary.txt` | pytest result per test group of claude-trading-skills (74 skill groups pass; 1 environment-specific failure in repo tooling) |
| `docs/phase0/cts_venv_licenses.json` | Licence metadata of the packages installed by the claude-trading-skills lockfile |
| `docs/phase0/repo_meta_raw.tsv` | HEAD commit date and licence header for 52 repositories |
| `docs/phase0/smoke_results.txt` | Output of the library smoke tests |
| `tests/fixtures/ebook_solutions.json` | 57 values from "Quantitative Finance From Scratch", re-computed and compared with the book |
| `tools/` | The scripts that produced all of the above |

## One-command reproduction

```bash
bash tools/phase0_reproduce.sh /path/to/empty/work/dir
```

Clones the three base repositories at the audited commits, runs their test suites, and regenerates
the audit, the decision table and the e-book fixtures. The claude-trading-skills matrix takes about
10 minutes; `SKIP_CTS_TESTS=1` skips it.

Library smoke tests (two environments, because PFHedge 0.23.0 requires numpy < 2):

```bash
uv venv --python 3.11 .venv-smoke && uv pip install --python .venv-smoke/bin/python \
  skfolio pyportfolioopt riskfolio-lib arch statsmodels py_vollib QuantLib hftbacktest \
  nautilus_trader vectorbt backtrader bt exchange_calendars duckdb pyarrow 'plotly<6'
.venv-smoke/bin/python tools/smoke_libs.py

uv venv --python 3.11 .venv-ml && uv pip install --python .venv-ml/bin/python torch pfhedge purgedcv pandas
.venv-ml/bin/python tools/smoke_ml_libs.py
```

## What is still weak after Phase 0

- Web search was not available, so the survey of existing bots starts from prior knowledge and may miss recent projects.
- Library checks are smoke tests on synthetic data. No framework was tested on real market data or on the owner's trades.
- Kronos, TimesFM, Chronos-2, Qlib and ABIDES were not run (no GPU here; deferred to the phases that use them).
- Finnhub's terms, Massive's pricing, IG country eligibility and API access on a ProRealTime-sponsored IG account are unverified.
- Lines of code and dependencies removed are projections from the cut list, not a finished conversion.
