# -*- coding: utf-8 -*-
"""T1 单元测试：filter.py（去重/时间窗/主题词/黑名单）与 _common 的 URL/标题归一化。测试不联网。"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(ROOT, ".claude", "skills", "esg-monthly-report-scripted", "scripts")
KW_MONTHLY = os.path.join(ROOT, ".claude", "skills", "esg-monthly-report-scripted", "references", "keywords.json")
KW_BID = os.path.join(ROOT, ".claude", "skills", "esg-bid-monitor-scripted", "references", "keywords.json")
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, SCRIPTS)

from _common import normalize_url, norm_title, title_fp  # noqa: E402

WINDOW = "2026-10-25:2026-11-24"


def run(*args):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "filter.py"), *[str(a) for a in args]],
                          capture_output=True, text=True, timeout=60)


class TestNormalizeUrl(unittest.TestCase):
    """设计文档 3.2 的归一化规则表逐条断言。"""

    def test_strip_tracking_params(self):
        self.assertEqual(normalize_url("https://example.com/a?utm_source=rss&id=3"),
                         "https://example.com/a?id=3")

    def test_drop_fragment(self):
        self.assertEqual(normalize_url("https://example.com/a#section"),
                         "https://example.com/a")

    def test_http_to_https(self):
        self.assertEqual(normalize_url("http://example.com/a"), "https://example.com/a")

    def test_host_lowercase(self):
        self.assertEqual(normalize_url("HTTPS://EXAMPLE.com/A"), "https://example.com/A")

    def test_trailing_slash(self):
        self.assertEqual(normalize_url("https://example.com/a/"), "https://example.com/a")
        self.assertEqual(normalize_url("https://example.com/"), "https://example.com/")

    def test_ddg_unwrap(self):
        self.assertEqual(normalize_url("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage"),
                         "https://example.com/page")

    def test_bing_unwrap(self):
        # "a1" + base64url("https://example.com/page")
        self.assertEqual(normalize_url("https://www.bing.com/ck/a?!&u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9wYWdl&ntb=1"),
                         "https://example.com/page")

    def test_params_sorted(self):
        self.assertEqual(normalize_url("https://example.com/a?b=2&a=1"),
                         "https://example.com/a?a=1&b=2")

    def test_empty(self):
        self.assertEqual(normalize_url(None), "")
        self.assertEqual(normalize_url(""), "")


class TestNormTitle(unittest.TestCase):
    def test_fullwidth_halfwidth_same_fp(self):
        self.assertEqual(title_fp("ＥＳＧ评级服务（2026）"), title_fp("ESG评级服务2026"))

    def test_whitespace_punct_ignored(self):
        self.assertEqual(title_fp("碳中和 咨询服务！"), title_fp("碳中和咨询服务"))


class TestFilterMonthly(unittest.TestCase):
    """月报模式：规则刻意宽松——keyword_weak 保留给语义判定，不误杀。"""

    @classmethod
    def setUpClass(cls):
        cls.r = run("--input", os.path.join(FIX, "candidates_monthly.json"),
                    "--window", WINDOW, "--mode", "monthly", "--client", "中国神华",
                    "--keywords", KW_MONTHLY)
        cls.out = json.loads(cls.r.stdout)

    def test_exit_ok(self):
        self.assertEqual(self.r.returncode, 0, self.r.stderr)

    def test_stats(self):
        s = self.out["stats"]
        self.assertEqual(s["total"], 7)
        self.assertEqual(s["passed"], 4)
        self.assertEqual(s["rejected"], 3)
        self.assertEqual(s["by_reason"], {"dup_url": 1, "dup_title": 1, "out_of_window": 1})

    def test_rejected_reasons(self):
        by = {x["item"]["url"]: x["reason_code"] for x in self.out["rejected"]}
        self.assertEqual(by["https://www.csrc.gov.cn/news/a1?utm_source=rss&utm_medium=feed&from=rss"], "dup_url")
        self.assertEqual(by["https://media.example.org/same-title"], "dup_title")
        self.assertEqual(by["https://coal.example.org/old-news"], "out_of_window")

    def test_passed_notes(self):
        by = {x["url"]: x for x in self.out["passed"]}
        self.assertEqual(set(by), {"https://www.csrc.gov.cn/news/a1",
                                   "https://finance.example.org/oper-data",
                                   "https://city.example.org/marathon",
                                   "https://www.ifrs.org/consultation"})
        self.assertTrue(any("date_unknown" in n for n in by["https://finance.example.org/oper-data"]["filter_notes"]))
        self.assertTrue(any("keyword_weak" in n for n in by["https://city.example.org/marathon"]["filter_notes"]))
        self.assertTrue(any("date_future" in n for n in by["https://www.ifrs.org/consultation"]["filter_notes"]))
        self.assertTrue(any("命中词库" in n for n in by["https://www.csrc.gov.cn/news/a1"]["filter_notes"]))

    def test_default_keywords_path(self):
        """不传 --keywords 时应自动取本 skill 的 references/keywords.json。"""
        r = run("--input", os.path.join(FIX, "candidates_monthly.json"),
                "--window", WINDOW, "--mode", "monthly", "--client", "中国神华")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["stats"]["passed"], 4)


class TestFilterBid(unittest.TestCase):
    """标讯模式：主题词硬要求 + 黑名单巧合词排除（对齐作业1 keywords.md 典型排除项）。"""

    @classmethod
    def setUpClass(cls):
        cls.r = run("--input", os.path.join(FIX, "candidates_bid.json"),
                    "--window", WINDOW, "--mode", "bid", "--keywords", KW_BID)
        cls.out = json.loads(cls.r.stdout)

    def test_exit_ok(self):
        self.assertEqual(self.r.returncode, 0, self.r.stderr)

    def test_stats(self):
        s = self.out["stats"]
        self.assertEqual(s["total"], 9)
        self.assertEqual(s["passed"], 4)
        self.assertEqual(s["rejected"], 5)
        self.assertEqual(s["by_reason"],
                         {"dup_url": 1, "dup_title": 1, "keyword_miss": 1,
                          "out_of_window": 1, "blacklist_hit": 1})

    def test_blacklist_green_channel(self):
        """绿色通道：主题词命中('绿色')仍被黑名单排除。"""
        rej = {x["item"]["url"]: x for x in self.out["rejected"]}
        self.assertEqual(rej["https://hosp.example.org/purchase"]["reason_code"], "blacklist_hit")
        self.assertIn("绿色通道", rej["https://hosp.example.org/purchase"]["detail"])

    def test_keyword_miss_greenbelt(self):
        """市政绿化带养护：无主题词命中 → keyword_miss（黑名单前的规则链顺序）。"""
        rej = {x["item"]["url"]: x["reason_code"] for x in self.out["rejected"]}
        self.assertEqual(rej["https://city.example.org/road-green"], "keyword_miss")

    def test_unless_exemption_passes(self):
        """矿区绿化+碳汇计量：unless 豁免词命中 → 放行。"""
        by = {x["url"]: x for x in self.out["passed"]}
        self.assertIn("https://mine.example.org/carbon", by)
        self.assertTrue(any("命中主题词:碳汇" in n for n in by["https://mine.example.org/carbon"]["filter_notes"]))

    def test_future_date_kept_with_note(self):
        by = {x["url"]: x for x in self.out["passed"]}
        self.assertTrue(any("date_future" in n for n in by["https://pv.example.org/procurement"]["filter_notes"]))

    def test_missing_keywords_file_fails(self):
        r = run("--input", os.path.join(FIX, "candidates_bid.json"),
                "--window", WINDOW, "--mode", "bid", "--keywords", "/nonexistent/keywords.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("无法读取词库", r.stderr)


if __name__ == "__main__":
    unittest.main()
