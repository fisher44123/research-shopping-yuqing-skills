#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立审核台账：把一次独立审核的结论追加成一行，供人工抽查。

不判通过、不改交付物、不做元审核。判定权只在独立审核者（子 agent / 新会话）。
"""
import argparse
import datetime as dt
import os
import re
import sys

DEFAULT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_log.md")
HEADER = ("# 独立审核台账（人工抽查用）\n\n"
          "> 一行一次。模型只负责留痕，不得据此声称「元审核通过」。\n"
          "> 格式：时间 ｜ 上下文 ID ｜ 目标 ｜ G1–G5 ｜ 结论 ｜ 最不满意的一处\n\n")


def _ensure_utf8_stdio() -> None:
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main(argv=None):
    _ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="追加一条独立审核记录")
    ap.add_argument("--context", required=True, help="子 agent ID / 新会话标识（必填，不许编）")
    ap.add_argument("--gates", required=True, help="五条门禁逐条结果，如 G1:PASS;G2:FAIL")
    ap.add_argument("--verdict", required=True, choices=["通过", "重写后通过", "未通过"])
    ap.add_argument("--target", default="", help="本轮被审的交付物路径")
    ap.add_argument("--worst", default="", help="最不满意的一处")
    ap.add_argument("--log", default=DEFAULT_LOG, help="审核台账文件路径（默认同目录 review_log.md）")
    a = ap.parse_args(argv)

    # 拒绝作者用同一上下文自审或以 author-* 前缀自判「通过」
    ctx = a.context.strip()
    if not ctx or ctx.lower() in ("self", "作者", "same"):
        ap.error("--context 必须是独立上下文标识，拒绝自审留痕")
    if ctx.lower().startswith("author") and a.verdict == "通过":
        ap.error('作者自记只能是「重写后通过」或「未通过」；「通过」只能由独立审核者写')

    # 逐条解析 G1–G5，五条齐全且每条带 PASS/FAIL/PARTIAL 才放行
    items = [x.strip().upper() for x in a.gates.split(";") if x.strip()]
    res = {}
    for it in items:
        m = re.match(r"^(G[1-5]):(PASS|FAIL|PARTIAL)$", it)
        if not m:
            ap.error('--gates 每条必须是 "G1:PASS" 格式（PASS/FAIL/PARTIAL），收到: %r' % it)
        res[m.group(1)] = m.group(2)
    missing = [f"G{i}" for i in range(1, 6) if f"G{i}" not in res]
    if missing:
        ap.error("--gates 缺 %s，五条门禁必须逐条给结果" % ",".join(missing))

    log_path = os.path.abspath(a.log)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    if not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(HEADER)

    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def cell(s):
        return str(s or "").replace("|", "/").replace("\n", " ").strip()[:200]

    row = "| %s ｜ %s ｜ %s ｜ %s ｜ %s ｜ %s |\n" % (
        ts, cell(a.context), cell(a.target), cell(a.gates),
        cell(a.verdict), cell(a.worst))

    # 跨进程追加：独占临时锁文件，写入后立即删除；拒绝完全相同的重复记录
    lock = log_path + ".lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        with open(log_path, encoding="utf-8") as f:
            existing = f.read()
        if row in existing:
            ap.error("重复审核记录，拒绝追加")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(row)
    finally:
        try:
            os.unlink(lock)
        except FileNotFoundError:
            pass
    print("✅ 已追加审核记录 → %s" % log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
