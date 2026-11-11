"""Archive the cut skills and vendor the surviving ones (owner decision 2, 2026-11-10).

Nothing is deleted: every cut skill becomes one zip under _archive/<repo>/ with a one-line reason
in _archive/INDEX.md, so it can be reinstated if it later passes backtests. The 37 surviving skills
are kept as pristine reference sources under third_party/sources/ until they are converted.

Zips are reproducible (sorted entries, fixed timestamp), so re-running on the same upstream commits
gives byte-identical files.

Usage: python tools/build_archive.py <trader-skill> <claude-trading-skills> <day-trader-skill>
"""
from __future__ import annotations
import csv
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED_DATE = (2026, 11, 10, 0, 0, 0)
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv"}
REPO_URL = {
    "trader-skill": "https://github.com/Jakeschincariol/trader-skill",
    "claude-trading-skills": "https://github.com/tradermonty/claude-trading-skills",
    "day-trader-skill": "https://github.com/Jakeschincariol/day-trader-skill",
}


def skill_files(repo: str, src: Path, skill: str) -> list[tuple[Path, str]]:
    """(absolute path, path inside the zip) for everything that belongs to one skill."""
    out: list[tuple[Path, str]] = []
    if repo == "claude-trading-skills":
        roots = [src / "skills" / skill]
    else:
        key = skill.replace("trader-", "")
        roots = [src / skill, src / "tests" / "fixtures" / skill]
        for extra in (src / "tests" / f"test_{key}.py", src / "tests" / "_load.py"):
            if extra.exists():
                out.append((extra, extra.relative_to(src).as_posix()))
    for r in roots:
        if r.exists():
            for p in sorted(r.rglob("*")):
                if p.is_file() and not (set(p.parts) & SKIP_PARTS) and p.suffix != ".pyc":
                    out.append((p, p.relative_to(src).as_posix()))
    lic = src / "LICENSE"
    if lic.exists():
        out.append((lic, "LICENSE"))
    return sorted(set(out), key=lambda t: t[1])


def write_zip(dest: Path, files: list[tuple[Path, str]]) -> tuple[str, int, int]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path, arc in files:
            info = zipfile.ZipInfo(arc, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, path.read_bytes())
    data = dest.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data), len(files)


def head(src: Path) -> str:
    return subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def main() -> None:
    srcs = dict(zip(("trader-skill", "claude-trading-skills", "day-trader-skill"), map(Path, sys.argv[1:4])))
    rows = list(csv.DictReader(open(ROOT / "docs/phase0/skill_decisions.csv", newline="")))
    commits = {r: head(p) for r, p in srcs.items()}

    cut = [r for r in rows if r["decision"] == "CUT"]
    lines = [
        "# _archive: the 59 cut skills",
        "",
        "Nothing was deleted. Each skill cut in Phase 0 is one zip here, unchanged from upstream, with the reason",
        "it was cut. To reinstate one: unzip it, run its tests, then put it through the candidate gate like any",
        "other strategy. A skill leaves this folder only with out-of-sample evidence net of costs.",
        "",
        "Upstream commits:",
        "",
    ]
    lines += [f"- {r}: {REPO_URL[r]} at `{c}` (MIT)" for r, c in commits.items()]
    lines += ["", "| Skill | Repo | Archive | Files | Why it was cut | SHA-256 (first 16) |", "| --- | --- | --- | --- | --- | --- |"]
    total = 0
    for r in sorted(cut, key=lambda r: (r["repo"], r["skill"])):
        rel = Path("_archive") / r["repo"] / f"{r['skill']}.zip"
        sha, size, n = write_zip(ROOT / rel, skill_files(r["repo"], srcs[r["repo"]], r["skill"]))
        total += size
        lines.append(f"| {r['skill']} | {r['repo']} | `{rel.as_posix()}` | {n} | {r['reason']} | `{sha[:16]}` |")
    (ROOT / "_archive" / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"archived {len(cut)} cut skills, {total/1e6:.1f} MB zipped")

    keep = [r for r in rows if r["decision"] != "CUT"]
    man = [
        "# third_party/sources: pristine sources of the 37 surviving skills",
        "",
        "Reference copies, unchanged from upstream, kept until each skill is converted into a typed module under",
        "`src/quantbot/`. They are not imported at run time. Licences are in `third_party/licenses/`.",
        "",
        "| Archive | Upstream commit | Skills inside | Files | SHA-256 (first 16) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for repo, src in srcs.items():
        skills = sorted(r["skill"] for r in keep if r["repo"] == repo)
        files: dict[str, Path] = {}
        for s in skills:
            for path, arc in skill_files(repo, src, s):
                files[arc] = path
        rel = Path("third_party") / "sources" / f"{repo}.zip"
        sha, size, n = write_zip(ROOT / rel, sorted(((p, a) for a, p in files.items()), key=lambda t: t[1]))
        man.append(f"| `{rel.as_posix()}` | `{commits[repo][:12]}` | {', '.join(skills)} | {n} | `{sha[:16]}` |")
        lic_dir = ROOT / "third_party" / "licenses"
        lic_dir.mkdir(parents=True, exist_ok=True)
        (lic_dir / f"{repo}-LICENSE").write_text((src / "LICENSE").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        print(f"vendored {len(skills)} surviving skills from {repo}: {n} files, {size/1e6:.1f} MB zipped")
    man += ["", "Which skill becomes which module, and why, is in `docs/phase0/skill_decisions.csv`."]
    (ROOT / "third_party" / "sources" / "README.md").write_text("\n".join(man) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
