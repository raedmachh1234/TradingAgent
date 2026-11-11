# _archive: the 59 cut skills

Nothing was deleted. Each skill cut in Phase 0 is one zip here, unchanged from upstream, with the reason
it was cut. To reinstate one: unzip it, run its tests, then put it through the candidate gate like any
other strategy. A skill leaves this folder only with out-of-sample evidence net of costs.

Upstream commits:

- trader-skill: https://github.com/Jakeschincariol/trader-skill at `5189e79b9a480755a3733ac9713f5353981dbe18` (MIT)
- claude-trading-skills: https://github.com/tradermonty/claude-trading-skills at `163ceb48968c71a701dd9cc77d827258d9b5b348` (MIT)
- day-trader-skill: https://github.com/Jakeschincariol/day-trader-skill at `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd` (MIT)

| Skill | Repo | Archive | Files | Why it was cut | SHA-256 (first 16) |
| --- | --- | --- | --- | --- | --- |
| breadth-chart-analyst | claude-trading-skills | `_archive/claude-trading-skills/breadth-chart-analyst.zip` | 19 | Reads chart images | `24774f0575651b8e` |
| breakout-trade-planner | claude-trading-skills | `_archive/claude-trading-skills/breakout-trade-planner.zip` | 13 | Only useful downstream of VCP, which is cut pending backtest | `ea7eafcfac8657b7` |
| canslim-screener | claude-trading-skills | `_archive/claude-trading-skills/canslim-screener.zip` | 28 | Cut pending backtest; re-enters only through the candidate gate | `d4780a49c54ede76` |
| contrarian-setup-gate | claude-trading-skills | `_archive/claude-trading-skills/contrarian-setup-gate.zip` | 10 | Final step of the COT chain | `5913360e5bec9e59` |
| cot-contrarian-detector | claude-trading-skills | `_archive/claude-trading-skills/cot-contrarian-detector.zip` | 13 | COT chain; CFTC publishes the data free if revisited | `38f497f62cdf1960` |
| crypto-regime-analyzer | claude-trading-skills | `_archive/claude-trading-skills/crypto-regime-analyzer.zip` | 26 | Beta; per brief | `aca7e697109135b8` |
| data-quality-checker | claude-trading-skills | `_archive/claude-trading-skills/data-quality-checker.zip` | 8 | Validates blog and markdown documents, not market data; the data layer gets its own checks | `ffc37778823c8661` |
| dividend-growth-pullback-screener | claude-trading-skills | `_archive/claude-trading-skills/dividend-growth-pullback-screener.zip` | 12 | Per brief | `7605883f09e19908` |
| downtrend-duration-analyzer | claude-trading-skills | `_archive/claude-trading-skills/downtrend-duration-analyzer.zip` | 13 | Descriptive histograms only | `d87e6272ccdd7db7` |
| dual-axis-skill-reviewer | claude-trading-skills | `_archive/claude-trading-skills/dual-axis-skill-reviewer.zip` | 8 | Meta tooling | `06c696f5dff3de19` |
| edge-candidate-agent | claude-trading-skills | `_archive/claude-trading-skills/edge-candidate-agent.zip` | 22 | Idea-generation pipeline | `164e9047eba7a9d6` |
| edge-concept-synthesizer | claude-trading-skills | `_archive/claude-trading-skills/edge-concept-synthesizer.zip` | 8 | Idea-generation pipeline | `be9a8af293dedc3f` |
| edge-hint-extractor | claude-trading-skills | `_archive/claude-trading-skills/edge-hint-extractor.zip` | 8 | Idea-generation pipeline with optional LLM ideation | `424b1513d6600943` |
| edge-pipeline-orchestrator | claude-trading-skills | `_archive/claude-trading-skills/edge-pipeline-orchestrator.zip` | 8 | Idea-generation pipeline | `a50d33a18e0c75c8` |
| edge-signal-aggregator | claude-trading-skills | `_archive/claude-trading-skills/edge-signal-aggregator.zip` | 8 | Aggregates cut skills | `3928cfd7d3c3d95a` |
| edge-strategy-designer | claude-trading-skills | `_archive/claude-trading-skills/edge-strategy-designer.zip` | 9 | Idea-generation pipeline | `4c9f69bd5c1871a0` |
| finviz-screener | claude-trading-skills | `_archive/claude-trading-skills/finviz-screener.zip` | 7 | Builds FinViz URLs and opens a browser | `210505d6a4e7968a` |
| fxmacrodata-calendar | claude-trading-skills | `_archive/claude-trading-skills/fxmacrodata-calendar.zip` | 5 | Beta; small vendor; can return as a provider behind the calendar interface | `4c5907f95e2563a4` |
| institutional-flow-tracker | claude-trading-skills | `_archive/claude-trading-skills/institutional-flow-tracker.zip` | 19 | Same 13F data through a paid aggregator; edgar13f reads the primary source | `d32ef1e5e2b6159a` |
| kanchi-dividend-review-monitor | claude-trading-skills | `_archive/claude-trading-skills/kanchi-dividend-review-monitor.zip` | 10 | Per brief | `daa44a4f6570fac6` |
| kanchi-dividend-sop | claude-trading-skills | `_archive/claude-trading-skills/kanchi-dividend-sop.zip` | 29 | Per brief | `db26523f01f5fe8a` |
| kanchi-dividend-us-tax-accounting | claude-trading-skills | `_archive/claude-trading-skills/kanchi-dividend-us-tax-accounting.zip` | 11 | Per brief | `802e01c0379a363b` |
| manifoldbt-backtester | claude-trading-skills | `_archive/claude-trading-skills/manifoldbt-backtester.zip` | 14 | Beta; per brief | `0e1f920df7307174` |
| market-environment-analysis | claude-trading-skills | `_archive/claude-trading-skills/market-environment-analysis.zip` | 10 | Narrative | `28754f77c3a7b0ea` |
| market-news-analyst | claude-trading-skills | `_archive/claude-trading-skills/market-news-analyst.zip` | 7 | Narrative; no code | `281f36ff197ef1ca` |
| market-top-detector | claude-trading-skills | `_archive/claude-trading-skills/market-top-detector.zip` | 44 | Composite of other regime inputs plus web-searched values | `c8f06737cb7010ff` |
| mt5-robot-tester | claude-trading-skills | `_archive/claude-trading-skills/mt5-robot-tester.zip` | 20 | Beta; per brief | `459504e1dbed2c51` |
| news-reaction-failure-analyzer | claude-trading-skills | `_archive/claude-trading-skills/news-reaction-failure-analyzer.zip` | 11 | Needs LLM-curated news judgement | `12160829111a6b69` |
| parabolic-short-trade-planner | claude-trading-skills | `_archive/claude-trading-skills/parabolic-short-trade-planner.zip` | 99 | Per brief | `21cf37ce99a5485d` |
| portfolio-manager | claude-trading-skills | `_archive/claude-trading-skills/portfolio-manager.zip` | 25 | Per brief | `2be044fa2a5dfcf0` |
| scenario-analyzer | claude-trading-skills | `_archive/claude-trading-skills/scenario-analyzer.zip` | 6 | Narrative; no code | `86d1e4d60aa279f5` |
| sector-analyst | claude-trading-skills | `_archive/claude-trading-skills/sector-analyst.zip` | 11 | Reads chart images | `21e1794223db67e6` |
| skill-designer | claude-trading-skills | `_archive/claude-trading-skills/skill-designer.zip` | 9 | Meta tooling | `11add56492fd17f9` |
| skill-idea-miner | claude-trading-skills | `_archive/claude-trading-skills/skill-idea-miner.zip` | 11 | Meta tooling | `b164512119b38921` |
| skill-integration-tester | claude-trading-skills | `_archive/claude-trading-skills/skill-integration-tester.zip` | 7 | Meta tooling | `a778c7e16aa609b0` |
| stanley-druckenmiller-investment | claude-trading-skills | `_archive/claude-trading-skills/stanley-druckenmiller-investment.zip` | 19 | Narrative synthesis of cut skills | `f4841c7f9e2afc8b` |
| stockbee-20pct-study | claude-trading-skills | `_archive/claude-trading-skills/stockbee-20pct-study.zip` | 17 | Beta; per brief | `cb2ebabe1c32e4e0` |
| stockbee-episodic-pivot-analyzer | claude-trading-skills | `_archive/claude-trading-skills/stockbee-episodic-pivot-analyzer.zip` | 10 | Beta; per brief | `53423c86cc9d525a` |
| stockbee-exhaustion-hammer-screener | claude-trading-skills | `_archive/claude-trading-skills/stockbee-exhaustion-hammer-screener.zip` | 10 | Beta; per brief | `5e781865a67a50b3` |
| stockbee-momentum-burst-screener | claude-trading-skills | `_archive/claude-trading-skills/stockbee-momentum-burst-screener.zip` | 13 | Beta; per brief | `a6e879ea02f90d21` |
| stockbee-setup-fluency-trainer | claude-trading-skills | `_archive/claude-trading-skills/stockbee-setup-fluency-trainer.zip` | 10 | Beta; per brief | `abe0bf0bf2547188` |
| strategy-pivot-designer | claude-trading-skills | `_archive/claude-trading-skills/strategy-pivot-designer.zip` | 15 | Not in your lists: generates new variants when backtests stall, which invites overfitting | `2345107a270f3c37` |
| technical-analyst | claude-trading-skills | `_archive/claude-trading-skills/technical-analyst.zip` | 12 | Reads chart images | `ece906548345e986` |
| theme-detector | claude-trading-skills | `_archive/claude-trading-skills/theme-detector.zip` | 50 | Cut pending backtest | `d13215fb6ae59ffa` |
| trade-hypothesis-ideator | claude-trading-skills | `_archive/claude-trading-skills/trade-hypothesis-ideator.zip` | 29 | Not in your lists: LLM ideation | `e99df5a21c083850` |
| trade-performance-coach | claude-trading-skills | `_archive/claude-trading-skills/trade-performance-coach.zip` | 18 | Not in your lists: beta, LLM coaching | `04489d0c5c7fe893` |
| trading-skills-navigator | claude-trading-skills | `_archive/claude-trading-skills/trading-skills-navigator.zip` | 13 | Meta tooling | `22c360619fedf537` |
| us-market-bubble-detector | claude-trading-skills | `_archive/claude-trading-skills/us-market-bubble-detector.zip` | 11 | Narrative | `0400b74fa4cd78e3` |
| us-stock-analysis | claude-trading-skills | `_archive/claude-trading-skills/us-stock-analysis.zip` | 7 | Narrative; no code | `f5fff1b9929bf7a4` |
| us-undervalued-growth-screener | claude-trading-skills | `_archive/claude-trading-skills/us-undervalued-growth-screener.zip` | 74 | Beta; 14,635 lines; per brief | `cc9692043c7ede49` |
| value-dividend-screener | claude-trading-skills | `_archive/claude-trading-skills/value-dividend-screener.zip` | 12 | Per brief | `cc423b751f0496bd` |
| vcp-screener | claude-trading-skills | `_archive/claude-trading-skills/vcp-screener.zip` | 27 | Cut pending backtest | `ebf22fd3ce574239` |
| trader-alerts | day-trader-skill | `_archive/day-trader-skill/trader-alerts.zip` | 15 | Duplicate; calendar table taken from trader-skill | `82c5fb93344fb648` |
| trader-analyst | day-trader-skill | `_archive/day-trader-skill/trader-analyst.zip` | 12 | Duplicate | `40930b3b8b794c77` |
| trader-news | day-trader-skill | `_archive/day-trader-skill/trader-news.zip` | 12 | Duplicate; diff for improvements during the merge | `51dc7f9999d80eba` |
| trader-pelosi | day-trader-skill | `_archive/day-trader-skill/trader-pelosi.zip` | 10 | Per brief | `26329da371283d62` |
| trader-scanner | day-trader-skill | `_archive/day-trader-skill/trader-scanner.zip` | 12 | Universe scan tied to Yahoo; screener engine plus data layer replace it | `6a4747d4eeb13e96` |
| trader-pelosi | trader-skill | `_archive/trader-skill/trader-pelosi.zip` | 10 | Per brief; fragile PDF parsing and long disclosure lag | `ee42e1d29966259e` |
| trader-tax | trader-skill | `_archive/trader-skill/trader-tax.zip` | 8 | US tax-lot and wash-sale rules; jurisdiction-specific | `9cb1382134be550d` |
