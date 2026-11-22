#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review_check.py —— 交付前的「确定性检查」层（能机器判的，绝不交给模型判）。

## 为什么要有这个

如果审核门禁本身完全依赖 LLM 主观打分（“我觉得可以”），就很容易陷入自我偏好、
位置偏差或形式主义。业界成熟实践将校验严格分成两类：
- **Deterministic eval metrics**：equals/contains/regex/python …
  程序确定性判定，同一输入永远同一结果；
- **Model-assisted eval metrics**：llm-rubric/g-eval/factuality … 模型辅助判断，
  存在自我偏好、位置偏差、冗长偏差等系统性误差。

本脚本只负责第一类，先用确定性代码把「数字缺来源」「空口声称已验证」等硬伤拦下来，
再把真正需要语义理解的部分交给人或独立审核上下文。

## 设计原则（规则外置 + 双级门禁）

1. **规则全部外置**到 `review_rules.json`。词表、模式、阈值、哪项硬拦哪项只提示，
   都在配置文件里，调整松紧无需改代码。
2. **分两级**：`fail_on`（硬拦，退出码 1）默认只留「数字没来源」「说跑过没凭证」两条——
   这两条会直接误导读者；其余降级为 `warn_on`（只提示，不阻塞交付）。

## 用法

    python tools/review_check.py report.md              # 只看结果
    python tools/review_check.py report.md --strict     # 有 FAIL 就退出码 1（接 CI/hook 用）
    python tools/review_check.py report.md --rules custom_rules.json

## 边界（写清楚，不夸大）

- 只查「形式与可核对性」，查不出「结论是否真的对」；
- 数字溯源只验「附近有没有来源标注」，不验「那个来源是否真支持这个数字」；
- 反向质疑只验条数，不验质量；
- 把 A 产品的参数安到 B 产品上时，需要 `sku_check.py` 或人工回源做实体核对。
"""
import argparse
import json
import os
import re
import sys

RULES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_rules.json")

_DEFAULT_RULES = {
    "fail_on": ["numbers", "claims"],
    "warn_on": ["overclaim", "gap_section", "reverse", "ledger"],
    "number_check": {
        "stat_units": ["个", "条", "项", "部", "篇", "次", "秒", "元", "%", "星", "人", "字", "万", "倍"],
        "max_unsourced_ratio": 0.3,
        "skip_line_prefix": ["```", "|--", "#"],
        "design_param_words": ["设计参数", "超时", "阈值", "最多", "默认"],
    },
    "overclaim_words": ["全量", "一对一", "必然", "彻底", "唯一可靠", "100%"],
    "overclaim_negation": "删掉|降级|改为|不再|避免|禁止",
    "claim_patterns": [["FAIL\\s*0\\s*/\\s*WARN\\s*0", "自称自检全绿"],
                       ["已实锤", "自称已实锤"]],
    "claim_negation": "未通过|缺|但",
    "source_hint": "SRC-[A-Z0-9]+|https?://|file:///|[A-Za-z]:\\\\|\\.md|\\.txt|\\.json|\\.csv|\\[\\d{4}\\s*\\||命令[:：]|python\\s|§\\d",
    "gap_section_pattern": "未闭合|覆盖缺口|仍未解决|带病|没做",
    "reverse_question_pattern": "^\\s*[-*\\d\\.]{1,3}\\s*.*(如果.*错|最可能错|反向质疑)",
    "min_reverse_questions": 3,
}

# 数字不查的场景：日期/时间、URL、版本号、行号、常见扩展名
_SKIP_NUM_CTX = re.compile(
    r"(\d{2}:\d{2}|\d{4}-\d{2}-\d{2}|https?://|file:///|\bv?\d+\.\d+\.\d+|L\d+|#\d+|\.md|\.txt|\.json|\.csv|\.py)")


def load_rules(path=None):
    """读规则文件；读不到就用内置副本，绝不因为缺少配置文件而罢工。"""
    p = path or RULES_FILE
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and "fail_on" in d:
            return d
    except Exception:  # noqa: BLE001
        pass
    return _DEFAULT_RULES


def _src_re(rules):
    return re.compile(rules.get("source_hint") or _DEFAULT_RULES["source_hint"])


def _table_cells(line):
    """兼容 Markdown 半角竖线和中文全角竖线表格。"""
    if "｜" in line:
        return [c.strip() for c in line.split("｜")]
    return [c.strip() for c in line.split("|")]


def _evidence_declarations(text):
    """提取报告开头声明的凭证文件，供 §N 引用绑定。"""
    head = "\n".join(text.splitlines()[:40])
    return set(re.findall(r"(?:凭证|证据|evidence)[^\n:：]*[:：]\s*([^\s，,；;]+)", head, re.I))


def check_evidence_binding(text, rules):
    """§N 简写必须绑定到开头声明的 evidence 文件，避免裸引用。"""
    refs = re.findall(r"§\s*(\d+)", text)
    if not refs:
        return []
    declared = _evidence_declarations(text)
    if declared:
        return []
    return [("§" + n, "缺少开头凭证文件声明") for n in sorted(set(refs))]


def check_numbers(text, rules):
    """数字附近有没有来源标注。只查「统计量」（数字后紧跟计量单位）。"""
    nc = rules.get("number_check") or {}
    units = "|".join(re.escape(u) for u in (nc.get("stat_units") or ["个", "条", "元"]))
    stat = re.compile(r"\d[\d,\.]*\s*(%s)" % units)
    prefixes = tuple(nc.get("skip_line_prefix") or ("```", "#"))
    design = re.compile("|".join(nc.get("design_param_words") or ["设计参数"]))
    src = _src_re(rules)
    bad, total = [], 0
    lines_list = text.splitlines()
    for idx0, ln in enumerate(lines_list):
        i = idx0 + 1
        st = ln.strip()
        if st.startswith(prefixes) or not stat.search(ln):
            continue
        block_lines = [ln]
        for step in (-1, -2):
            k = idx0 + step
            if k < 0:
                break
            ks = lines_list[k].strip()
            if not ks or ks.startswith(("#", "|", "｜", "---", "```")):
                break
            block_lines.insert(0, lines_list[k])
        for step in (1, 2):
            k = idx0 + step
            if k >= len(lines_list):
                break
            ks = lines_list[k].strip()
            if not ks or ks.startswith(("#", "|", "｜", "---", "```")):
                break
            block_lines.append(lines_list[k])
        block_scope = "\n".join(block_lines)
        for m in stat.finditer(ln):
            raw = m.group(0)
            # 序号形式（1~2 位数字紧接句点+空白）直接跳过，避免把「2. 字…」误算成「2 字」
            if re.match(r"^\d{1,2}\.\s", raw):
                continue
            num = re.match(r"[\d,\.]+", raw).group(0)
            if len(num.replace(",", "")) < 2:
                continue
            w = 90 if len(ln) < 400 else 60
            ctx = ln[max(0, m.start() - w): m.end() + w]
            if _SKIP_NUM_CTX.search(ctx) or design.search(ctx):
                continue
            total += 1
            if st.startswith(("|", "｜")):
                scope = " ".join(_table_cells(ln))
                has_src = bool(src.search(scope))
            else:
                has_src = bool(src.search(ctx) or src.search(block_scope))
            if not has_src:
                bad.append((i, num, st[:60]))
    return total, bad


def check_overclaim(text, rules):
    """越级词所在段落是否够 2 处来源。否定/引用语境不算主张。"""
    words = rules.get("overclaim_words") or []
    neg = re.compile(rules.get("overclaim_negation") or "$^")
    src = _src_re(rules)
    bad = []
    for p in re.split(r"\n\s*\n", text):
        if p.lstrip().startswith("#"):
            continue
        hits = [w for w in words if w in p]
        if not hits or neg.search(p):
            continue
        n = len(src.findall(p))
        if n < 2 and len(p) > 30:
            bad.append((" ".join(hits), n, p.strip()[:70]))
    return bad


def check_claims(text, rules):
    """「声称跑过了」必须有可复跑凭证（同段有路径/命令/证据号即可）。"""
    src = _src_re(rules)
    neg = re.compile(rules.get("claim_negation") or "$^")
    bad = []
    for item in rules.get("claim_patterns") or []:
        pat, why = (item[0], item[1] if len(item) > 1 else "声称")
        for m in re.finditer(pat, text):
            near = text[max(0, m.start() - 120): m.end() + 120]
            ps = text.rfind("\n\n", 0, m.start())
            pe = text.find("\n\n", m.end())
            para = text[max(0, ps): (pe if pe > 0 else len(text))]
            if src.search(near) or src.search(para) or neg.search(near):
                continue
            bad.append((why, text[max(0, m.start() - 40): m.end() + 40].replace("\n", " ")))
    return bad


def check_sections(text, rules):
    """结构项：缺口章节、反向质疑条数。"""
    res = []
    gap = re.search(rules.get("gap_section_pattern") or "$^", text)
    res.append(("缺口/未做章节", bool(gap), "存在" if gap else "缺失（没有就补一节「还没做到的」）"))
    pat = rules.get("reverse_question_pattern") or "$^"
    need = int(rules.get("min_reverse_questions") or 3)
    q = len(re.findall(pat, text, re.M))
    res.append((f"反向质疑 ≥{need} 条", q >= need, f"{q} 条"))
    return res


def check_ledger(path=None):
    """台账里有没有「作者自己判自己通过」。"""
    p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_log.md")
    if not os.path.exists(p):
        return None
    bad = []
    with open(p, encoding="utf-8") as f:
        for ln in f:
            if not ln.startswith("|") or not re.search(r"author", ln, re.I):
                continue
            cells = _table_cells(ln)
            verdict = next((c for c in cells if c in ("通过", "重写后通过", "未通过")), "")
            if verdict == "通过":
                bad.append(ln.strip()[:100])
    return bad


def _ensure_utf8_stdio() -> None:
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main():
    _ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="交付前确定性检查（机器可判部分）")
    ap.add_argument("report")
    ap.add_argument("--strict", action="store_true", help="有 FAIL 即退出码 1")
    ap.add_argument("--rules", help="规则文件路径（默认同目录 review_rules.json）")
    ap.add_argument("--audit-mode", action="store_true",
                    help="审的是审核意见本身（额外要求带审核凭证行）")
    a = ap.parse_args()

    if not os.path.exists(a.report):
        print("❌ 报告不存在: %s" % a.report)
        return 2
    rules = load_rules(a.rules)
    with open(a.report, encoding="utf-8") as f:
        text = f.read()

    results = []  # (key, label, passed, detail)

    total, bad = check_numbers(text, rules)
    ratio = (len(bad) / total) if total else 0.0
    thr = float((rules.get("number_check") or {}).get("max_unsourced_ratio") or 0.3)
    results.append(("numbers", "数字带来源标注", ratio <= thr,
                    "%d 个统计量中 %d 个附近无来源（%.0f%%，阈值 %.0f%%）"
                    % (total, len(bad), ratio * 100, thr * 100)
                    + ("；例：" + "; ".join("L%d「%s」" % (i, n) for i, n, _ in bad[:3]) if bad else "")))

    cl = check_claims(text, rules)
    ev = check_evidence_binding(text, rules)
    cl = cl + [(w, d) for w, d in ev]
    results.append(("claims", "声称类有可复跑凭证", not cl,
                    "无裸露声称" if not cl else "；".join("%s 无凭证" % w for w, _ in cl[:3])))

    oc = check_overclaim(text, rules)
    results.append(("overclaim", "越级词有证据支撑", not oc,
                    "无越级词或均有 ≥2 处来源" if not oc else
                    "；".join("「%s」仅 %d 处来源" % (w, s) for w, s, _ in oc[:3])))

    for name, (label, okd, det) in zip(("gap_section", "reverse"), check_sections(text, rules)):
        results.append((name, label, okd, det))

    lb = check_ledger()
    if lb is not None:
        results.append(("ledger", "台账无作者自判通过", not lb,
                        "干净" if not lb else "%d 条：%s" % (len(lb), lb[0])))

    if a.audit_mode:
        has = bool(re.search(r"审核上下文[:：]", text))
        results.append(("audit_line", "审核凭证行", has, "存在" if has else "缺失"))

    fail_on = set(rules.get("fail_on") or [])
    warn_on = set(rules.get("warn_on") or [])
    fails, warns = [], []
    print("=" * 78)
    print("确定性检查 · %s" % os.path.basename(a.report))
    print("规则：%s" % (a.rules or os.path.basename(RULES_FILE)))
    print("=" * 78)
    for key, label, okd, detail in results:
        if okd:
            mark = "✅"
        elif key in fail_on:
            mark = "❌ 硬拦"
        elif key in warn_on:
            mark = "⚠️ 提示"
        else:
            mark = "·"
        print("  %-8s %-2s %-18s %s" % (mark, "", label, detail))
        if not okd:
            (fails if key in fail_on else warns).append(label)
    print("-" * 78)
    print("硬拦 FAIL %d 项%s ｜ 提示 WARN %d 项%s"
          % (len(fails), ("：" + "、".join(fails)) if fails else "",
             len(warns), ("：" + "、".join(warns)) if warns else ""))
    print("⚠️ 本脚本只查形式与可核对性，查不出「结论是否真的对」——人工审不能省。")
    if a.strict and fails:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
