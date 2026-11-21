# -*- coding: utf-8 -*-
"""商品实体核对：把「标题」拆成品牌 / 型号 / 版本后缀 / 容量 / 颜色，判断两条价格记录是不是同一件东西。

为什么单独写：决赛圈核价最容易犯的错不是抓不到价，而是把
「Comfo Clip Q2」的价套到「Fit900NB」头上、或者把「小米14 Pro」的价当成「小米14」，
品牌一样、名字都带英文或都带数字，人眼一瞟就过去了，最后报出去的最低价是另一个型号的。

这个脚本只做一件确定性的事：字段级比对。能判就判，判不出来就 unknown，
绝不用「看起来像」来凑结论。

用法：
  python tools/sku_check.py --target "sanag 塞那 Comfo Clip Q2 蓝牙耳机 黑色"
  python tools/sku_check.py --target "..." --cand "渠道A ... 379 元" --cand "渠道B ... 351.12 元"
  python tools/sku_check.py --target "..." --cands-json prices.json --json

退出码：0 = 正常；3 = 出现字段冲突（--strict 时）
"""
import argparse
import json
import os
import re
import sys
import unicodedata

# 品牌按「同一品牌的多种写法」分组：只要命中组内任一写法就算同一个品牌。
BRAND_GROUPS = [
    ["sanag", "塞那"],
    ["apple", "苹果"],
    ["huawei", "华为"],
    ["xiaomi", "小米", "mi"],
    ["redmi", "红米"],
    ["honor", "荣耀"],
    ["oppo", "欧珀"],
    ["vivo", "维沃"],
    ["oneplus", "一加"],
    ["realme", "真我"],
    ["meizu", "魅族"],
    ["sony", "索尼"],
    ["sennheiser", "森海塞尔"],
    ["edifier", "漫步者"],
    ["baseus", "倍思"],
    ["ugreen", "绿联"],
    ["anker", "安克"],
    ["soundcore", "声阔"],
    ["lenovo", "联想"],
    ["dell", "戴尔"],
    ["asus", "华硕"],
    ["acer", "宏碁"],
    ["msi", "微星"],
    ["logitech", "罗技"],
    ["razer", "雷蛇"],
    ["nike", "耐克"],
    ["adidas", "阿迪达斯"],
    ["uniqlo", "优衣库"],
    ["philips", "飞利浦"],
    ["midea", "美的"],
    ["gree", "格力"],
    ["haier", "海尔"],
    ["dyson", "戴森"],
    ["roborock", "石头"],
    ["ecovacs", "科沃斯"],
    ["bose"],
    ["jbl"],
    ["keychron"],
    ["nuphy"],
    ["thinkpad"],
    ["thinkbook"],
    ["macbook"],
    ["ipad"],
    ["iphone"],
]


def _load_extra_brands() -> None:
    """从同目录 sku_rules.json 增量加载日化/家电/相机/外设品牌组。"""
    rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sku_rules.json")
    if not os.path.isfile(rules_path):
        return
    try:
        with open(rules_path, encoding="utf-8") as f:
            data = json.load(f)
        seen = {tuple(g) for g in BRAND_GROUPS}
        for grp in (data.get("extra_brand_groups") or []):
            if isinstance(grp, list) and grp:
                clean = [str(x).strip().lower() for x in grp if str(x).strip()]
                if clean and tuple(clean) not in seen:
                    BRAND_GROUPS.append(clean)
                    seen.add(tuple(clean))
    except Exception:
        pass


_load_extra_brands()

BRANDS = sorted({b for g in BRAND_GROUPS for b in g}, key=len, reverse=True)

# 颜色词。单字（黑/白/金…）容易撞上「白条」「黑卡」「金卡」这类词，
# 所以先按 _COLOR_TRAPS 把陷阱词抹掉，再按「长词优先」匹配。
COLORS = {
    "黑": ["黑", "black", "曜石黑", "幻夜黑", "典雅黑"],
    "白": ["白", "white", "珍珠白", "雪域白", "陶瓷白"],
    "银": ["银", "silver", "星光色", "starlight", "star light"],
    "灰": ["灰", "gray", "grey", "深空灰", "space gray", "space grey"],
    "金": ["金", "gold", "香槟金"],
    "蓝": ["蓝", "blue", "远峰蓝", "海军蓝"],
    "绿": ["绿", "green", "苍岭绿", "暗夜绿"],
    "红": ["红", "red", "product red"],
    "粉": ["粉", "pink", "玫瑰金", "rose gold"],
    "紫": ["紫", "purple", "lavender"],
}
_COLOR_TRAPS = ["蓝牙", "蓝光", "蓝奏", "蓝月亮", "立白", "漂白", "增白", "亮白", "净白",
                "美白", "洁白", "白醋", "白条", "白金", "白嫖", "黑卡", "黑科技",
                "红包", "粉丝", "紫外线", "银河", "银河系", "黑白", "金牌", "金卡"]

# 版本后缀：Pro / Max / 青春版 这些不进任何数字字段，必须单独比。
SUFFIXES = ["pro max", "pro+", "青春版", "至臻版", "典藏版", "尊享版", "大师版",
            "至尊版", "增强版", "标准版", "电竞版", "折叠屏", "pro", "max", "ultra",
            "plus", "se", "mini", "lite", "neo", "air"]

# 代次：第2代 / 2代 / 2024款 / Gen2 / Mk2。同名不同代是两件货。
_RE_EDITION = re.compile(
    r"第\s*([0-9一二三四五六七八九十]{1,3})\s*代|(?<!\d)(\d{1,2})\s*代|"
    r"(20\d{2})\s*款|\bgen\s*(\d{1,2})\b|\bmk\s*(\d{1,2})\b",
    re.I,
)
_CN_NUM = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
           "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}

# 包装形态：套装和单机、套件(空壳无轴)和成品(含轴含帽)不是一个价，不能混着比
PACKAGING = {
    "套装": ["套装", "礼盒", "组合装", "two pack", "2件套", "三件套"],
    "单机": ["单机", "裸机", "单主机", "不含配件", "官方标配"],
    "桶装": ["桶装", "罐装"],
    "袋装": ["袋装", "补充装", "替换装"],
    "套件": ["套件", "空壳", "无轴", "不含轴", "准系统", "barebone"],
    "成品": ["成品", "整机", "含轴", "带轴", "含轴帽"],
}

_RE_COMPOUND = re.compile(
    r"(?<![a-z0-9])(\d{1,5}(?:\.\d+)?)\s*"
    r"(ml|l|kg|g|千克|公斤|克|抽|片|颗|粒|张|包|袋|瓶|盒)"
    r"(?:/[包袋盒瓶])?\s*[×xX\*]\s*(\d{1,4})"
    r"(?:\s*(包|袋|盒|瓶|桶|件|箱|卷|提|套|组))?",
    re.I,
)
_RE_CAP = re.compile(
    r"(?<![a-z0-9])(\d{1,5}(?:\.\d+)?)\s*(mah|wh|tb|t|gb|mb|ml|l|kg|g|千克|公斤|克)(?![a-z])", re.I)
_RE_COUNT_CAP = re.compile(
    r"(?<![a-z0-9切照芯胶卡镜贴图影])(\d{1,5})\s*(抽|片|颗|粒)(?![a-z\u4e00-\u9fff])", re.I)
# 国产手机常见写法「12+256」「8+128」：前一个是内存、后一个是存储。
_RE_PLUS = re.compile(r"(?<![\d.])(\d{1,3})\s*\+\s*(\d{2,4})(?![\d.])(?!\s*(?:元|块|券|折|积分))")
_PLUS_STORAGE = {64, 128, 256, 512, 1024, 2048, 4096}
# 型号：必须含字母，允许 Q2 / Fit900NB / WH-1000XM5 / A15 / GT3 这类
_RE_MODEL = re.compile(r"(?<![a-z0-9])([a-z]{1,8}[-\s]?\d{1,5}[a-z0-9-]*)(?![a-z0-9])", re.I)
_MODEL_NOISE_RE = re.compile(
    r"^(?:IP\d{2}[A-Z]?|BT\d+(?:\.\d+)?|USB\d+(?:\.\d+)?|PD\d+W?|QC\d+(?:\.\d+)?|"
    r"WIFI\d*|TYPEC\d*|NFC\d*|HDMI\d*|ATX\d*|V\d+\.\d+|\d+W)$", re.I)
_SUFFIX_SPACE_NUM_RE = re.compile(
    r"^(?:pro|max|ultra|plus|mini|lite|air|se|neo)\s+\d+(?:gb|tb|mb|mah|wh|w|hz|ms|k)?$",
    re.I,
)
# 系列数字：小米14 / 荣耀100 这种没有字母的型号。
_RE_NUM = re.compile(r"(?<![\d.])(\d{2,4})(?![\d.])")
_RE_PRICE = re.compile(
    r"(?:(?:到手|券后|实付|折后|补贴后|特价|低至|约|¥|￥)\s*[:：]?\s*)?(\d{1,6}(?:\.\d{1,2})?)\s*(?:元|块)|(?:¥|￥)\s*(\d{1,6}(?:\.\d{1,2})?)"
)

STRONG_FIELDS = ("型号", "系列数字", "容量", "净含量", "重量", "抽数/片数", "代次")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = s.lower()
    s = re.sub(r"[（(【\[)）】\]]", " ", s)
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff.+]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _brand_of(n: str) -> str:
    """返回品牌组里的代表写法；同一品牌的不同语言写法归一到一起。"""
    for group in BRAND_GROUPS:
        for alias in sorted(group, key=len, reverse=True):
            if alias in n:
                return group[0]
    return ""


def extract_price(text: str) -> float | None:
    """从标题或价格串中确定性提取价格数值。"""
    s = str(text or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{1,6}(?:\.\d{1,2})?", s):
        return float(s)
    m = _RE_PRICE.search(s)
    if not m:
        return None
    val = m.group(1) or m.group(2)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _expand_compound_specs(raw: str) -> tuple[str, list[str], int]:
    """先在保留乘号的文本里折算「500g*2袋」「250ml×12盒」「80抽*20包」。"""
    norm_raw = unicodedata.normalize("NFKC", str(raw or "")).lower()
    counts = []
    total_count = 0

    def _repl(m):
        nonlocal total_count
        try:
            num = float(m.group(1))
            mult = int(m.group(3))
        except (TypeError, ValueError):
            return m.group(0)
        u = m.group(2).lower()
        if u in ("ml", "l"):
            ml = num * (1000.0 if u == "l" else 1.0) * mult
            return f" {ml:g}ml "
        if u in ("kg", "千克", "公斤", "g", "克"):
            grams = num * (1000.0 if u in ("kg", "千克", "公斤") else 1.0) * mult
            return f" {grams:g}g "
        tot = int(round(num * mult))
        if tot > 0:
            total_count += tot
            counts.append(f"{tot}{u}")
        return " "

    expanded = _RE_COMPOUND.sub(_repl, norm_raw)
    return expanded, counts, total_count


def parse_sku(title: str) -> dict:
    """从标题里抽字段。抽不到就留空 —— 留空比猜错安全。"""
    raw = str(title or "")
    expanded_raw, comp_counts, comp_total_count = _expand_compound_specs(raw)
    n = _norm(expanded_raw)

    brand = _brand_of(n)

    caps = []
    total_weight_g = 0.0
    total_volume_ml = 0.0
    total_count = comp_total_count
    counts = list(comp_counts)
    for val, unit in _RE_CAP.findall(n):
        u = unit.lower()
        try:
            num = float(val)
        except ValueError:
            continue
        if num <= 0:
            continue
        if u == "g" and int(num) in (4, 5) and ("4g" in n or "5g" in n) and "克" not in raw:
            continue
        if u in ("tb", "t"):
            gb_num = num * 1024
            caps.append(("storage", "%dGB" % int(round(gb_num))))
        elif u == "gb":
            caps.append(("storage", "%dGB" % int(round(num))))
        elif u == "mb":
            caps.append(("storage", "%dMB" % int(round(num))))
        elif u == "mah":
            caps.append(("storage", "%dmAh" % int(round(num))))
        elif u == "wh":
            caps.append(("storage", "%gWh" % num))
        elif u == "ml":
            total_volume_ml += float(num)
            caps.append(("volume", "%gML" % round(num, 3)))
        elif u == "l":
            ml = round(num * 1000, 3)
            total_volume_ml += float(ml)
            caps.append(("volume", "%gML" % ml))
        elif u in ("kg", "千克", "公斤"):
            g_val = round(num * 1000, 3)
            total_weight_g += float(g_val)
            caps.append(("weight", "%gg" % g_val))
        elif u in ("g", "克"):
            g_val = round(num, 3)
            total_weight_g += float(g_val)
            caps.append(("weight", "%gg" % g_val))
    for c_val, c_unit in _RE_COUNT_CAP.findall(n):
        try:
            c_num = int(c_val)
        except ValueError:
            continue
        if c_num > 0:
            tag = f"{c_num}{c_unit}"
            if tag not in counts:
                counts.append(tag)
            total_count += c_num
    for a, b in _RE_PLUS.findall(n):
        ia, ib = int(a), int(b)
        if ib in _PLUS_STORAGE and 1 <= ia <= 64:
            caps.append(("storage", "%dGB" % ia))
            caps.append(("storage", "%dGB" % ib))

    storages, volumes, weights = [], [], []
    for k, v in caps:
        if k == "storage" and v not in storages:
            storages.append(v)
        if k == "volume" and v not in volumes:
            volumes.append(v)
        if k == "weight" and v not in weights:
            weights.append(v)

    n_color = re.sub(
        r"(?:快金|金粉|白菜豆腐|抹茶拿铁|灰木|赤兔|紫云|冰蓝|冰影|黛粉|超茶|青白|"
        r"红|茶|黑|青|白|银|绿|粉|蓝|灰|黄|紫|棕|金)[\u4e00-\u9fff]{0,2}轴(?:\s*v\d+(?:\.\d+)?)?",
        " ",
        n,
    )
    for t in _COLOR_TRAPS:
        n_color = n_color.replace(t, " ")
    n_color = re.sub(
        r"(?:彩漂|洗衣|漂白|去污|亮白|奶|淀粉|面|爽身|花|藕|可可|胡椒|孜然|五香|辣椒|豆|果|铁|老|路人)粉",
        " ",
        n_color,
    )
    color_zh = ""
    pairs = sorted(((w, zh) for zh, ws in COLORS.items() for w in ws),
                   key=lambda x: len(x[0]), reverse=True)
    for w, zh in pairs:
        if w in n_color:
            color_zh = zh
            break

    suffixes = []
    for s in sorted(SUFFIXES, key=len, reverse=True):
        pat = r"(?<![a-z])%s(?![a-z])" % re.escape(s) if re.match(r"^[a-z+ ]+$", s) else re.escape(s)
        if re.search(pat, n) and s not in suffixes:
            suffixes.append(s)
    suffixes = [s for s in suffixes
                if not any(s != o and s in o for o in suffixes)]
    suffixes = [s for s in suffixes if s != "标准版"]

    n_no_switch_ver = re.sub(r"轴\s*v\d+(?:\.\d+)?", "轴 ", n)

    models = []
    v_tokens = []
    for m in _RE_MODEL.finditer(n_no_switch_ver):
        raw_m = m.group(0).strip()
        if _SUFFIX_SPACE_NUM_RE.match(raw_m):
            continue
        t = re.sub(r"\s+", "", raw_m).upper()
        if re.fullmatch(r"\d+", t):
            continue
        if re.fullmatch(r"(GB|TB|ML|MB|KG|L|G|HZ|MS|GF|MAH|WH)", t):
            continue
        if _MODEL_NOISE_RE.match(t):
            continue
        if re.fullmatch(r"V\d{1,2}", t):
            if t not in v_tokens:
                v_tokens.append(t)
            continue
        if t not in models:
            models.append(t)

    n_num = n
    for m in _RE_CAP.finditer(n):
        n_num = n_num.replace(m.group(0), " ")
    for m in _RE_COUNT_CAP.finditer(n):
        n_num = n_num.replace(m.group(0), " ")
    for a, b in _RE_PLUS.findall(n):
        n_num = n_num.replace("%s+%s" % (a, b), " ")
        n_num = n_num.replace("%s + %s" % (a, b), " ")
    nums = []
    for m in _RE_NUM.finditer(n_num):
        v = m.group(1)
        iv = int(v)
        if 1990 <= iv <= 2100:
            continue
        if re.match(
            r"\s*(?:元|块|价|%|期|个月|月|年|天|日|小时|周|件|次|键|层|档|折|"
            r"mm|cm|khz|hz|ms|gf|mah|wh|w|万|千|倍)(?![a-z0-9])",
            n_num[m.end():m.end() + 6],
            re.I,
        ):
            continue
        if re.search(r"(?:满|近|前)\s*$", n_num[max(0, m.start() - 3):m.start()]):
            continue
        if v not in nums:
            nums.append(v)

    edition = []
    for m in _RE_EDITION.finditer(n_no_switch_ver):
        v = m.group(1) or m.group(2) or m.group(3) or m.group(4) or m.group(5)
        v = _CN_NUM.get(v, v)
        if v:
            tag = "%s款" % v if m.group(3) is not None else "%s代" % v
            if tag not in edition:
                edition.append(tag)
    if v_tokens:
        if models:
            for vt in v_tokens:
                ed_tag = "%s代" % vt[1:]
                if ed_tag not in edition:
                    edition.append(ed_tag)
        else:
            for vt in v_tokens:
                if vt not in models:
                    models.append(vt)

    packaging = ""
    for k, words in PACKAGING.items():
        if any(w in n for w in words):
            packaging = k
            break

    return {"raw": raw, "brand": brand, "models": models, "nums": nums,
            "suffixes": suffixes, "edition": edition, "packaging": packaging,
            "storages": storages, "volumes": volumes, "weights": weights,
            "counts": counts,
            "storage": "/".join(storages), "volume": "/".join(volumes),
            "weight": "/".join(weights), "count": "/".join(counts),
            "total_weight_g": round(total_weight_g, 3),
            "total_volume_ml": round(total_volume_ml, 3),
            "total_count": int(total_count),
            "price": extract_price(raw),
            "color": color_zh}


def compute_unit_cost(sku_or_title, price=None, dose: str = "") -> dict:
    """确定性单次使用成本与单位折算价（杜绝大模型口算小数点错误）。"""
    parsed = parse_sku(sku_or_title) if isinstance(sku_or_title, str) else dict(sku_or_title or {})
    price_val = float(price) if price not in (None, "") else parsed.get("price")
    out = {
        "price": price_val,
        "total_weight_g": float(parsed.get("total_weight_g") or 0.0),
        "total_volume_ml": float(parsed.get("total_volume_ml") or 0.0),
        "total_count": int(parsed.get("total_count") or 0),
        "per_500g": None,
        "per_100ml": None,
        "per_100count": None,
        "servings": None,
        "cost_per_use": None,
    }
    if not price_val or price_val <= 0:
        return out
    if out["total_weight_g"] > 0:
        out["per_500g"] = round(price_val / (out["total_weight_g"] / 500.0), 4)
    if out["total_volume_ml"] > 0:
        out["per_100ml"] = round(price_val / (out["total_volume_ml"] / 100.0), 4)
    if out["total_count"] > 0:
        out["per_100count"] = round(price_val / (out["total_count"] / 100.0), 4)
    if dose:
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(kg|g|千克|公斤|克|l|ml|抽|片|颗|粒|张|包|袋|瓶|盒)?\s*$", str(dose), re.I)
        if m:
            d_num = float(m.group(1))
            d_u = (m.group(2) or "").lower()
            total_base = 0.0
            if d_u in ("kg", "千克", "公斤"):
                d_num *= 1000.0
                total_base = out["total_weight_g"]
            elif d_u in ("g", "克"):
                total_base = out["total_weight_g"]
            elif d_u == "l":
                d_num *= 1000.0
                total_base = out["total_volume_ml"]
            elif d_u == "ml":
                total_base = out["total_volume_ml"]
            elif d_u:
                total_base = float(out["total_count"])
            else:
                total_base = out["total_weight_g"] or out["total_volume_ml"] or float(out["total_count"])
            if d_num > 0 and total_base > 0:
                servings = total_base / d_num
                out["servings"] = round(servings, 2)
                out["cost_per_use"] = round(price_val / servings, 4)
    return out


def match_sku(target: dict, cand: dict) -> dict:
    """字段级比对。verdict: match / mismatch / unknown。

    规则：
      · 任一同名字段冲突 → mismatch（硬拦）
      · 无冲突 + 至少 2 个字段一致 + 至少一个「强字段」一致 → match
      · 其余 → unknown（不能拿它当最低价依据）
    """
    agree, conflict, missing = [], [], []

    def cmp(field, label):
        a, b = target.get(field), cand.get(field)
        if field in ("suffixes", "edition"):
            sa, sb = set(a or []), set(b or [])
            if not sa and not sb:
                missing.append(label)
            elif sa == sb:
                agree.append(label)
            else:
                conflict.append("%s不一致（%s ≠ %s）"
                                % (label, "/".join(sorted(sa)) or "无",
                                   "/".join(sorted(sb)) or "无"))
            return
        if field in ("models", "storages", "volumes", "weights", "counts", "nums"):
            if not a or not b:
                missing.append(label)
                return
            sa, sb = set(a), set(b)
            if sa == sb:
                agree.append(label)
            else:
                conflict.append("%s不一致（%s ≠ %s）"
                                % (label, "/".join(a), "/".join(b)))
            return
        if field == "packaging":
            if a and b and str(a) != str(b):
                conflict.append("%s不一致（%s ≠ %s）" % (label, a, b))
            elif a and b:
                agree.append(label)
            else:
                missing.append(label)
            return
        if not a or not b:
            missing.append(label)
            return
        if str(a) == str(b):
            agree.append(label)
        else:
            conflict.append("%s不一致（%s ≠ %s）" % (label, a, b))

    cmp("brand", "品牌")
    cmp("models", "型号")
    cmp("nums", "系列数字")
    cmp("suffixes", "版本后缀")
    cmp("edition", "代次")
    cmp("packaging", "包装")
    cmp("storages", "容量")
    cmp("volumes", "净含量")
    cmp("weights", "重量")
    cmp("counts", "抽数/片数")
    cmp("color", "颜色")

    strong = [f for f in agree if f in STRONG_FIELDS]
    if conflict:
        verdict = "mismatch"
    elif len(agree) >= 2 and strong:
        verdict = "match"
    else:
        verdict = "unknown"

    return {"verdict": verdict, "agree": agree, "conflict": conflict,
            "missing": missing, "strong": strong,
            "target": target, "candidate": cand}


def _fmt_line(r: dict, price: str = "") -> str:
    c = r["candidate"]
    name = c["raw"][:46].replace("\n", " ")
    tag = {"match": "✅ 同款", "mismatch": "❌ 不同型号", "unknown": "❔ 判不出"}[r["verdict"]]
    if r["conflict"]:
        extra = "；".join(r["conflict"])
    elif r["verdict"] == "unknown":
        extra = "缺强字段（型号/系列数字/容量都没对上）"
    else:
        extra = ""
    p = (" %s" % price) if price else ""
    return "  %s%s ｜ %s%s" % (tag, p, name, (" ｜ " + extra) if extra else "")


def _load_cands(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        for k in ("items", "candidates", "results", "data"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
        else:
            data = [data]
    out = []
    for d in data:
        if isinstance(d, str):
            out.append({"title": d, "price": ""})
        elif isinstance(d, dict):
            out.append({"title": d.get("title") or d.get("name") or "",
                        "price": d.get("price") or ""})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="商品实体核对（品牌/型号/后缀/容量/颜色）")
    ap.add_argument("--target", required=True, help="目标商品标题（决赛圈那一款）")
    ap.add_argument("--cand", action="append", default=[],
                    help="候选价格记录标题，可重复传")
    ap.add_argument("--cands-json", help='JSON 文件：[{"title":..,"price":..}] 或纯字符串数组')
    ap.add_argument("--dose", default="", help="单次用量（如 25g / 20ml / 2抽），确定性算出单次成本并对比高低倍数")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--strict", action="store_true", help="出现 mismatch 时退出码 3")
    a = ap.parse_args(argv)

    t = parse_sku(a.target)
    items = [{"title": c, "price": ""} for c in a.cand]
    if a.cands_json:
        items.extend(_load_cands(a.cands_json))
    if not items:
        out = dict(t)
        if a.dose or t.get("price"):
            out["unit_cost"] = compute_unit_cost(t, dose=a.dose)
        print("没有候选，只解析目标：")
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    results = []
    for it in items:
        cand_parsed = parse_sku(it["title"])
        res = match_sku(t, cand_parsed)
        p_override = extract_price(str(it.get("price") or ""))
        if p_override is not None or cand_parsed.get("price") is not None:
            res["unit_cost"] = compute_unit_cost(cand_parsed, price=p_override, dose=a.dose)
        results.append(res)

    if a.json:
        print(json.dumps({"target": t, "results": results}, ensure_ascii=False, indent=2))
    else:
        print("目标：%s" % a.target)
        print("  解析 → 品牌=%s ｜ 型号=%s ｜ 系列数字=%s ｜ 后缀=%s ｜ 容量=%s ｜ 净含量=%s ｜ 重量=%s ｜ 抽片=%s ｜ 颜色=%s"
              % (t["brand"] or "?", "/".join(t["models"]) or "?",
                 "/".join(t["nums"]) or "?", "/".join(t["suffixes"]) or "?",
                 t["storage"] or "?", t["volume"] or "?", t["weight"] or "?",
                 t["count"] or "?", t["color"] or "?"))
        print("候选：")
        for r, it in zip(results, items):
            line = _fmt_line(r, str(it.get("price") or ""))
            uc = r.get("unit_cost") or {}
            if uc.get("cost_per_use") is not None:
                line += f" ｜ 单次 ¥{uc['cost_per_use']:.2f} ({uc['servings']}次)"
            elif uc.get("per_500g") is not None:
                line += f" ｜ 折合 ¥{uc['per_500g']:.2f}/斤"
            print(line)
        n_mis = sum(1 for r in results if r["verdict"] == "mismatch")
        n_unk = sum(1 for r in results if r["verdict"] == "unknown")
        print("\n小结：%d 条同款 ｜ %d 条不同型号（禁止拿来比价）｜ %d 条判不出（缺强字段，需人工确认）"
              % (len(results) - n_mis - n_unk, n_mis, n_unk))
        priced_matches = [
            r["unit_cost"]["cost_per_use"] for r in results
            if r["verdict"] == "match" and (r.get("unit_cost") or {}).get("cost_per_use")
        ]
        if len(priced_matches) >= 2:
            hi, lo = max(priced_matches), min(priced_matches)
            if lo > 0:
                print("成本对比：贵的那款单次要 %.2f 元，便宜这款 %.2f 元，差 %.1f 倍。" % (hi, lo, hi / lo))
        if n_unk:
            print("提示：判不出的条目不能直接进最低价结论，先把型号（含 Pro/Max 等后缀）补全再比。")

    if a.strict and any(r["verdict"] == "mismatch" for r in results):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
