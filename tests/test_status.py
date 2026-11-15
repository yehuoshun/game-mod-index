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

    def test_render_is_deterministic(self):
        data = {"synced_at": "2026-11-15T15:00:00Z", "mods": {}}
        rows = [self._row("A", 100), self._row("B", 5, "active", False)]
        first = modindex.render_readme(self.cfg, rows, data)
        second = modindex.render_readme(self.cfg, rows, data)
        self.assertEqual(first, second)


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
