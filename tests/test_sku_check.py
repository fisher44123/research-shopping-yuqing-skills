# -*- coding: utf-8 -*-
"""Offline unit tests for tools/sku_check.py (all 25 regression groups + unit cost & CLI)."""
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

import sku_check  # noqa: E402


class SkuCheckTests(unittest.TestCase):
    def test_01_to_07_core_earphone_and_phone_matching(self) -> None:
        target_str = "sanag塞那 Comfo Clip Q2 蓝牙耳机 黑色"
        t = sku_check.parse_sku(target_str)
        self.assertEqual(t["brand"], "sanag")
        self.assertIn("Q2", t["models"])
        self.assertEqual(t["color"], "黑")

        # 2. exact match
        r = sku_check.match_sku(t, sku_check.parse_sku("自营 sanag塞那 Comfo Clip Q2 蓝牙耳机 黑色 379元"))
        self.assertEqual(r["verdict"], "match")

        # 3. same brand different model -> mismatch
        r2 = sku_check.match_sku(t, sku_check.parse_sku("店铺B sanag塞那 Fit900NB 蓝牙耳机 黑色 351.12元"))
        self.assertEqual(r2["verdict"], "mismatch")

        # 4 & 5. capacity comparison
        a = sku_check.parse_sku("小米 14 12GB 256GB 黑色")
        b = sku_check.parse_sku("小米 14 12GB 512GB 黑色")
        c = sku_check.parse_sku("小米 14 12GB 256GB 黑色")
        self.assertIn("256GB", a["storages"])
        self.assertIn("12GB", a["storages"])
        self.assertEqual(sku_check.match_sku(a, b)["verdict"], "mismatch")
        self.assertEqual(sku_check.match_sku(a, c)["verdict"], "match")

        # 6. color conflict
        r5 = sku_check.match_sku(t, sku_check.parse_sku("自营 sanag塞那 Comfo Clip Q2 蓝牙耳机 白色 359元"))
        self.assertEqual(r5["verdict"], "mismatch")

        # 7. missing strong field -> unknown
        r6 = sku_check.match_sku(t, sku_check.parse_sku("蓝牙耳机 特价"))
        self.assertEqual(r6["verdict"], "unknown")

    def test_08_to_15_storage_series_suffix_and_traps(self) -> None:
        # 8. storage tokens never enter models
        p = sku_check.parse_sku("Apple MacBook Air 13 M2 16GB 512GB 星光色")
        self.assertIn("M2", p["models"])
        self.assertIn("512GB", p["storages"])
        self.assertIn("16GB", p["storages"])
        self.assertNotIn("16GB", p["models"])

        # 9. 12+512 notation
        t9 = sku_check.parse_sku("小米 14 12GB 256GB 黑色")
        c9 = sku_check.parse_sku("百亿补贴 小米14 12+512 黑色 3599元")
        self.assertIn("512GB", c9["storages"])
        self.assertEqual(sku_check.match_sku(t9, c9)["verdict"], "mismatch")
        self.assertIn("128GB", sku_check.parse_sku("小米14 8+128 蓝色")["storages"])

        # 10. series numbers 14 vs 15
        t10 = sku_check.parse_sku("小米 14 12GB 256GB 黑色")
        c10 = sku_check.parse_sku("品牌店 小米15 12GB 256GB 黑色 4299元")
        self.assertIn("14", t10["nums"])
        self.assertIn("15", c10["nums"])
        self.assertEqual(sku_check.match_sku(t10, c10)["verdict"], "mismatch")

        # 11. price numbers excluded from series nums
        p11 = sku_check.parse_sku("自营 小米14 12GB 256GB 黑色 3999元")
        self.assertNotIn("3999", p11["nums"])
        self.assertNotIn("12", p11["nums"])

        # 12. Pro vs standard edition
        c12 = sku_check.parse_sku("品牌店 小米14 Pro 12GB 256GB 黑色 4299元")
        c12b = sku_check.parse_sku("品牌店 小米14 标准版 12GB 256GB 黑色 3999元")
        self.assertEqual(sku_check.match_sku(t10, c12)["verdict"], "mismatch")
        self.assertEqual(sku_check.match_sku(t10, c12b)["verdict"], "match")

        # 13. brand + color without strong field -> unknown
        t13 = sku_check.parse_sku("sanag 蓝牙耳机 黑色")
        c13 = sku_check.parse_sku("自营 sanag 蓝牙耳机 黑色 199元")
        self.assertEqual(sku_check.match_sku(t13, c13)["verdict"], "unknown")

        # 14. color trap words (白条)
        c14 = sku_check.parse_sku("自营 小米14 12GB+256GB 黑色 可12期白条免息 3799元")
        self.assertEqual(c14["color"], "黑")
        self.assertEqual(sku_check.match_sku(t10, c14)["verdict"], "match")

        # 15. 5G is not 5GB
        p15 = sku_check.parse_sku("小米14 12GB 256GB 5G手机 黑色")
        self.assertNotIn("5GB", p15["storages"])

    def test_16_to_25_aliases_editions_packaging_and_switches(self) -> None:
        # 16. bilingual brand group
        t16 = sku_check.parse_sku("sanag 塞那 Comfo Clip Q2 黑色")
        c16 = sku_check.parse_sku("自营 sanag Comfo Clip Q2 黑色 379元")
        self.assertEqual(sku_check.match_sku(t16, c16)["verdict"], "match")

        # 17. rose gold -> pink, not gold
        self.assertEqual(sku_check.parse_sku("Apple Watch 玫瑰金 41mm")["color"], "粉")

        # 18. edition & packaging
        t18 = sku_check.parse_sku("Apple AirPods Pro 第2代 官方标配")
        c18a = sku_check.parse_sku("自营 AirPods Pro 第2代 官方标配 1499元")
        c18b = sku_check.parse_sku("自营 AirPods Pro 第1代 官方标配 999元")
        c18c = sku_check.parse_sku("自营 AirPods Pro 第2代 套装含保护壳 1599元")
        self.assertEqual(t18["edition"], ["2代"])
        self.assertEqual(sku_check.match_sku(t18, c18a)["verdict"], "match")
        self.assertEqual(sku_check.match_sku(t18, c18b)["verdict"], "mismatch")
        self.assertEqual(sku_check.match_sku(t18, c18c)["verdict"], "mismatch")

        # 19. mAh mismatch
        t19 = sku_check.parse_sku("小米 移动电源 10000mAh")
        c19 = sku_check.parse_sku("自营 小米移动电源 20000mAh 149元")
        self.assertEqual(sku_check.match_sku(t19, c19)["verdict"], "mismatch")

        # 20. multi-spec candidate cannot pass via subset rule
        t20 = sku_check.parse_sku("小米14 12GB 256GB 黑色")
        c20 = sku_check.parse_sku("小米14 12GB 256GB/512GB 黑色")
        self.assertEqual(sku_check.match_sku(t20, c20)["verdict"], "mismatch")

        # 21. coupon noise "满2+128元券"
        p20 = sku_check.parse_sku("小米14 12GB 256GB 黑色 满2+128元券")
        self.assertEqual(p20["storages"], ["12GB", "256GB"])

        # 22. "28天新低" ignored in series nums
        t22 = sku_check.parse_sku("NuPhy Kick75 三模机械键盘")
        c22 = sku_check.parse_sku("NuPhy Kick75 28天新低 439元")
        self.assertNotIn("28", c22["nums"])
        self.assertIn("75", c22["nums"])
        self.assertEqual(sku_check.match_sku(t22, c22)["verdict"], "match")

        # 23. V3 model preserved and kit vs prebuilt blocked
        t23 = sku_check.parse_sku("Keychron V3 Max 87键三模机械键盘 成品")
        c23_ok = sku_check.parse_sku("Keychron V3 Max 成品含轴帽 480元")
        c23_kit = sku_check.parse_sku("Keychron V3 Max 套件 398元")
        self.assertEqual(t23["models"], ["V3"])
        self.assertEqual(sku_check.match_sku(t23, c23_ok)["verdict"], "match")
        self.assertEqual(sku_check.match_sku(t23, c23_kit)["verdict"], "mismatch")

        # 24 & 25. switch color traps & V2/V3 edition
        t24 = sku_check.parse_sku("迈从 G87 V2 87键三模机械键盘 雾桃渐变 快金轴V3")
        c24_same = sku_check.parse_sku("迈从G87 V2 三模Gasket结构雾桃渐变快金轴V3 机械键盘 240.17元")
        c24_v3 = sku_check.parse_sku("迈从G87 V3 雾桃渐变 269元")
        c24_v1 = sku_check.parse_sku("迈从G87 87键三模机械键盘流影黑白菜豆腐轴V2 239元")
        self.assertEqual(t24["color"], "")
        self.assertEqual(t24["edition"], ["2代"])
        self.assertEqual(sku_check.match_sku(t24, c24_same)["verdict"], "match")
        self.assertEqual(sku_check.match_sku(t24, c24_v3)["verdict"], "mismatch")
        self.assertEqual(sku_check.match_sku(t24, c24_v1)["verdict"], "mismatch")
        self.assertEqual(c24_v1["color"], "黑")
        self.assertEqual(c24_v1["edition"], [])

    def test_compound_spec_unit_cost_and_cli_strict(self) -> None:
        uc = sku_check.compute_unit_cost("立白 彩漂粉 500g*2袋 29.9元", dose="25g")
        self.assertEqual(uc["total_weight_g"], 1000.0)
        self.assertEqual(uc["servings"], 40.0)
        self.assertAlmostEqual(uc["per_500g"], 14.95, places=2)
        self.assertAlmostEqual(uc["cost_per_use"], 0.7475, places=4)

        with tempfile.TemporaryDirectory() as tmp:
            cand_file = os.path.join(tmp, "cands.json")
            with open(cand_file, "w", encoding="utf-8") as f:
                json.dump(
                    [{"title": "品牌店 小米14 Pro 12GB 256GB 黑色", "price": "4299"}],
                    f, ensure_ascii=False,
                )
            p = subprocess.run(
                [sys.executable, os.path.join(TOOLS, "sku_check.py"),
                 "--target", "小米 14 12GB 256GB 黑色",
                 "--cands-json", cand_file, "--strict"],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(p.returncode, 3)


if __name__ == "__main__":
    unittest.main()
