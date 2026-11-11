# quantbot

An orchestrator for trading sub-bots with one execution gate and four modes: observe (M0), human-confirm (M1),
auto-with-limits (M2) and full-auto (M3).

**Status: Phase 2 complete.** Phase 1 built the architecture, event bus, strategy registry, cached data layer and
execution gate, running against a paper broker on synthetic data. Phase 2 added the book foundation: the 17
chapters of "Quantitative Finance From Scratch" as tested modules, each flagging data that breaks its assumptions,
and a comparison of three portfolio libraries. There are no live credentials anywhere. Every strategy defaults
to M1.

Nothing in this repository is financial advice. No strategy here has been shown to be profitable; the two built-in
sub-bots are plumbing aids, not trading ideas.

## Quick start

Requires Python 3.11 or newer. On Windows:

```
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,allocators]"
python -m quantbot demo
python -m quantbot demo foundation
python -m pytest
```

On Linux or macOS, use `python3 -m venv .venv` and `source .venv/bin/activate` instead. The `allocators` extra
installs skfolio, the adopted portfolio library. Re-running the library comparison also needs the `bakeoff` extra
(PyPortfolioOpt and Riskfolio-Lib); Riskfolio-Lib pulls in vectorbt, which is Apache 2.0 with Commons Clause.

| Command | What it does |
| --- | --- |
| `python -m quantbot demo` | Phase 1 demo: the execution gate, offline, about 2 seconds; exits 0 if all its checks pass |
| `python -m quantbot demo foundation` | Phase 2 demo: the book foundation, offline, about 10 seconds; exits 0 if all its checks pass |
| `python -m quantbot bakeoff` | Re-runs the portfolio-library comparison and rewrites `docs/phase2/allocator_bakeoff.*` |
| `python -m pytest` | 372 tests, about 30 seconds |
| `python -m quantbot paper` | Interactive paper session: each proposal is shown and you approve, reject or edit it |
| `python -m quantbot history check FILE` | Checks your trade-history CSV against [the import format](docs/trade_history_format.md) |
| `python -m quantbot log verify FILE` | Verifies an audit log's hash chain |
| `python -m quantbot keys init` | Creates your operator key pair; the private key is stored outside the project |
| `python -m quantbot autonomy sign` | Signs `config/autonomy.yaml`, the only way to allow a strategy above M1 |
| `python -m quantbot config` | Prints the effective configuration |

## How it fits together

```
providers (synthetic, CSV; failover in order) -> DataService -> cache: Parquet files + DuckDB catalog
                                                                 (provider, retrieval time, terms per dataset)
replay or live feed -> Orchestrator -> sub-bots: read-only context in, Decision out
                                     -> ExecutionGate
                                          risk gate      always on; signs a verdict bound to one exact order
                                          PolicyEngine   strictest rule wins; signed grants cap; downgrades lower
                                          ApprovalService
                                             M0 observe | M1 human (CLI, Telegram) | M2 auto with limits | M3 auto
                                             expiry, bounded edits, revalidation, re-proposal
                                     -> Executor: the only holder of a broker adapter -> PaperBroker
                                     -> books: actual (broker fills) and shadow (every decision filled)
monitors (kill switch, loss, drawdown, data, reconciliation, errors, slippage, calibration) -> M1 or halt
event bus: every event audited, then delivered to observers -> append-only, hash-chained audit log
```

Two design points carry most of the safety:

- **Decisions do not depend on the mode.** Sub-bots read their positions from the shadow book, which fills every
  decision whatever happens to it afterwards. Replaying the same data in M0, M1, M2 and M3 gives identical
  decisions; only what happens after the gate differs. The shadow book also gives the counterfactual outcome of
  every vetoed or expired proposal.
- **The event bus cannot trade.** Decisions reach the gate and fills reach the books by direct calls inside the
  orchestrator. The bus audits events and informs observers, so a component that can publish an event, such as a
  future news reader, cannot create an order.

## Guarantees and the tests that check them

| Guarantee | Tests |
| --- | --- |
| Strategy code cannot import a broker, the gate or the network | `test_architecture.py` |
| Nothing reaches the broker without a risk pass and revalidation | `test_state_machine.py`, `test_risk_gate.py` |
| The executor refuses forged, stale or mismatched risk verdicts | `test_risk_gate.py` |
| The bot cannot raise its own mode: no grant means M1; grants are Ed25519-signed by you, cool off and expire; lifting a downgrade needs a signed command | `test_policy.py`, `test_downgrades.py`, `test_config.py` |
| Untrusted text cannot approve: only authenticated channels count; Telegram text messages are ignored | `test_untrusted_text.py` |
| Proposals expire; approved orders are revalidated for price drift, data and risk, then cancelled and re-proposed if needed | `test_approval.py` |
| Edits are bounded: size down only, stop closer only, exits by size only | `test_approval.py` |
| Every downgrade trigger lowers the mode (M1 or halt) and only a signed command lifts it | `test_downgrades.py` |
| No duplicate orders: idempotent client order ids at the executor and the broker | `test_duplicates.py` |
| Identical decisions in every mode on replay | `test_replay_modes.py`, the demo |
| Kill switch, max order rate, max position, daily loss limit and reconciliation are on in every mode | `test_risk_gate.py`, `test_downgrades.py` |
| The audit log is append-only and tamper-evident | `test_core.py` |
| No secrets in the repository | `test_no_secrets.py` |
| The book foundation only computes: it cannot reach a broker, the gate, a data store or the network | `test_architecture.py` |
| Each foundation check fires on data that breaks its assumption and stays quiet otherwise; each method beats its baseline | `test_foundation_checks.py`, `test_foundation_baselines.py`, the foundation demo |

## The book foundation (Phase 2)

Each chapter of "Quantitative Finance From Scratch" is a module in `src/quantbot/foundation/`. Every module states
its assumption, offers `check(...)` that flags data breaking it (at the 1% level), and `beat_baseline(seed)` that
measures its method against the naive baseline it replaces, on synthetic data with a known truth. The book's 57
worked answers are re-computed through these modules (`tests/test_foundation_fixtures.py`). Only the book's
formulas are used; none of its code is copied.

| Ch | Module | Assumption checked (test) | Baseline beaten |
| --- | --- | --- | --- |
| 1 | `returns` | none: exact arithmetic | adding simple returns |
| 2 | `timevalue` | none: a known rate | the undiscounted sum |
| 3 | `expectation` | edge distinguishable from zero (99% interval); independent results | picking the highest win rate |
| 4 | `randomwalk` | uncorrelated returns (robust Box-Pierce, variance ratio); independent step sizes (McLeod-Li) | forecasting a reversal to the recent average |
| 5 | `scaling` | uncorrelated returns (variance ratio) | linear scaling; plain sqrt rule under momentum |
| 6 | `normal` | normal returns (Jarque-Bera) | counting past losses |
| 7 | `volatility` | constant volatility (McLeod-Li) | the long-run average variance |
| 8 | `sharpe` | uncorrelated (robust Box-Pierce) and normal returns | sqrt(252) annualisation |
| 9 | `drag` | normal returns | the average return as the growth rate |
| 10 | `correlation` | normal returns; dependence beyond correlation (rank correlation of move sizes) | Pearson on fat tails |
| 11 | `diversification` | stable correlation on the worst days (against normal simulations) | the average of the volatilities |
| 12 | `minvariance` | covariance known well enough (bootstrap of the weights) | equal weights |
| 13 | `capm` | stable beta (first half against second half) | hedging one-for-one |
| 14 | `kelly` | edge known (lower bound of the fraction); independent bets (runs test) | full Kelly on an estimated edge |
| 15 | `montecarlo` | normal, unclustered shocks | plain Monte Carlo |
| 16 | `tails` | normal tails (Jarque-Bera, count of 4-sd moves) | the normal tail probability |
| 17 | `var` | right exception rate (Kupiec); independent exceptions (Christoffersen) | normal VaR from a rolling sd |

The checks separate direction from size: volatility clustering alone does not make returns look predictable,
because the autocorrelation tests are the heteroskedasticity-robust versions.

**Portfolio library.** skfolio, PyPortfolioOpt and Riskfolio-Lib solved the same minimum-variance and maximum-Sharpe
problems; all three matched the reference solver to within 1e-4. skfolio was chosen by the rule fixed before the
run: it is the only one with walk-forward and purged cross-validation and a scikit-learn API, and it pulls in the
fewest packages (18, against 24 and 93). Details: [docs/phase2/allocator_bakeoff.md](docs/phase2/allocator_bakeoff.md).

## Configuration

Defaults are in [src/quantbot/default_config.yaml](src/quantbot/default_config.yaml). Override them in
`config/quantbot.yaml` (start from [config/quantbot.example.yaml](config/quantbot.example.yaml)); a misspelt key is
an error, not a silent default. Still-open owner inputs are parameters: account currency and paper capital
(10,000), instruments and bar frequency, hardware, data budget, trade-history path.

Secrets go in `.env` (see [.env.example](.env.example)), which git ignores. Phase 1 needs none.

## Allowing a strategy above M1

Only you can, and only with your private key:

1. `python -m quantbot keys init` creates the key pair. The private key goes to `%USERPROFILE%\.quantbot\`, outside
   this folder.
2. Add a grant to `config/autonomy.yaml`, for example `{strategy: ma_demo, max_mode: M2}`.
3. `python -m quantbot autonomy sign`. The grant takes effect after its cooling-off period: 24 hours for M2 and
   72 hours for M3, counted from when the bot first sees it.

Releasing the kill switch and clearing a downgrade also require a command signed with that key. Halting needs no
key: create the file `data/KILL`.

## Layout

| Path | What it is |
| --- | --- |
| `src/quantbot/core/` | types, clock, config, event bus, audit log |
| `src/quantbot/data/` | providers, cache, quality checks, replay feed, trade-history validator |
| `src/quantbot/strategy/`, `strategies/` | strategy interface, registry, two plumbing sub-bots |
| `src/quantbot/risk/` | risk gate, kill switch, downgrade monitors |
| `src/quantbot/execution/` | policy engine, signed grants, approval service, proposals, executor, channels |
| `src/quantbot/brokers/` | adapter interface with declared modes, paper broker |
| `src/quantbot/portfolio/` | actual and shadow books, capital allocator |
| `src/quantbot/foundation/` | the 17 book chapters, their assumption checks and baselines, the library comparison |
| `config/` | example settings and the empty, unsigned autonomy file |
| `docs/` | decisions log, broker criteria, trade-history format, ProOrder stop runbook, phase outputs |
| `_archive/` | the 59 cut skills, unchanged, with the reason each was cut |
| `third_party/` | pristine sources of the 37 surviving skills and their licences |
| `tools/` | Phase 0 audit scripts |

## What is still weak after Phase 2

- Every foundation result is on synthetic data with a known truth. It shows that each method works as designed and
  that each check fires when it should; it says nothing yet about real markets.
- The checks use a 1% significance level, and two of them use rules of thumb: minimum-variance weights count as
  unstable when they move by more than half an equal weight, and the stress-correlation test compares the worst
  10% of days. Running many checks at once raises the chance that one fires by luck.
- Christoffersen's test of clustered VaR exceptions has little power with ten years of daily data.
- The library comparison covers minimum variance and maximum Sharpe on one synthetic data set; hierarchical risk
  parity and CVaR objectives are not compared yet. skfolio is adopted provisionally and stays an optional extra.
- Only synthetic and CSV data providers exist; no market-data vendor is connected.
- The Telegram channel is tested against a fake Bot API only. It is not yet wired into a long-running service.
- Strategies decide from the shadow book. When the real book diverges after a veto, edit or delay, the gate caps
  exits to the real position and refuses duplicate entries, but a position orphaned that way relies on its
  broker-side stop and target.
- Python cannot isolate components inside one process. Strategy isolation is enforced by architecture tests and
  by what the strategy context exposes, not by a sandbox.
- Signed grants are re-read only at start-up.
- The two built-in sub-bots have no edge; confidence values are uncalibrated.

## Phase 0 material

| Path | What it is |
| --- | --- |
| `THIRD_PARTY.md` | Dependencies, base repositories, candidate libraries and models: licence and last commit as verified |
| `docs/phase0/` | Skill audit, keep/merge/cut decisions, test summaries, licence metadata, library smoke-test output |
| `tests/fixtures/ebook_solutions.json` | 57 values from "Quantitative Finance From Scratch", re-computed and checked against the book |

`bash tools/phase0_reproduce.sh <empty dir>` reproduces the audit: it clones the three base repositories at the
audited commits, runs their tests, and regenerates the audit, the decision table and the e-book fixtures. The
claude-trading-skills matrix takes about 10 minutes; `SKIP_CTS_TESTS=1` skips it. The library smoke tests need
two environments, because PFHedge 0.23.0 requires numpy below 2: see `tools/smoke_libs.py` and
`tools/smoke_ml_libs.py`.
