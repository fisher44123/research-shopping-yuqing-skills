#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automated privacy, credential, and out-of-scope scraper leak scanner.

Scans all tracked/workspace text files under the public preview repository and
fails with exit code 1 if any local path, personal identifier, secret token,
geographic location tracking field, or private scraper identifier is detected.
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv"}
TEXT_EXTS = {
    ".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".sh", ".ps1", "",  # extensionless e.g. LICENSE
}

# Patterns are constructed so this scanner can scan every file cleanly without self-hits.
FORBIDDEN_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("personal_name", re.compile("\u5218\u4f73")),
    ("windows_user_path", re.compile(r"(?i)[A-Z]:\\Users\\")),
    ("local_drive_archive_path", re.compile(r"(?i)D:\\05_")),
    ("local_agent_dotdir", re.compile(r"(?:\.agents|\.gemini|\.work" + r"buddy)[\\/]")),
    ("private_env_name", re.compile(r"(?i)\b(?:" + "Work" + "Buddy|" + "My" + "Lucy|" + "Res" + r"pan)\b")),
    (
        "private_scraper_module",
        re.compile(
            r"(?i)\b(?:"
            + "search_" + "hub|"
            + "yuqing_" + "hub|"
            + "ego_" + "harvest|"
            + "ego_" + "routing|"
            + "ego-" + "browser|"
            + "ego_" + "cookie|"
            + "tieba_" + "probe|"
            + "community_" + "probe|"
            + "douyin_" + "web|"
            + "tg_" + "index|"
            + "tg_" + "mtproto|"
            + "aio" + "tieba|"
            + "kuri" + "gram|"
            + "coolapk_" + "mcp|"
            + "open" + "cli|"
            + "any" + "search|"
            + "tg-" + "channels|"
            + "tg-" + "watchlist|"
            + "deep_" + "fetch|"
            + "browser_" + "cdp|"
            + "benchmark_" + "probe"
            + r")\b"
        ),
    ),
    (
        "cookie_or_session_secret",
        re.compile(r"\b(?:" + "BD" + "USS|" + "STO" + "KEN|" + "BILI_" + r"SESSDATA)\b"),
    ),
    ("api_token_sk", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("github_token", re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z\-_]{30,}\b")),
    ("forbidden_geo_field", re.compile(r"(?:ip_" + "location|ip" + r"Location)")),
]


def scan_tree(root: str = ROOT) -> tuple[int, list[dict]]:
    """Scan all text files under root and return (file_count, violations)."""
    scanned = 0
    violations: list[dict] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in sorted(filenames):
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, root).replace("\\", "/")
            ext = os.path.splitext(fname)[1].lower()
            if ext not in TEXT_EXTS and fname not in ("LICENSE", ".gitignore"):
                continue
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except (UnicodeDecodeError, OSError):
                continue

            scanned += 1
            for lineno, line in enumerate(lines, start=1):
                for rule_name, pattern in FORBIDDEN_RULES:
                    m = pattern.search(line)
                    if m:
                        violations.append({
                            "file": rel,
                            "line": lineno,
                            "rule": rule_name,
                            "match": m.group(0),
                        })
    return scanned, violations


def main() -> int:
    scanned, violations = scan_tree(ROOT)
    print("=" * 72)
    print(f"Privacy & No-Scraper Audit | Scanned {scanned} files under {os.path.basename(ROOT)}")
    print("=" * 72)
    if violations:
        print(f"FAIL: Found {len(violations)} forbidden match(es):")
        for v in violations:
            print(f"  - {v['file']}:{v['line']} [{v['rule']}] matched {v['match']!r}")
        return 1
    print("PASS: 0 violations detected across all scanned files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
