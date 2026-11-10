#!/usr/bin/env bash
# One-command reproduction of the Phase 0 audit.
#   bash tools/phase0_reproduce.sh <empty-work-dir>
# Clones the three base repositories at the audited commits, runs their test suites,
# regenerates the static audit, the decision table and the e-book fixtures.
# Needs: git, python >= 3.11, uv (https://docs.astral.sh/uv/). Network: github.com and pypi.org.
# The claude-trading-skills suite takes about 10 minutes.
set -euo pipefail
WORK="${1:?usage: phase0_reproduce.sh <empty-work-dir>}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$WORK"

clone_at() {  # name url sha
  if [ ! -d "$WORK/$1/.git" ]; then git clone -q "$2" "$WORK/$1"; fi
  git -C "$WORK/$1" checkout -q "$3"
}
clone_at trader-skill          https://github.com/Jakeschincariol/trader-skill         5189e79b9a480755a3733ac9713f5353981dbe18
clone_at claude-trading-skills https://github.com/tradermonty/claude-trading-skills    163ceb48968c71a701dd9cc77d827258d9b5b348
clone_at day-trader-skill      https://github.com/Jakeschincariol/day-trader-skill     3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd

echo "== trader-skill tests";     (cd "$WORK/trader-skill"     && python3 -m unittest discover -s tests 2>&1 | tail -3)
echo "== day-trader-skill tests"; (cd "$WORK/day-trader-skill" && python3 -m unittest discover -s tests 2>&1 | tail -3)
if [ "${SKIP_CTS_TESTS:-0}" = "1" ]; then
  echo "== claude-trading-skills tests skipped (SKIP_CTS_TESTS=1)"
else
  echo "== claude-trading-skills tests (log: $WORK/cts_tests.log)"
  (cd "$WORK/claude-trading-skills" && bash scripts/run_all_tests.sh > "$WORK/cts_tests.log" 2>&1) || true
  grep -E '=== Summary|^FAILED' "$WORK/cts_tests.log" || true
fi

echo "== static audit and decisions"
uv run -q --no-project --with pyyaml python -I "$HERE/tools/audit_skills.py" \
  "$WORK/trader-skill" "$WORK/claude-trading-skills" "$WORK/day-trader-skill" "$HERE/docs/phase0/skill_audit_raw.csv"
python3 "$HERE/tools/skill_decisions.py"

echo "== e-book fixtures"
python3 "$HERE/tools/verify_ebook_solutions.py"
