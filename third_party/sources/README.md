# third_party/sources: pristine sources of the 37 surviving skills

Reference copies, unchanged from upstream, kept until each skill is converted into a typed module under
`src/quantbot/`. They are not imported at run time. Licences are in `third_party/licenses/`.

| Archive | Upstream commit | Skills inside | Files | SHA-256 (first 16) |
| --- | --- | --- | --- | --- |
| `third_party/sources/trader-skill.zip` | `5189e79b9a48` | trader-alerts, trader-analyst, trader-broker, trader-budget, trader-copycat, trader-news, trader-rebalance, trader-risk, trader-screener | 76 | `ca3da26f15b0bf93` |
| `third_party/sources/claude-trading-skills.zip` | `163ceb48968c` | backtest-expert, drawdown-circuit-breaker, earnings-calendar, earnings-trade-analyzer, economic-calendar-fetcher, edge-strategy-reviewer, exposure-coach, ftd-detector, futures-position-sizer, ibd-distribution-day-monitor, macro-regime-detector, market-breadth-analyzer, options-strategy-advisor, pair-trade-screener, pead-screener, position-sizer, pre-trade-discipline-gate, residual-edge-analyzer, signal-postmortem, trader-memory-core, uptrend-analyzer, weekly-performance-digest | 313 | `5bf01f6e610227ec` |
| `third_party/sources/day-trader-skill.zip` | `3d0f4ef6986f` | trader-broker, trader-budget, trader-entry, trader-exit, trader-risk, trader-timemachine | 30 | `22f7c24fb95aaad2` |

Which skill becomes which module, and why, is in `docs/phase0/skill_decisions.csv`.
