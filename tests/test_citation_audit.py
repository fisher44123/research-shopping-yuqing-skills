# -*- coding: utf-8 -*-
"""Offline unit tests for tools/citation_audit.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)

import citation_audit  # noqa: E402


class CitationAuditTests(unittest.TestCase):
    def test_detects_invented_ids_and_excludes_registry(self) -> None:
        text = (
            "## 1. 结论\n核心论据支持该架构 [SRC-001]，但补充了编造编号 [SRC-099]。\n"
            "## 2. 未覆盖章节\n这一段故意不写引用编号。\n"
            "## 3. 注册表 (Evidence Registry)\n"
            "| [SRC-001] | [SRC-002] |\n"
        )
        rep, md = citation_audit.audit_and_render(text, ["SRC-001", "SRC-002"])
        self.assertEqual(rep["status"], "fail")
        self.assertEqual(rep["unknown_ids"], ["SRC-099"])
        self.assertEqual(rep["sections_total"], 2)
        self.assertEqual(rep["sections_covered"], 1)
        self.assertIn("SRC-099", md)

    def test_masks_range_labels_from_weak_overlap(self) -> None:
        text = (
            "## 概览\n本轮登记了范围 [SRC-001 ~ SRC-012] 的讨论。\n"
            "内存占用在长时间运行下会达到两千四百兆字节并触发泄露警告 [SRC-001]。\n"
        )
        snippets = {
            "SRC-001": "长时间运行四小时后出现显著内存泄露，峰值占用高达两千四百兆字节，连接池未释放。",
            "SRC-012": "前端字体渲染锯齿和颜色主题对比度问题与后端无关。",
        }
        rep = citation_audit.audit_citations(
            text, ["SRC-001", "SRC-012"], evidence_snippets=snippets
        )
        self.assertEqual(rep["status"], "pass")
        self.assertEqual(rep["weak_citations"], [])

    def test_detects_weak_citation_when_context_unrelated(self) -> None:
        text = (
            "## 交互体验\n浅色模式下的按钮圆角动画非常流畅，导出图片清晰度也很高 [SRC-002]。\n"
        )
        snippets = {
            "SRC-002": "基准实测显示异步连接池未关闭，连续运行四小时后出现内存泄露和线程句柄耗尽问题。",
        }
        rep = citation_audit.audit_citations(
            text, ["SRC-002"], evidence_snippets=snippets
        )
        self.assertEqual(rep["status"], "warn")
        self.assertEqual(len(rep["weak_citations"]), 1)
        self.assertEqual(rep["weak_citations"][0]["id"], "SRC-002")

    def test_cli_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rep_file = os.path.join(tmp, "rep.md")
            reg_file = os.path.join(tmp, "reg.json")
            with open(rep_file, "w", encoding="utf-8") as f:
                f.write("## 1. 分析\n引用了不存在的编号 [SRC-404]。\n")
            with open(reg_file, "w", encoding="utf-8") as f:
                json.dump({"known_ids": ["SRC-001"]}, f)

            p = subprocess.run(
                [sys.executable, os.path.join(TOOLS, "citation_audit.py"),
                 rep_file, "--registry", reg_file, "--strict"],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(p.returncode, 1)

    def test_polarity_flip_detected_and_rendered(self) -> None:
        snippets = {
            "SRC-001": "实测当前版本在离线环境下明确不支持本地部署，且已知内存泄露问题仍未修复。",
        }
        body = (
            "## 1. 核心结论\n"
            "最新版本在离线环境下已经支持本地部署，并且历史内存泄露问题已修复 [SRC-001]。\n"
        )
        rep, md = citation_audit.audit_and_render(
            body, ["SRC-001"], evidence_snippets=snippets
        )
        self.assertEqual(rep["status"], "warn")
        self.assertGreaterEqual(len(rep["polarity_warnings"]), 1)
        pairs = {w["pair"] for w in rep["polarity_warnings"]}
        self.assertIn("支持/不支持", pairs)
        self.assertIn("已修复/未修复", pairs)
        self.assertIn("疑似极性反转", md)

    def test_reverse_polarity_affirmative_source_negated_claim(self) -> None:
        snippets = {
            "SRC-002": "官方已经在 v2.0 正式支持原生运行，目前团队保持活跃维护更新。",
        }
        body = (
            "## 1. 结论\n"
            "截至目前官方仍不支持原生运行，插件已停更跑路 [SRC-002]。\n"
        )
        rep = citation_audit.audit_citations(
            body, ["SRC-002"], evidence_snippets=snippets
        )
        self.assertEqual(rep["status"], "warn")
        dirs = {w["direction"] for w in rep["polarity_warnings"]}
        self.assertIn("证据肯定 / 正文否定", dirs)

    def test_consistent_polarity_questions_and_mixed_not_flagged(self) -> None:
        snippets = {
            "SRC-001": "实测当前版本在离线环境下明确不支持本地部署，兼容 Linux 与 macOS。",
            "SRC-002": "官方在旧版不支持，但 v2.0 起已全面支持离线运行与热重载。",
        }
        body = (
            "## 1. 结论\n"
            "实测当前版本在离线环境下确实不支持本地部署 [SRC-001]。\n"
            "读者常问：这个方案现在到底是否支持离线运行？ [SRC-001]\n"
            "虽然旧版不支持，但从 v2.0 起已全面支持离线运行 [SRC-002]。\n"
        )
        rep = citation_audit.audit_citations(
            body, ["SRC-001", "SRC-002"], evidence_snippets=snippets
        )
        self.assertEqual(rep["polarity_warnings"], [])
        self.assertEqual(rep["status"], "pass")


if __name__ == "__main__":
    unittest.main()
