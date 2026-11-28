# -*- coding: utf-8 -*-
"""T1 单元测试：parse_args.py（时间表达解析 + 行业查表 + CLI 契约）。测试不联网。"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(ROOT, ".claude", "skills", "esg-monthly-report-scripted", "scripts")
sys.path.insert(0, SCRIPTS)

import parse_args as pa  # noqa: E402

TODAY = datetime.date(2026, 11, 24)


def run(*args):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "parse_args.py"), *[str(a) for a in args]],
                          capture_output=True, text=True, timeout=60)


class TestParsePeriod(unittest.TestCase):
    def test_default_monthly(self):
        s, e = pa.parse_period("近一个月", TODAY)
        self.assertEqual((s, e), (datetime.date(2026, 10, 25), TODAY))

    def test_recent_n_months_cn_num(self):
        s, e = pa.parse_period("近三个月", TODAY)
        self.assertEqual(s, TODAY - datetime.timedelta(days=90))

    def test_recent_2_years(self):
        # 规则：近N年 = today − N×365 天（设计文档 3.1），2026-11-24 − 730d = 2024-11-24
        s, _ = pa.parse_period("近2年", TODAY)
        self.assertEqual(s, datetime.date(2024, 11, 24))
        s2, _ = pa.parse_period("近两年", TODAY)
        self.assertEqual(s2, datetime.date(2024, 11, 24))

    def test_half_year_and_24h(self):
        self.assertEqual(pa.parse_period("近半年", TODAY)[0], TODAY - datetime.timedelta(days=182))
        self.assertEqual(pa.parse_period("近24h", TODAY)[0], datetime.date(2026, 11, 23))

    def test_month_bounds(self):
        s, e = pa.parse_period("2026-11", TODAY)
        self.assertEqual((s, e), (datetime.date(2026, 11, 1), datetime.date(2026, 11, 30)))

    def test_closed_interval(self):
        s, e = pa.parse_period("2026-01-01至2026-06-30", TODAY)
        self.assertEqual((s, e), (datetime.date(2026, 1, 1), datetime.date(2026, 6, 30)))

    def test_single_day(self):
        s, e = pa.parse_period("2026-03-15", TODAY)
        self.assertEqual((s, e), (datetime.date(2026, 3, 15), datetime.date(2026, 3, 15)))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            pa.parse_period("2026-02-30", TODAY)  # 不存在的日期
        with self.assertRaises(ValueError):
            pa.parse_period("随便什么", TODAY)
        with self.assertRaises(ValueError):
            pa.parse_period("2026-13", TODAY)


class TestResolveIndustry(unittest.TestCase):
    def _args(self, **kw):
        ns = pa.argparse.Namespace(client=kw.get("client", "中国神华"),
                                   industry=kw.get("industry"), industry_map=kw.get("industry_map"))
        return ns

    def test_builtin(self):
        industry, src, hints = pa.resolve_industry(self._args())
        self.assertEqual((industry, src, hints), ("煤炭/传统能源", "builtin", []))

    def test_unknown_needs_search(self):
        industry, src, hints = pa.resolve_industry(self._args(client="某某新科技公司"))
        self.assertIsNone(industry)
        self.assertEqual(src, "needs_search")
        self.assertTrue(hints and "主营" in hints[0])

    def test_cli_override(self):
        industry, src, _ = pa.resolve_industry(self._args(industry="半导体"))
        self.assertEqual((industry, src), ("半导体", "cli"))


class TestCLI(unittest.TestCase):
    def test_monthly_default(self):
        r = run("--today", "2026-11-24")
        self.assertEqual(r.returncode, 0, r.stderr)
        meta = json.loads(r.stdout)
        self.assertEqual(meta["mode"], "monthly")
        self.assertEqual(meta["start_date"], "2026-10-25")
        self.assertEqual(meta["end_date"], "2026-11-24")
        self.assertEqual(meta["period_label"], "2026年11月刊")
        self.assertEqual(meta["window"], "2026-10-25:2026-11-24")
        self.assertEqual(meta["industry"], "煤炭/传统能源")

    def test_report_mode_default_2_years(self):
        r = run("--today", "2026-11-24", "--mode", "report")
        self.assertEqual(json.loads(r.stdout)["start_date"], "2024-11-24")

    def test_monitor_mode_default_24h(self):
        r = run("--today", "2026-11-24", "--mode", "monitor")
        self.assertEqual(json.loads(r.stdout)["start_date"], "2026-11-23")

    def test_explicit_period(self):
        r = run("--today", "2026-11-24", "--period", "2026-01-01至2026-06-30")
        meta = json.loads(r.stdout)
        self.assertEqual((meta["start_date"], meta["end_date"]), ("2026-01-01", "2026-06-30"))

    def test_unknown_client(self):
        r = run("--today", "2026-11-24", "--client", "某某新科技公司")
        meta = json.loads(r.stdout)
        self.assertIsNone(meta["industry"])
        self.assertEqual(meta["industry_source"], "needs_search")
        self.assertTrue(meta["hints"])

    def test_industry_override(self):
        r = run("--today", "2026-11-24", "--industry", "半导体")
        meta = json.loads(r.stdout)
        self.assertEqual((meta["industry"], meta["industry_source"]), ("半导体", "cli"))

    def test_out_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "meta.json")
            r = run("--today", "2026-11-24", "--out", out)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["client"], "中国神华")

    def test_invalid_period_fails(self):
        r = run("--today", "2026-11-24", "--period", "上礼拜")
        self.assertEqual(r.returncode, 1)
        self.assertIn("错误", r.stderr)

    def test_invalid_today_fails(self):
        r = run("--today", "2026-2-99")
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
