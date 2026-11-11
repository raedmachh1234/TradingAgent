"""No secrets in the repository, and the ignore rules the owner asked for are in place."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "data", "models", "__pycache__", ".pytest_cache", "_archive", "sources"}
PATTERNS = {
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "assignment of a secret": re.compile(r"(?i)\b(api_key|secret|password|token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
}


def text_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not set(p.relative_to(ROOT).parts) & SKIP_DIRS and p.suffix not in {".zip", ".parquet", ".duckdb", ".pyc"}:
            yield p


def test_no_secret_patterns_in_tracked_text():
    hits = []
    for p in text_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        for name, pat in PATTERNS.items():
            if pat.search(text):
                hits.append(f"{p.relative_to(ROOT)}: {name}")
    assert not hits, hits


def test_no_env_or_key_files_and_the_ignore_rules_exist():
    assert not (ROOT / ".env").exists()
    assert not [p for p in text_files() if p.suffix in {".key", ".pem"}]
    rules = (ROOT / ".gitignore").read_text().splitlines()
    for rule in (".env", "data/", "models/", "*.key"):
        assert rule in rules, rule


def test_the_shipped_autonomy_file_grants_nothing():
    doc = yaml.safe_load((ROOT / "config" / "autonomy.yaml").read_text()) or {}
    assert not doc.get("grants")
