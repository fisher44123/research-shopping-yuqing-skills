# AGENTS.md — Repository Rules for Coding Agents

This file defines mandatory conventions for AI coding agents working in `research-shopping-yuqing-skills`.

1. **Zero Third-Party Dependencies in `tools/`**:
   - All deterministic verification scripts (`review_check.py`, `review_log.py`, `citation_audit.py`, `sku_check.py`, `event_history_store.py`) must remain 100% Python 3.10+ standard-library only. Do not add `pip` dependencies to core tools.
2. **Strict No-Scraper / No-Bypass Boundary**:
   - Never add platform scrapers, headless browser automation, cookie extractors, CAPTCHA workarounds, or undocumented endpoint probes to this repository. Keep retrieval decoupled behind `skills/quick-research/references/adapter-schema.json`.
3. **Config-Before-Code for Review Rules**:
   - When tuning false positives or thresholds in `review_check.py` or `sku_check.py`, prefer updating `tools/review_rules.json` or `tools/sku_rules.json` when possible, and always add a regression test under `tests/`.
4. **Never Silently Swallow Failures**:
   - Deterministic tools must report real status explicitly (`status="fail"` / non-zero `--strict` exit codes) rather than silently normalizing broken data.
5. **Pre-Commit Verification Gate**:
   - Before finishing any change, run all checks and verify zero failures:
     - `python -m unittest discover -s tests -v`
     - `python demo/run_demo.py`
     - `python scripts/privacy_audit.py`
