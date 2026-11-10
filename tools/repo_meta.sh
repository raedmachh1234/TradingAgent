#!/usr/bin/env bash
# Usage: repo_meta.sh owner/repo outdir
# Prints one TSV line: repo, HEAD commit date, top-level entry count, licence files, licence head, tests dir, CI workflow count.
# Blobless, depth-1, no-checkout clone: reads commit metadata and the licence blob only. Nothing is executed.
set -u
repo="$1"; out="$2"
d=$(mktemp -d "$out/$(echo "$repo" | tr '/' '_').XXXXXX")
if ! GIT_TERMINAL_PROMPT=0 timeout 90 git clone -q --depth 1 --filter=blob:none --no-checkout "https://github.com/$repo" "$d/r" 2>"$d/err"; then
  printf '%s\tCLONE_FAILED\t%s\n' "$repo" "$(tr '\n' ' ' < "$d/err" | cut -c1-160)"
  exit 0
fi
cd "$d/r" || exit 0
date=$(git log -1 --format=%cI)
tree=$(git ls-tree --name-only HEAD)
lic=$(echo "$tree" | grep -i -E '^(LICEN[SC]E|COPYING|UNLICENSE)' | head -3 | tr '\n' ',')
first=$(echo "$tree" | grep -i -E '^(LICEN[SC]E|COPYING|UNLICENSE)' | head -1)
lhead=""
if [ -n "$first" ]; then
  lhead=$(git show "HEAD:$first" 2>/dev/null | grep -v '^\s*$' | head -4 | tr '\n' ' ' | tr '\t' ' ' | cut -c1-170)
fi
tests=$(echo "$tree" | grep -i -E '^(tests?|testing|unit_tests)$' | head -1)
ci=$(git ls-tree --name-only HEAD .github/workflows/ 2>/dev/null | wc -l)
printf '%s\t%s\t%s\t%s\t%s\ttests=%s\tci=%s\n' "$repo" "$date" "$(echo "$tree" | wc -l)" "$lic" "$lhead" "${tests:-none}" "$ci"
