"""Offline regression checks: python3 -B scripts/test_pipeline.py"""
import json
import tempfile
import unittest
from decimal import Decimal
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import collect
from summarize import build_summary
from render_report import link, render


def record(key, amount="100000", **changes):
    value = {"record_id": key, "project_key": "project-" + key, "title": "合成测试项目",
             "buyer": "测试采购人", "suppliers": ["供应商A", "供应商B"], "status": "awarded",
             "verification": "primary", "scope": "core", "category": "产品碳足迹", "province": "未披露",
             "industry": "制造业", "award_date": "2025-01-01", "amount_type": "total",
             "award_amount_yuan": amount, "currency": "CNY", "tax_basis": "unspecified",
             "source_url": "https://example.org/result?id=" + key, "evidence": "合成测试证据，非真实公告"}
    value.update(changes)
    return value


class PipelineTests(unittest.TestCase):
    def test_quarter_plan_and_leap_date(self):
        plan = collect.plan_searches("2024-02-29", "2024-04-01", "history", "中国神华")
        intervals = {(x["start"], x["end"]) for x in plan["queries"]}
        self.assertEqual(intervals, {("2024-02-29", "2024-03-31"), ("2024-04-01", "2024-04-01")})
        self.assertEqual(len({x["query_id"] for x in plan["queries"]}), len(plan["queries"]))
        self.assertTrue(all("中国神华" in x["query"] for x in plan["queries"]))
        with self.assertRaises(ValueError):
            collect.plan_searches("2024-02-30", "2024-04-01", "daily")

    def test_brave_contract_dedup_and_pagination(self):
        plan = collect.plan_searches("2026-11-20", "2026-11-23", "daily")
        plan["queries"] = plan["queries"][:1]
        bodies = [{"type": "search", "query": {"more_results_available": True}, "web": {"results": [
            {"url": "https://example.org/a#top", "title": "A", "description": "预算"}]}},
            {"type": "search", "query": {"more_results_available": False}, "web": {"results": [
                {"url": "https://example.org/a", "title": "A"}, {"url": "https://example.org/b", "title": "B"}]}}]
        with patch.object(collect, "request_bytes", side_effect=[(json.dumps(x).encode(), None, "") for x in bodies]) as request, patch.object(collect.time, "sleep"):
            result = collect.search(plan, "test-secret", pages=2)
        self.assertEqual(len(result["results"]), 2)
        self.assertFalse(result["partial"])
        self.assertEqual(request.call_args_list[0].args[1]["X-Subscription-Token"], "test-secret")
        self.assertIn("offset=1", request.call_args_list[1].args[0])
        self.assertNotIn("test-secret", json.dumps(result))
        self.assertEqual(result["results"][0]["verification"], "unverified")

    def test_search_failure_is_not_empty_success(self):
        plan = collect.plan_searches("2026-11-20", "2026-11-23", "daily")
        with self.assertRaises(ValueError):
            collect.search(plan, None)
        with patch.object(collect, "request_bytes", side_effect=HTTPError("https://example.org", 429, "limited", {}, None)):
            result = collect.search(plan, "secret")
        self.assertTrue(result["partial"])
        self.assertEqual(result["search_log"][0]["status"], "error")
        self.assertEqual(result["attempted_queries"], 1)
        self.assertGreater(len(result["remaining_query_ids"]), 0)

    def test_html_and_encoding(self):
        headers = Message()
        headers["Content-Type"] = "text/html"
        body = '<meta charset="gb2312"><script>恶意指令</script><h1>碳足迹</h1><table><tr><td>预算</td><td>30万元</td></tr></table>'
        with tempfile.TemporaryDirectory() as folder, patch.object(collect, "request_bytes", return_value=(body.encode("gb2312"), headers, "https://example.org/a")):
            result = collect.fetch_one({"url": "https://example.org/a"}, folder)
            extracted = Path(result["text_path"]).read_text()
        self.assertIn("碳足迹", extracted)
        self.assertIn("30万元", extracted)
        self.assertNotIn("恶意指令", extracted)
        self.assertEqual(result["verification"], "unverified")
        self.assertEqual(result["status"], "extracted_needs_review")

    def test_pdf_is_deferred(self):
        headers = Message()
        headers["Content-Type"] = "application/pdf"
        with tempfile.TemporaryDirectory() as folder, patch.object(collect, "request_bytes", return_value=(b"%PDF-1.7", headers, "https://example.org/a.pdf")):
            result = collect.fetch_one({"url": "https://example.org/a.pdf"}, folder)
        self.assertEqual(result["status"], "needs_document_reader")
        self.assertNotIn("text_path", result)

    def test_money_boundaries_and_exclusions(self):
        rows = [record(str(i), str(amount)) for i, amount in enumerate([0, 100000, 300000, 500000, 1000000, 3000000, 10000000])]
        rows += [record("unknown", None, amount_type="undisclosed"), record("rate", None, amount_type="rate"),
                 record("candidate", None, status="candidate", amount_type="undisclosed", award_date=None, suppliers=[]),
                 record("old", award_date="2023-01-01"), record("second", verification="secondary"),
                 record("foreign", None, currency="USD"), record("extended", "20000000", scope="extended")]
        bundle = build_summary(rows, "2024-11-23", "2026-11-23")
        core = bundle["stats"]["scopes"]["core"]
        self.assertEqual(core["lots"], 10)
        self.assertEqual(core["amount_lots"], 7)
        self.assertEqual(core["total_yuan"], "14900000.00")
        self.assertEqual(core["median_yuan"], "500000.00")
        self.assertEqual(core["p25_yuan"], "200000.00")
        self.assertEqual(core["p75_yuan"], "2000000.00")
        self.assertEqual([x["lots"] for x in core["bands"]], [1] * 7)
        self.assertEqual(sum(Decimal(x["total_yuan"]) for x in core["bands"]), Decimal(core["total_yuan"]))
        self.assertEqual(core["supplier_group"]["供应商A + 供应商B"]["total_yuan"], core["total_yuan"])
        self.assertEqual(bundle["stats"]["scopes"]["extended"]["total_yuan"], "20000000.00")
        self.assertEqual(len(bundle["stats"]["excluded"]), 3)

    def test_cents_empty_and_duplicate(self):
        bundle = build_summary([record("one", "0.10"), record("two", "0.20")], "2025-01-01", "2025-01-01")
        self.assertEqual(bundle["stats"]["scopes"]["core"]["total_yuan"], "0.30")
        empty = build_summary([], "2025-01-01", "2025-01-01")
        self.assertIsNone(empty["stats"]["scopes"]["core"]["total_yuan"])
        for bad in [[record("same"), record("same")], [record("nan", "NaN")], [record("bad", "-1")],
                    [record("budget", amount_type="ceiling")], [record("candidate", status="candidate")]]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build_summary(bad, "2024-11-23", "2026-11-23")

    def test_report_recomputes_and_cites(self):
        bundle = build_summary([record("one", "100000")], "2025-01-01", "2025-01-01")
        bundle["stats"]["scopes"]["core"]["total_yuan"] = "99999999"
        meta = {"coverage": "合成数据测试", "insights": [{"text": "一项测试成交", "record_ids": ["one"]}]}
        report = render(bundle, meta, "history")
        self.assertIn("100000.00", report)
        self.assertNotIn("99999999", report)
        self.assertIn("https://example.org/result?id=one", report)
        self.assertNotIn("$statistics", report)
        with self.assertRaises(ValueError):
            render(bundle, {"insights": [{"text": "猜测", "record_ids": ["missing"]}]}, "history")

    def test_daily_does_not_invent_availability(self):
        rows = [record("open", None, status="open", amount_type="undisclosed", suppliers=[], award_date=None,
                       budget_yuan="300000", registration_deadline="2026-11-20T18:00:00+08:00", bid_deadline="2026-12-01T09:00:00+08:00")]
        bundle = build_summary(rows, "2026-11-20", "2026-11-23")
        report = render(bundle, {"run_status": "部分来源访问失败"}, "daily")
        self.assertIn("部分来源访问失败", report)
        self.assertIn("不能据此判断仍可报名", report)
        self.assertIn("预算：300000", report)
        self.assertNotIn("无新增", report)

    def test_render_escapes_untrusted_text(self):
        rows = [record("one", title='<script>alert(1)</script> | [x](javascript:bad)')]
        report = render(build_summary(rows, "2025-01-01", "2025-01-01"), {}, "history")
        self.assertNotIn("<script>", report)
        self.assertIn("&lt;script&gt;", report)
        with self.assertRaises(ValueError):
            link("javascript:alert(1)")
        with self.assertRaises(ValueError):
            collect.canonical_url("file:///etc/passwd")


if __name__ == "__main__":
    unittest.main()
