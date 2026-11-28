# -*- coding: utf-8 -*-
"""T1 单元测试：check.py 的 R1–R7 规则（每条规则 1 正 1 反）。测试不联网。"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(ROOT, ".claude", "skills", "esg-monthly-report-scripted", "scripts")
FIX = os.path.join(HERE, "fixtures")

WINDOW = "2026-10-25:2026-11-24"


def run(*args):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "check.py"), *[str(a) for a in args]],
                          capture_output=True, text=True, timeout=60)


class TestReportGood(unittest.TestCase):
    """合格样本：引用一致、期外数据已标注、无占位残留、章节达标。"""

    @classmethod
    def setUpClass(cls):
        cls.r = run("report", "--file", os.path.join(FIX, "report_good.md"),
                    "--window", WINDOW, "--notes", os.path.join(FIX, "notes_good.md"))
        cls.out = json.loads(cls.r.stdout)

    def test_exit_ok_and_passed(self):
        self.assertEqual(self.r.returncode, 0, self.r.stdout + self.r.stderr)
        self.assertTrue(self.out["passed"])
        self.assertEqual(self.out["summary"]["errors"], 0)

    def test_only_future_date_warn(self):
        self.assertEqual(self.out["summary"]["warns"], 1)
        w = self.out["failures"][0]
        self.assertEqual(w["rule"], "R2")
        self.assertEqual(w["severity"], "warn")
        self.assertIn("2027-02-19", w["detail"])


class TestReportBad(unittest.TestCase):
    """违规样本：故意触发 R1/R2/R3/R4/R5/R6。"""

    @classmethod
    def setUpClass(cls):
        # --min-words 150：fixture 第一/二章内容量 180/234（达标），三/四章 8/0（违规），
        # 使 R4 的预期违规数精确为 2
        cls.r = run("report", "--file", os.path.join(FIX, "report_bad.md"),
                    "--window", WINDOW, "--min-words", "150",
                    "--notes", os.path.join(FIX, "nonexistent_notes.md"))
        cls.out = json.loads(cls.r.stdout)

    def test_exit_1_and_not_passed(self):
        self.assertEqual(self.r.returncode, 1)
        self.assertFalse(self.out["passed"])

    def test_error_rules(self):
        errors = [f for f in self.out["failures"] if f["severity"] == "error"]
        self.assertEqual({f["rule"] for f in errors}, {"R1", "R2", "R3", "R4", "R6"})

    def test_r1_missing_citation(self):
        r1 = [f for f in self.out["failures"] if f["rule"] == "R1" and f["severity"] == "error"]
        self.assertEqual(len(r1), 1)
        self.assertIn("[3]", r1[0]["detail"])

    def test_r1_uncited_appendix_warn(self):
        warns = [f for f in self.out["failures"] if f["rule"] == "R1" and f["severity"] == "warn"]
        self.assertEqual(len(warns), 1)
        self.assertIn("[2]", warns[0]["detail"])

    def test_r2_unannotated_out_of_window(self):
        r2 = [f for f in self.out["failures"] if f["rule"] == "R2" and f["severity"] == "error"]
        self.assertEqual(len(r2), 1)
        self.assertIn("2026-10-01", r2[0]["detail"])

    def test_r3_placeholders(self):
        r3 = [f for f in self.out["failures"] if f["rule"] == "R3"]
        self.assertEqual(len(r3), 3)  # 模型撰写注释 / {{cite:}} / TODO

    def test_r4_short_chapters(self):
        r4 = [f for f in self.out["failures"] if f["rule"] == "R4"]
        self.assertEqual(len(r4), 2)  # 三、建议 与 四、空章节
        self.assertTrue(any("三、建议" in f["detail"] for f in r4))

    def test_r5_warnings(self):
        r5 = [f for f in self.out["failures"] if f["rule"] == "R5"]
        self.assertEqual(len(r5), 3)  # 空 mermaid / 空章节 / 空表格行

    def test_r6_missing_notes(self):
        r6 = [f for f in self.out["failures"] if f["rule"] == "R6"]
        self.assertEqual(len(r6), 1)
        self.assertIn("nonexistent_notes", r6[0]["detail"])


class TestDb(unittest.TestCase):
    def test_good(self):
        r = run("db", "--db", os.path.join(FIX, "bids_good.jsonl"),
                "--state", os.path.join(FIX, "state_ok.json"))
        out = json.loads(r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(out["passed"])
        self.assertEqual(out["summary"]["errors"], 0)

    def test_bad(self):
        r = run("db", "--db", os.path.join(FIX, "bids_bad.jsonl"),
                "--state", os.path.join(FIX, "state_bad.json"))
        out = json.loads(r.stdout)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(out["passed"])
        errors = [f for f in out["failures"] if f["severity"] == "error"]
        # L1: buyer 空 + publish_date 坏 + url 坏 = 3；L2: record_id 重复 + theme 空 = 2；seen_count 不一致 = 1
        self.assertEqual(len(errors), 6)
        self.assertEqual({f["rule"] for f in errors}, {"R7"})
        details = " | ".join(f["detail"] for f in errors)
        for expect in ["必填字段 buyer 为空", "publish_date 非法", "url 非法",
                       "record_id 重复", "必填字段 theme 为空", "seen_count"]:
            self.assertIn(expect, details)

    def test_missing_db_file(self):
        r = run("db", "--db", os.path.join(FIX, "nonexistent.jsonl"))
        out = json.loads(r.stdout)
        self.assertEqual(r.returncode, 1)
        self.assertIn("标讯库不存在", out["failures"][0]["detail"])

    def test_missing_state_warns_only(self):
        r = run("db", "--db", os.path.join(FIX, "bids_good.jsonl"),
                "--state", os.path.join(FIX, "nonexistent_state.json"))
        out = json.loads(r.stdout)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(any(f["rule"] == "R7" and f["severity"] == "warn" for f in out["failures"]))


if __name__ == "__main__":
    unittest.main()
