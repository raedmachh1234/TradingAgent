# THIRD_PARTY

Status: Phase 0 audit verified 2026-11-10; section 0 added in Phase 1.
"Last commit" is the committer date of the default-branch HEAD, read with a blobless depth-1 clone
(`tools/repo_meta.sh`); the raw output is in `docs/phase0/repo_meta_raw.tsv`.
"Licence" is what the LICENSE file in the repository says, not what a README or badge claims.

Rules for this file

- Every file harvested from a base repository keeps its copyright line and is listed here with its source path and commit.
- No code is copied from a source without a licence file (all rights reserved by default).
- GPL, AGPL and Commons-Clause code is never imported into this codebase. Where such a tool is useful it runs as a separate process.
- Model weights and datasets have their own licences; they are listed separately from code.

## 0. Runtime dependencies of quantbot itself (Phase 1)

Versions as installed and tested on 2026-11-10 (Python 3.11.18 and 3.13.18). Licences from package metadata.

| Package | Version tested | Licence | Used for |
| --- | --- | --- | --- |
| numpy | 2.4.6 | BSD-3-Clause (bundled parts 0BSD, MIT, Zlib, CC0-1.0) | synthetic data, arrays |
| pandas | 3.1.1 | BSD-3-Clause | data frames |
| pyarrow | 26.0.1 | Apache-2.0 | Parquet files |
| duckdb | 2.0.0 | MIT | catalog and queries over Parquet |
| PyYAML | 6.0.3 | MIT | configuration, grants |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | Ed25519 operator signatures |
| tzdata | 2026.6 | Apache-2.0 | time zones on Windows |
| pytest (dev only) | 9.2.0 | MIT | tests |

**Harvest status after Phase 1.** No code was copied from the base repositories. Phase 1 re-implements two designs
from them, with credit: the risk verdict bound to one exact order by its fingerprint (trader-skill, `trader-risk`
and `trader-broker`), and exits treated more leniently than entries so that getting out stays possible
(day-trader-skill, `trader-risk`). The 59 cut skills are archived unchanged in `_archive/`, the 37 survivors in
`third_party/sources/`, each with its upstream LICENSE.

## 1. Base repositories (harvested by copying, with attribution)

| Repository | Commit | Date | Licence | Copyright | Use |
| --- | --- | --- | --- | --- | --- |
| Jakeschincariol/trader-skill | 5189e79 | 2026-10-14 | MIT | (c) 2026 Jake Schincariol | risk rules, ticket schema, sizing constraints, news and SEC readers, edgar13f.py, NYSE calendar table, rebalancer, screener engine |
| tradermonty/claude-trading-skills | 163ceb48 | 2026-11-08 | MIT (LICENSE added 2026-04-12) | (c) 2026 TraderMonty | 22 of 74 skills, see docs/phase0/skill_decisions.csv |
| Jakeschincariol/day-trader-skill | 3d0f4ef | 2026-10-20 | MIT | (c) 2026 Jake Schincariol | risk gate v2 rules, replay method, ORB candidate |

Data repositories referenced by claude-trading-skills (not code we ship):

| Repository | Last commit | Licence | Note |
| --- | --- | --- | --- |
| tradermonty/market-breadth-analysis | 2026-11-06 | MIT | breadth CSV on GitHub Pages; one maintainer |
| tradermonty/uptrend-dashboard | 2026-11-10 | no LICENSE file | data rights unclear; treat as optional, compute our own breadth as fallback |

## 2. Dependencies of the base repositories

trader-skill and day-trader-skill: Python standard library only. Optional external binary: `pdftotext` (trader-pelosi, cut).

claude-trading-skills (versions from its uv.lock as installed here on Python 3.13):

| Package | Version | Licence | Still needed after the cut list |
| --- | --- | --- | --- |
| numpy | 2.4.3 | BSD-3-Clause | yes |
| pandas | 3.0.3 | BSD-3-Clause | yes |
| scipy | 1.17.1 | BSD-3-Clause | yes |
| statsmodels | 0.14.6 | BSD-3-Clause | yes |
| requests | 2.34.2 | Apache-2.0 | yes |
| PyYAML | 6.0.3 | MIT | yes |
| jsonschema | 4.26.0 | MIT | yes |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | yes |
| pyarrow | 26.0.0 | Apache-2.0 | yes (data layer) |
| pandas-market-calendars | 5.2.2 (pinned extra) | MIT | replaced by one calendar module |
| yfinance | 1.7.0 | Apache-2.0 (code); Yahoo terms apply to data | prototyping provider only, never live |
| beautifulsoup4 | 4.15.0 | MIT | no |
| lxml | 6.1.3 | BSD-3-Clause | no |
| opencv-python-headless | 5.0.0.93 | Apache-2.0 | no |
| pillow | 13.0.0 | MIT-CMU | no |
| curl_cffi | 0.16.3 | MIT | no |
| finvizfinance | not installed by the lockfile | MIT (unverified) | no |
| manifoldbt | not installed by the lockfile | unverified | no |

## 3. Candidate dependencies for this build

"Smoke" = installed on Python 3.11.18 and one minimal example run with `tools/smoke_libs.py` or `tools/smoke_ml_libs.py` on 2026-11-10.
Output is saved in `docs/phase0/smoke_results.txt`.

| Library | Last commit | Licence | Smoke | Decision |
| --- | --- | --- | --- | --- |
| statsmodels/statsmodels | 2026-11-10 | BSD-3-Clause | 0.15.0 OK | adopt (ADF, Engle-Granger, Johansen, HAC) |
| bashtage/arch | 2026-11-09 | NCSA | 8.0.0 OK | adopt (GARCH, bootstrap) |
| skfolio/skfolio | 2026-11-08 | BSD-3-Clause | 1.12.8 OK | adopt as the one portfolio library (provisional; bake-off in Phase 4) |
| robertmartin8/PyPortfolioOpt | 2026-07-07 | MIT | 1.6.0 OK | comparison only |
| dcajasn/Riskfolio-Lib | 2026-11-04 | BSD-3-Clause | 7.4.1 OK | comparison only |
| vollib/py_vollib | 2026-04-30 | MIT | 1.0.12 OK | test oracle for our Black-Scholes |
| lballabio/QuantLib | 2026-11-10 | QuantLib licence (BSD-style) | 1.44 OK | test oracle; not a runtime dependency |
| domokane/FinancePy | 2026-11-06 | GPL-3.0 | not installed | reject (GPL) |
| eslazarev/purged-cross-validation (purgedcv) | 2026-11-08 | MIT | 0.1.12 OK, with a caveat | adopt behind our own tests; alpha; set purge_horizon to at least one bar |
| hpicsk/afml-python | 2025-10-04 | no LICENSE file | not installed | reject (no licence) |
| pfnet-research/pfhedge | 2024-08-30 | MIT | 0.23.0 OK on torch 2.15.0 CPU, in its own environment | adopt, pinned; unmaintained since 2024. It requires numpy >=1.26,<2.0, which conflicts with pyarrow 26 (NumPy 2 only), so it runs in a separate environment or is vendored with the pin lifted |
| nkaz001/hftbacktest | 2025-12-23 | MIT | 2.4.2 import OK | adopt for market-making simulation |
| jpmorganchase/abides-jpmc-public | 2023-12-13 | BSD-3-Clause | not installed | fallback only; stale |
| abides-sim/abides | 2020-11-19 | BSD-3-Clause | not installed | reject (superseded) |
| microsoft/qlib | 2026-10-08 | MIT | not installed | optional, only for the Kronos fine-tune example |
| robcarver17/pysystemtrade | 2026-11-02 | GPL-3.0 | not installed | read as reference; no code copied |
| nautechsystems/nautilus_trader | 2026-11-10 | LGPL-3.0 | 1.221.0 OK on 3.11; 1.231.0 needs Python 3.12+ | candidate execution engine if the broker is IB or crypto; no IG adapter |
| QuantConnect/Lean | 2026-11-09 | Apache-2.0 | not installed (C#, Docker) | not adopted |
| freqtrade/freqtrade | 2026-11-09 | GPL-3.0 | not installed | separate process only, crypto only |
| polakowo/vectorbt | 2026-11-08 | Apache-2.0 with Commons Clause | 1.0.0 OK with plotly < 6; import fails on plotly 7.1.0 | research sweeps only, optional |
| mementum/backtrader | 2023-04-19 | GPL-3.0 | 1.9.78.123 OK | reject (GPL, unmaintained) |
| pmorissette/bt | 2026-11-08 | MIT | 1.4.1 OK | optional |
| ig-python/trading-ig | 2026-09-02 | BSD-3-Clause | not installed | candidate for the IG adapter |
| ib-api-reloaded/ib_async | 2025-12-06 | BSD-2-Clause | not installed | candidate for an IB adapter |
| exchange_calendars | not checked by git | Apache-2.0 (package metadata) | 4.13.2 OK | candidate calendar library |
| duckdb | not checked by git | MIT (package metadata) | 2.0.0 OK | adopt (data layer) |

## 4. Models and weights

| Model | Code licence | Weights licence | Verified | Decision |
| --- | --- | --- | --- | --- |
| Kronos (shiyu-coder/Kronos, last commit 2026-04-13) | MIT | MIT (NeoQuasar/Kronos-small model card) | yes | evaluate as a feature source; context 512 for small and base, Kronos-large not released |
| TimesFM (google-research/timesfm, 2026-09-29) | Apache-2.0 | Apache-2.0 (google/timesfm-2.5-200m-pytorch) | yes | baseline |
| Chronos-2 (amazon-science/chronos-forecasting, 2026-10-05) | Apache-2.0 | Apache-2.0 (amazon/chronos-2) | yes | baseline |
| Moirai (SalesforceAIResearch/uni2ts, 2026-06-02) | Apache-2.0 | cc-by-nc-4.0 (Salesforce/moirai-2.0-R-small) | yes | research comparison only; non-commercial weights never feed a live decision |
| FinGPT (AI4Finance-Foundation/FinGPT, 2026-10-25) | MIT | depends on the base LLM | partly | text classification only, if at all |
| FinLoRA (Open-Finance-Lab/FinLoRA, 2026-03-17) | OpenMDW-1.0 | depends on the base LLM | partly | optional |

## 5. Data providers

See the report, section "Verified resource table", for terms and limits as read on 2026-11-10.
Every dataset written by the data layer records provider, retrieval time and a terms tag.
