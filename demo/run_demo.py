#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""60-second offline demo proving all four deterministic verification tools work without network."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
DEMO = os.path.join(ROOT, "demo")
sys.path.insert(0, TOOLS)

import citation_audit  # noqa: E402
from event_history_store import EventHistoryStore  # noqa: E402
import sku_check  # noqa: E402


def _banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main() -> int:
    report_path = os.path.join(DEMO, "sample_flawed_report.md")
    registry_path = os.path.join(DEMO, "sample_registry.json")
    sku_cands_path = os.path.join(DEMO, "sample_sku_candidates.json")

    with open(report_path, encoding="utf-8") as f:
        report_text = f.read()

    # 1. Citation Audit: catch invented SRC-099 + unrelated SRC-002 context + empty section 4
    _banner("[1/4] citation_audit.py —— 抓编造 SRC 编号与文不对题引用")
    known_ids, snippets = citation_audit.load_registry(registry_path)
    rep, md_appendix = citation_audit.audit_and_render(
        report_text, known_ids, evidence_snippets=snippets
    )
    print(md_appendix.strip())
    assert rep["status"] == "fail", f"Expected fail, got {rep['status']}"
    assert rep["unknown_ids"] == ["SRC-099"], f"Unexpected unknown_ids: {rep['unknown_ids']}"
    assert any(w["id"] == "SRC-002" for w in rep["weak_citations"]), "Expected weak citation on SRC-002"
    print("-> Demo Check 1 PASS: 已成功揪出编造编号 SRC-099 与张冠李戴的 SRC-002。")

    # 2. Review Check: strict mode must return exit code 1 on unsourced stats + bare claims
    _banner("[2/4] review_check.py --strict —— 硬拦裸统计数字与无凭证声称")
    proc = subprocess.run(
        [sys.executable, os.path.join(TOOLS, "review_check.py"), report_path, "--strict"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    print(proc.stdout.strip())
    assert proc.returncode == 1, f"Expected exit code 1 under --strict, got {proc.returncode}"
    print("-> Demo Check 2 PASS: review_check --strict 成功返回退出码 1 并拦截硬伤。")

    # 3. SKU Check: catch Pro / 12+512 / 小米15 mismatch + deterministic unit cost
    _banner("[3/4] sku_check.py —— 字段级防张冠李戴与单次成本精算")
    with open(sku_cands_path, encoding="utf-8") as f:
        sku_data = json.load(f)
    rc_sku = sku_check.main([
        "--target", sku_data["target"],
        "--cands-json", sku_cands_path,
        "--strict",
    ])
    assert rc_sku == 3, f"Expected exit code 3 on SKU mismatch, got {rc_sku}"

    print("\n--- 复合规格折算与单次成本演示（25g/次） ---")
    c_big = sku_check.compute_unit_cost("立白 彩漂粉 500g*2袋 29.9元", dose="25g")
    c_small = sku_check.compute_unit_cost("立白 彩漂粉 500g 桶装 19.9元", dose="25g")
    ratio = c_small["cost_per_use"] / c_big["cost_per_use"]
    print(f"  大包装 500g*2袋 (¥29.9) -> 总重 {c_big['total_weight_g']}g | 单次 ¥{c_big['cost_per_use']:.3f} | 折合 ¥{c_big['per_500g']:.2f}/斤")
    print(f"  小包装 500g桶装 (¥19.9) -> 总重 {c_small['total_weight_g']}g | 单次 ¥{c_small['cost_per_use']:.3f} | 折合 ¥{c_small['per_500g']:.2f}/斤")
    print(f"  成本对比：贵的那款单次要 {c_small['cost_per_use']:.3f} 元，便宜这款 {c_big['cost_per_use']:.3f} 元，差 {ratio:.2f} 倍。")
    assert c_big["total_weight_g"] == 1000.0 and c_big["servings"] == 40.0
    print("-> Demo Check 3 PASS: SKU 错配硬拦与单次使用成本计算完全准确。")

    # 4. EventHistoryStore: atomic commit + SHA-256 hash + JSON atomic export
    _banner("[4/4] event_history_store.py —— SQLite 事务落盘与来源健康追踪")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "events.db")
        json_file = os.path.join(tmpdir, "events_backup.json")
        store = EventHistoryStore(db_file, json_file)
        store.commit_run(
            run_id="demo-run-001",
            topic_key="demoframe-v2",
            events=[
                {
                    "raw_event_id": "evt-001",
                    "source": "github_api",
                    "source_url": "https://example.com/demoframe/issues/418",
                    "title": "内存峰值告警讨论",
                    "raw_text": "运行四小时后占用 2.4GB",
                    "observed_at": "2026-11-21T02:00:00Z",
                }
            ],
            health=[
                {"source": "github_api", "status": "ok", "attempts": 1, "items_seen": 12, "items_new": 1},
                {"source": "tech_forum", "status": "timeout", "attempts": 1, "consecutive_failures": 1, "last_error_code": "ETIMEDOUT"},
            ],
            outputs=[{"output_name": "final_report.md", "status": "verified", "attempts": 1}],
        )
        loaded = store.load_events("demoframe-v2")
        exported = store.export_json("demoframe-v2")
        assert len(loaded) == 1 and os.path.exists(exported)
        print(f"  SQLite 入库事件数: {len(loaded)} ｜ 已原子导出 JSON 快照: {os.path.basename(exported)}")
    print("-> Demo Check 4 PASS: 事务持久化与原子导出正常。")

    print("\n✅ 全部 4 项确定性核验演示均按预期精准命中拦截！")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
