"""Static audit of the three skill packs. Reads files only; never imports or executes repo code.
Usage: python -I tools/audit_skills.py <trader-skill> <claude-trading-skills> <day-trader-skill> <out.csv>
"""
from __future__ import annotations
import csv, re, sys
from pathlib import Path
import yaml

STD = set(sys.stdlib_module_names) | {"__future__"}
IMP = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w\.]*)\s+import|import\s+([A-Za-z_][\w\.]*))", re.M)
HOST = re.compile(r"https?://([A-Za-z0-9.-]+\.[a-z]{2,})")
ENV = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:API_KEY|KEY|TOKEN|SECRET|USER_AGENT))\b")
TESTDEF = re.compile(r"^\s*def (test_\w+)", re.M)

def loc(p: Path) -> int:
    n = 0
    for ln in p.read_text(errors="replace").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            n += 1
    return n

def scan(py_files, local_names):
    third, hosts, env = set(), set(), set()
    for p in py_files:
        t = p.read_text(errors="replace")
        for a, b in IMP.findall(t):
            m = (a or b).split(".")[0]
            if m and m not in STD and m not in local_names and not m.startswith("_"):
                third.add(m)
        hosts |= {h.lower() for h in HOST.findall(t)}
        env |= set(ENV.findall(t))
    drop = {"example.com", "www.example.com", "github.com", "www.w3.org", "json-schema.org", "docs.python.org"}
    return third, {h for h in hosts if h not in drop}, env

def skill_md_flags(md: Path):
    if not md.exists():
        return 0, "", ""
    t = md.read_text(errors="replace")
    desc = ""
    m = re.search(r"^description:\s*(.+)$", t, re.M)
    if m:
        desc = m.group(1).strip().strip('"\'')
    low = t.lower()
    flags = []
    if re.search(r"websearch|web search|webfetch|web_search", low): flags.append("websearch")
    if re.search(r"chart image|screenshot|image analysis|uploaded image|\.png|\.jpg|\.jpeg", low): flags.append("image")
    if re.search(r"\bmcp\b", low): flags.append("mcp")
    return len(t.split()), desc, "+".join(flags)

def audit_cts(root: Path):
    idx = {s["id"]: s for s in yaml.safe_load((root / "skills-index.yaml").read_text())["skills"]}
    rows = []
    for d in sorted((root / "skills").iterdir()):
        if not d.is_dir():
            continue
        allpy = [p for p in d.rglob("*.py") if "__pycache__" not in p.parts]
        tests = [p for p in allpy if "tests" in p.parts or p.name.startswith("test_") or p.name == "conftest.py"]
        prod = [p for p in allpy if p not in tests]
        local = {p.stem for p in allpy} | {p.name for p in d.rglob("*") if p.is_dir()}
        third, hosts, env = scan(prod, local)
        ntests = sum(len(TESTDEF.findall(p.read_text(errors="replace"))) for p in tests)
        words, desc, flags = skill_md_flags(d / "SKILL.md")
        s = idx.get(d.name, {})
        v = s.get("verification", {})
        integ = ";".join(f"{i['id']}({i.get('requirement','?')[:3]})" for i in s.get("integrations", []) or [])
        rows.append(dict(repo="claude-trading-skills", skill=d.name, category=s.get("category", ""), status=s.get("status", ""),
            v_unit=v.get("unit_tests", ""), v_fin=v.get("financial_logic_review", ""), v_emp=v.get("empirical_validation", ""),
            v_prov=v.get("data_provenance", ""), integrations=integ, prod_files=len(prod), prod_loc=sum(map(loc, prod)),
            test_files=len(tests), test_loc=sum(map(loc, tests)), n_tests=ntests, third_party=";".join(sorted(third)),
            env=";".join(sorted(env)), hosts=";".join(sorted(hosts)), md_words=words, md_flags=flags, desc=desc[:300]))
    return rows

def audit_flat(root: Path, repo: str):
    rows = []
    for d in sorted(root.glob("trader-*")):
        prod = [p for p in d.rglob("*.py")]
        key = d.name.replace("trader-", "")
        tests = [p for p in (root / "tests").glob(f"test_{key}*.py")]
        third, hosts, env = scan(prod, {p.stem for p in prod})
        ntests = sum(len(TESTDEF.findall(p.read_text(errors="replace"))) for p in tests)
        words, desc, flags = skill_md_flags(d / "SKILL.md")
        rows.append(dict(repo=repo, skill=d.name, category="", status="", v_unit="", v_fin="", v_emp="", v_prov="", integrations="",
            prod_files=len(prod), prod_loc=sum(map(loc, prod)), test_files=len(tests), test_loc=sum(map(loc, tests)), n_tests=ntests,
            third_party=";".join(sorted(third)), env=";".join(sorted(env)), hosts=";".join(sorted(hosts)), md_words=words,
            md_flags=flags, desc=desc[:300]))
    return rows

if __name__ == "__main__":
    ts, cts, dts, out = map(Path, sys.argv[1:5])
    rows = audit_flat(ts, "trader-skill") + audit_cts(cts) + audit_flat(dts, "day-trader-skill")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    for repo in ("trader-skill", "claude-trading-skills", "day-trader-skill"):
        rr = [r for r in rows if r["repo"] == repo]
        print(f"{repo}: {len(rr)} skills, prod LOC {sum(r['prod_loc'] for r in rr)}, test LOC {sum(r['test_loc'] for r in rr)}, tests {sum(r['n_tests'] for r in rr)}")
