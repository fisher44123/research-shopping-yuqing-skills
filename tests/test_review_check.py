# -*- coding: utf-8 -*-
"""Offline unit tests for tools/review_check.py and tools/review_log.py."""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)

import review_check  # noqa: E402
import review_log  # noqa: E402


class ReviewCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = review_check.load_rules()

    def test_sourced_numbers_pass(self) -> None:
        text = (
            "## 1. 实测\n"
            "官方测试显示吞吐量提升 45% [SRC-001]，社区复现共有 18 条讨论反馈内存升高 [SRC-002]。\n"
            "| 方案 | 耗时 |\n| --- | --- |\n| 方案A | 12秒 [SRC-001] |\n"
        )
        total, bad = review_check.check_numbers(text, self.rules)
        self.assertGreaterEqual(total, 2)
        self.assertEqual(bad, [])

    def test_unsourced_numbers_flagged_and_exemptions_respected(self) -> None:
        text = (
            "## 1. 无来源数字与豁免测试\n"
            "某项目并发提升 380%，总共运行了 85 个测试。\n"
            "注意：日期 2026-11-21、版本 v2.4.1、超时阈值 30 秒属于设计参数，不应误报。\n"
            "2. 字幕核验条款里的序号也不能误算。\n"
        )
        total, bad = review_check.check_numbers(text, self.rules)
        self.assertEqual(total, 2)
        self.assertEqual(len(bad), 2)

    def test_claims_and_evidence_binding(self) -> None:
        naked = "## 结论\n该架构在生产环境已实锤稳定，无需进一步核验。\n"
        self.assertTrue(review_check.check_claims(naked, self.rules))

        anchored = "## 结论\n该架构表现已实锤稳定 [SRC-001]。\n"
        self.assertEqual(review_check.check_claims(anchored, self.rules), [])

        unbound_sec = "此处参考了证据文件 §2。\n"
        self.assertEqual(len(review_check.check_evidence_binding(unbound_sec, self.rules)), 1)

        bound_sec = "证据文件: evidence_pack.json\n正文详情见 §2。\n"
        self.assertEqual(review_check.check_evidence_binding(bound_sec, self.rules), [])

    def test_overclaim_detection_and_negation(self) -> None:
        bad_txt = (
            "这是一个跨平台框架，在实际部署场景中可以 100% 解决所有超时问题并保持全量兼容，非常出色。"
        )
        self.assertEqual(len(review_check.check_overclaim(bad_txt, self.rules)), 1)

        neg_txt = (
            "原写：100% 解决所有问题，但复核后改为删掉这种夸大说法，避免误导读者判断。"
        )
        self.assertEqual(review_check.check_overclaim(neg_txt, self.rules), [])

    def test_cli_strict_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            good_md = os.path.join(tmp, "good.md")
            with open(good_md, "w", encoding="utf-8") as f:
                f.write(
                    "## 结论\n实测共 12 条样本通过验证 [SRC-001]。\n"
                    "## 未闭合缺口\n尚缺 Windows ARM 样本。\n"
                    "## 反向质疑\n"
                    "- 如果样本偏差最可能错在哪里？\n"
                    "- 如果上游更新导致接口失效怎么办？\n"
                    "- 若条件不成立是否推翻核心结论？\n"
                )
            p_good = subprocess.run(
                [sys.executable, os.path.join(TOOLS, "review_check.py"), good_md, "--strict"],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(p_good.returncode, 0, p_good.stdout)


class ReviewLogTests(unittest.TestCase):
    def test_rejects_self_review_and_incomplete_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_file = os.path.join(tmp, "review_log.md")
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    review_log.main([
                        "--context", "self",
                        "--gates", "G1:PASS;G2:PASS;G3:PASS;G4:PASS;G5:PASS",
                        "--verdict", "通过",
                        "--log", log_file,
                    ])
                with self.assertRaises(SystemExit):
                    review_log.main([
                        "--context", "author-fix-1",
                        "--gates", "G1:PASS;G2:PASS;G3:PASS;G4:PASS;G5:PASS",
                        "--verdict", "通过",
                        "--log", log_file,
                    ])
                with self.assertRaises(SystemExit):
                    review_log.main([
                        "--context", "subagent-1",
                        "--gates", "G1:PASS;G2:PASS;G3:PASS;G4:PASS",
                        "--verdict", "通过",
                        "--log", log_file,
                    ])

    def test_writes_valid_entry_and_blocks_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_file = os.path.join(tmp, "review_log.md")
            rc = review_log.main([
                "--context", "subagent-audit-99",
                "--gates", "G1:PASS;G2:PASS;G3:PASS;G4:PARTIAL;G5:PASS",
                "--verdict", "通过",
                "--target", "report.md",
                "--worst", "缺口部分还可以更细",
                "--log", log_file,
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(log_file))
            with open(log_file, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("subagent-audit-99", content)
            self.assertEqual(review_check.check_ledger(log_file), [])


if __name__ == "__main__":
    unittest.main()
