import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import modindex  # noqa: E402

CFG = {
    "freshness": {"active_within_days": 30, "watch_within_days": 90, "stale_within_days": 180}
}


class BucketTests(unittest.TestCase):
    def test_boundaries(self):
        cases = {
            0: "active",
            30: "active",
            31: "watch",
            90: "watch",
            91: "stale",
            180: "stale",
            181: "dead",
            900: "dead",
        }
        for days, expected in cases.items():
            with self.subTest(days=days):
                self.assertEqual(modindex.bucket_for(days, CFG), expected)

    def test_none_is_unknown(self):
        self.assertEqual(modindex.bucket_for(None, CFG), "unknown")


class LocalDateTests(unittest.TestCase):
    def test_utc_rolls_into_next_local_day(self):
        tz = modindex.timezone(__import__("datetime").timedelta(hours=8))
        # UTC 2026-11-14 20:00 == 北京 2026-11-15 04:00
        self.assertEqual(
            modindex.local_date("2026-11-14T20:00:00Z", tz).isoformat(), "2026-11-15"
        )

    def test_plain_date_passthrough(self):
        tz = modindex.timezone(__import__("datetime").timedelta(hours=8))
        self.assertEqual(modindex.local_date("2026-11-15", tz).isoformat(), "2026-11-15")

    def test_garbage_is_none(self):
        tz = modindex.timezone(__import__("datetime").timedelta(hours=8))
        self.assertIsNone(modindex.local_date("不是日期", tz))
        self.assertIsNone(modindex.local_date(None, tz))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.cfg = modindex.load_config()
        self.tz = modindex.tz_of(self.cfg)

    def _row(self, name, days, status="stale", attention=True):
        entry = {
            "id": name.lower(),
            "name": name,
            "_game": "sts2",
            "kind": "mod",
            "summary": "示例 | 带竖线",
        }
        meta = {
            "html_url": f"https://github.com/x/{name}",
            "pushed_at": "2026-01-01T00:00:00Z",
            "latest_release": None,
        }
        return modindex.Row(entry=entry, meta=meta, status=status, days=days, attention=attention)

    def test_attention_sorted_oldest_first(self):
        text = modindex.render_attention([self._row("A", 100), self._row("B", 300)], self.cfg)
        self.assertLess(text.index("B"), text.index("A"))

    def test_attention_empty_has_positive_text(self):
        text = modindex.render_attention([self._row("A", 1, "active", False)], self.cfg)
        self.assertIn("没有需要关注", text)

    def test_table_escapes_pipe(self):
        text = modindex.render_tables([self._row("A", 100)], self.cfg)
        self.assertIn("示例 \\| 带竖线", text)

    def test_render_readme_leaves_no_placeholder(self):
        data = {"synced_at": "2026-11-15T15:00:00Z", "mods": {}}
        text = modindex.render_readme(self.cfg, [self._row("A", 100)], data)
        self.assertNotIn("{{", text)
        # 北京时区 2026-11-15 23:00，验证 synced_at 的时区换算
        self.assertIn("2026-11-15 23:00", text)

    def test_attention_block_below_tables(self):
        # 「需要关注」是告警块，必须排在「全部 Mod」之后，整页读序才是 活跃→停更
        data = {"synced_at": "2026-11-15T15:00:00Z", "mods": {}}
        text = modindex.render_readme(self.cfg, [self._row("A", 100)], data)
        self.assertLess(text.index("## 📚 全部 Mod"), text.index("## 🔔 需要关注"))

    def test_render_is_deterministic(self):
        data = {"synced_at": "2026-11-15T15:00:00Z", "mods": {}}
        rows = [self._row("A", 100), self._row("B", 5, "active", False)]
        first = modindex.render_readme(self.cfg, rows, data)
        second = modindex.render_readme(self.cfg, rows, data)
        self.assertEqual(first, second)


class BomTests(unittest.TestCase):
    """Windows 上手滑保存成「UTF-8 带 BOM」不该让每日核查整天挂掉。"""

    def setUp(self):
        self.tmp = modindex.ROOT / "tmp"
        self.tmp.mkdir(exist_ok=True)
        self.file = self.tmp / "bom-probe.json"

    def tearDown(self):
        self.file.unlink(missing_ok=True)

    def test_read_text_strips_bom(self):
        self.file.write_bytes(b"\xef\xbb\xbf" + b'{"a": 1}')
        self.assertEqual(modindex.read_text(self.file), '{"a": 1}')
        self.assertEqual(__import__("json").loads(modindex.read_text(self.file)), {"a": 1})


class SortTests(unittest.TestCase):
    """主表格排序由 config.yaml 的 table_order 控制，两种顺序都要能排对。"""

    NAMES = ("Fresh", "Mid", "Old", "Unknown")

    def _rows(self):
        rows = []
        for name, days in (("Fresh", 1), ("Mid", 40), ("Old", 200), ("Unknown", None)):
            entry = {"id": name.lower(), "name": name, "_game": "sts2", "kind": "mod"}
            meta = {"html_url": f"https://github.com/x/{name}", "pushed_at": "2026-01-01T00:00:00Z"}
            rows.append(
                modindex.Row(
                    entry=entry,
                    meta=meta,
                    status="unknown" if days is None else "active",
                    days=days,
                    attention=False,
                )
            )
        return rows

    def _order(self, mode):
        cfg = dict(modindex.load_config())
        cfg["table_order"] = mode
        text = modindex.render_tables(self._rows(), cfg)
        return sorted(self.NAMES, key=lambda n: text.index(f"[{n}]"))

    def test_newest_first(self):
        self.assertEqual(self._order("newest_first"), ["Fresh", "Mid", "Old", "Unknown"])

    def test_oldest_first(self):
        self.assertEqual(self._order("oldest_first"), ["Old", "Mid", "Fresh", "Unknown"])

    def test_unknown_always_last(self):
        for mode in ("newest_first", "oldest_first"):
            with self.subTest(mode=mode):
                self.assertEqual(self._order(mode)[-1], "Unknown")

    def test_configured_order_is_valid(self):
        self.assertIn(modindex.load_config()["table_order"], modindex.TABLE_ORDERS)


class ConfigTests(unittest.TestCase):
    def test_thresholds_are_90_180(self):
        cfg = modindex.load_config()
        self.assertEqual(cfg["freshness"]["watch_within_days"], 90)
        self.assertEqual(cfg["freshness"]["stale_within_days"], 180)

    def test_every_mod_game_is_declared(self):
        cfg = modindex.load_config()
        for entry in modindex.load_mods(cfg):
            self.assertIn(entry["_game"], cfg["games"], f"{entry.get('id')} 的游戏没在 config 登记")


if __name__ == "__main__":
    unittest.main()
