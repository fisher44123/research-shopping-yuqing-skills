# -*- coding: utf-8 -*-
"""Repository-wide structural & privacy integrity checks."""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import privacy_audit  # noqa: E402


class RepoIntegrityTests(unittest.TestCase):
    def test_skills_have_valid_yaml_frontmatter(self) -> None:
        for skill in ("quick-research", "shopping-research", "yuqing-research"):
            path = os.path.join(ROOT, "skills", skill, "SKILL.md")
            self.assertTrue(os.path.isfile(path), f"Missing {path}")
            with open(path, encoding="utf-8") as f:
                text = f.read()
            m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
            self.assertIsNotNone(m, f"Missing YAML frontmatter in {skill}/SKILL.md")
            fm = m.group(1)
            self.assertIn(f"name: {skill}", fm)
            self.assertIn("description:", fm)
            self.assertLess(len(text.splitlines()), 250)

    def test_json_configs_and_eval_suites_valid(self) -> None:
        json_paths = [
            os.path.join(ROOT, "tools", "review_rules.json"),
            os.path.join(ROOT, "tools", "sku_rules.json"),
            os.path.join(ROOT, "skills", "quick-research", "references", "adapter-schema.json"),
            os.path.join(ROOT, "demo", "sample_registry.json"),
            os.path.join(ROOT, "demo", "sample_sku_candidates.json"),
            os.path.join(ROOT, "evals", "quick-research.eval.json"),
            os.path.join(ROOT, "evals", "shopping-research.eval.json"),
            os.path.join(ROOT, "evals", "yuqing-research.eval.json"),
        ]
        for jp in json_paths:
            self.assertTrue(os.path.isfile(jp), f"Missing JSON: {jp}")
            with open(jp, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIsInstance(data, dict)

        for name in ("quick-research", "shopping-research", "yuqing-research"):
            ep = os.path.join(ROOT, "evals", f"{name}.eval.json")
            with open(ep, encoding="utf-8") as f:
                ev = json.load(f)
            self.assertEqual(ev["target"], name)
            self.assertGreaterEqual(len(ev["trigger_cases"]), 7)
            self.assertGreaterEqual(len(ev["output_cases"]), 2)

    def test_privacy_audit_zero_violations(self) -> None:
        scanned, violations = privacy_audit.scan_tree(ROOT)
        self.assertGreaterEqual(scanned, 25)
        self.assertEqual(violations, [], f"Privacy violations detected: {violations}")


if __name__ == "__main__":
    unittest.main()
