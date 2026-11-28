import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "esg-bid-monitor" / "scripts"
MONTHLY_SCRIPTS = ROOT / "esg-monthly-report" / "scripts"


def record(amount, url="https://example.com/1", date="2026-11-01"):
    return {
        "project_name": "P",
        "buyer": "甲",
        "winner": None,
        "amount_wan": amount,
        "publish_date": date,
        "category": "ESG",
        "source_url": url,
    }


class BidScriptsTest(unittest.TestCase):
    def load(self, name):
        path = SCRIPTS / f"{name}.py"
        if not path.exists():
            self.fail(f"missing script: {path}")
        spec = importlib.util.spec_from_file_location(f"{name}_bid_test", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_shared_scripts_are_identical_copies(self):
        for name in ("search_deepseek.py", "md_to_pdf.py"):
            with self.subTest(name=name):
                source = MONTHLY_SCRIPTS / name
                copy = SCRIPTS / name
                if not copy.exists():
                    self.fail(f"missing copied script: {copy}")
                self.assertEqual(source.read_bytes(), copy.read_bytes())

    def test_validate_records_flags_bad_fields(self):
        mod = self.load("validate_records")
        records = [
            record("约1200万", "not-a-url", "2026-13-01"),
            record(120, "https://example.com/b", "2026-11-01"),
        ]
        result = mod.validate_records(records)
        self.assertFalse(result["ok"])
        fields = {v["field"] for v in result["violations"]}
        self.assertTrue({"amount_wan", "publish_date", "source_url"} <= fields)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["valid"], 1)

    def test_validate_records_accepts_null_amount_and_winner(self):
        mod = self.load("validate_records")
        records = [
            record(None, "https://example.com/a"),
            record(120, "https://example.com/b"),
        ]
        result = mod.validate_records(records)
        self.assertTrue(result["ok"])
        self.assertEqual(result["valid"], 2)

    def test_validate_records_flags_duplicate_source_url(self):
        mod = self.load("validate_records")
        records = [
            record(120, "https://example.com/a"),
            record(130, "https://example.com/a"),
        ]
        result = mod.validate_records(records)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any(v["field"] == "source_url" and "重复" in v["reason"] for v in result["violations"])
        )

    def test_validate_records_rejects_non_string_fields_and_zero_amount(self):
        mod = self.load("validate_records")
        records = [
            {
                "project_name": 123,
                "buyer": ["甲"],
                "winner": 456,
                "amount_wan": 0,
                "publish_date": "2026-11-01",
                "category": "ESG",
                "source_url": "https://example.com/a",
            }
        ]
        result = mod.validate_records(records)
        self.assertFalse(result["ok"])
        fields = {v["field"] for v in result["violations"]}
        self.assertTrue({"project_name", "buyer", "winner", "amount_wan"} <= fields)

    def test_validate_records_rejects_null_required_fields(self):
        mod = self.load("validate_records")
        records = [
            {
                "project_name": "P",
                "buyer": "甲",
                "winner": None,
                "amount_wan": None,
                "publish_date": None,
                "category": None,
                "source_url": "https://example.com/a",
            }
        ]
        result = mod.validate_records(records)
        self.assertFalse(result["ok"])
        fields = {v["field"] for v in result["violations"]}
        self.assertTrue({"publish_date", "category"} <= fields)

    def test_validate_records_rejects_dict_without_records_key(self):
        mod = self.load("validate_records")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wrong.json"
            path.write_text('{"query": "x", "results": []}', encoding="utf-8")
            with self.assertRaises(ValueError):
                mod._load_records(str(path))

    def test_validate_records_keeps_non_tracking_query_params(self):
        mod = self.load("validate_records")
        records = [
            record(120, "https://example.com/a?id=1&utm_source=x"),
            record(130, "https://example.com/a?id=2"),
        ]
        result = mod.validate_records(records)
        self.assertTrue(result["ok"])

    def test_parse_amount_wan_accepts_numbers_and_rejects_units(self):
        mod = self.load("chart")
        self.assertEqual(mod.parse_amount_wan(120), 120.0)
        self.assertEqual(mod.parse_amount_wan("1,200"), 1200.0)
        self.assertIsNone(mod.parse_amount_wan("约1200万"))
        self.assertIsNone(mod.parse_amount_wan("1.2亿"))
        self.assertIsNone(mod.parse_amount_wan(None))
        self.assertIsNone(mod.parse_amount_wan(-5))
        self.assertIsNone(mod.parse_amount_wan(0))

    def test_bucket_amounts_boundaries(self):
        mod = self.load("chart")
        counts = mod.bucket_amounts([50, 50.1, 100, 100.1, 200, 200.1, 500, 500.1])
        self.assertEqual(
            counts,
            {
                "≤50万": 1,
                "50-100万": 2,
                "100-200万": 2,
                "200-500万": 2,
                ">500万": 1,
            },
        )

    def test_chart_zero_records_generates_nothing(self):
        mod = self.load("chart")
        with tempfile.TemporaryDirectory() as tmp:
            prefix = str(Path(tmp) / "zero")
            result = mod.generate_chart([record(None)], prefix)
            self.assertFalse(result["generated"])
            self.assertFalse(Path(tmp, "zero.png").exists())

    def test_chart_four_records_generates_bar_only(self):
        mod = self.load("chart")
        records = [record(value, f"https://example.com/{i}") for i, value in enumerate([10, 60, 120, 250])]
        with tempfile.TemporaryDirectory() as tmp:
            prefix = str(Path(tmp) / "four")
            result = mod.generate_chart(records, prefix)
            self.assertTrue(result["generated"])
            self.assertEqual(result["chart"], "bar")
            self.assertIn("样本量较小", result["note"])
            self.assertTrue(Path(tmp, "four.png").exists())

    def test_chart_six_records_generates_bar_and_pie(self):
        mod = self.load("chart")
        values = [10, 60, 80, 120, 250, 600]
        records = [record(value, f"https://example.com/{i}") for i, value in enumerate(values)]
        with tempfile.TemporaryDirectory() as tmp:
            prefix = str(Path(tmp) / "six")
            result = mod.generate_chart(records, prefix)
            self.assertTrue(result["generated"])
            self.assertEqual(result["chart"], "bar+pie")
            self.assertEqual(result["valid_amounts"], 6)
            self.assertEqual(sum(result["buckets"].values()), 6)
            self.assertTrue(Path(tmp, "six.png").exists())

    def test_chart_zero_records_removes_stale_png(self):
        mod = self.load("chart")
        with tempfile.TemporaryDirectory() as tmp:
            prefix = str(Path(tmp) / "stale")
            Path(tmp, "stale.png").write_bytes(b"old")
            result = mod.generate_chart([record(None)], prefix)
            self.assertFalse(result["generated"])
            self.assertFalse(Path(tmp, "stale.png").exists())

    def test_chart_default_scope_excludes_tender_budget(self):
        mod = self.load("chart")
        records = [
            record(10, "https://example.com/1"),
            record(60, "https://example.com/2"),
            record(120, "https://example.com/3"),
            record(250, "https://example.com/4"),
            record(600, "https://example.com/5"),
        ]
        records[0]["announcement_type"] = "tender"
        with tempfile.TemporaryDirectory() as tmp:
            prefix = str(Path(tmp) / "award")
            result = mod.generate_chart(records, prefix)
            self.assertEqual(result["valid_amounts"], 4)
            self.assertEqual(result["chart"], "bar")
            self.assertIn("仅统计中标金额", result["note"])

    def test_chart_all_scope_includes_tender_budget(self):
        mod = self.load("chart")
        records = [
            record(10, "https://example.com/1"),
            record(60, "https://example.com/2"),
            record(120, "https://example.com/3"),
            record(250, "https://example.com/4"),
            record(600, "https://example.com/5"),
        ]
        records[0]["announcement_type"] = "tender"
        with tempfile.TemporaryDirectory() as tmp:
            prefix = str(Path(tmp) / "all")
            result = mod.generate_chart(records, prefix, scope="all")
            self.assertEqual(result["valid_amounts"], 5)
            self.assertEqual(result["chart"], "bar+pie")

    def test_chart_rejects_dict_without_records_key(self):
        mod = self.load("chart")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wrong.json"
            path.write_text('{"query": "x", "results": []}', encoding="utf-8")
            with self.assertRaises(ValueError):
                mod._load_records(str(path))

    def test_daily_window_uses_shanghai_midnight(self):
        mod = self.load("daily_window")
        from datetime import datetime
        from zoneinfo import ZoneInfo

        result = mod.compute_window(
            datetime(2026, 11, 26, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        )
        self.assertEqual(result["start_date"], "2026-11-25")
        self.assertEqual(result["end_date"], "2026-11-26")
        self.assertEqual(result["timezone"], "Asia/Shanghai")
        self.assertIn("+08:00", result["start"])


if __name__ == "__main__":
    unittest.main()
