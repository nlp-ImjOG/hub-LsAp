"""离线自测:验证确定性脚本(抽取/分类/去重/统计/摘要)在网络不可达时仍可运行。

跑法:.venv/bin/python scripts/test_offline.py
全部通过则证明"高代码确定性部分"独立可用。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import SearchResult, dedup, credibility, summarize_text
from common.config import CONFIG
from esg_bidding.extract import extract_amount, extract_date, classify, parse_record, CATEGORIES
from esg_bidding.stats import compute, render_table


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        sys.exit(1)


# 1) 金额抽取(确定性)
check("金额 1234.5 万元", extract_amount("中标金额为1234.5万元") == 1234.5)
check("金额 1.2 亿元→12000 万元", extract_amount("成交金额:1.2亿元") == 12000.0)
check("金额 元→万元", abs(extract_amount("金额:50000元") - 5.0) < 0.01)
check("无金额返回 None", extract_amount("无金额信息") is None)

# 2) 日期抽取(确定性)
check("日期 2026-10-03", extract_date("公告日 2026年10月3日") == "2026-10-03")
check("日期 2026/10/03", extract_date("2026/10/03 发布") == "2026-10-03")

# 3) 分类(关键词确定性优先)
check("碳核查→C1", classify("某碳核查服务采购") == "C1")
check("ESG报告→C2", classify("ESG报告编制采购") == "C2")
check("节能改造→C4", classify("节能改造工程招标") == "C4")
check("无匹配→C0", classify("普通办公用品采购") == "C0")

# 4) 去重 + 可信度
rs = [
    SearchResult("标题一", "https://www.gov.cn/x", "s1"),
    SearchResult("标题一", "https://www.gov.cn/x", "s1"),  # 重复 url
    SearchResult("标题二", "https://blog.spam.com/y", "s2"),
    SearchResult("标题二", "https://www.caixin.com/z", "s3"),  # 同标题,但 B 级应覆盖 C 级
]
dd = dedup(rs)
check("去重后 2 条", len(dd) == 2)
check("可信度 A", credibility("https://www.gov.cn/a") == "A")
check("可信度 B", credibility("https://www.caixin.com/b") == "B")
check("可信度 C", credibility("https://random.xyz/c") == "C")

# 5) 字段抽取 + 统计
sample_text = "采购人:某生态环境局\n中标供应商:绿碳科技有限公司\n中标金额:880.5万元\n2026年9月12日"
rec = parse_record("双碳背景下碳核查服务采购", "https://www.gov.cn/b", "碳核查", sample_text, "A")
check("record.bidder", rec.bidder == "某生态环境局")
check("record.winner", rec.winner == "绿碳科技有限公司")
check("record.amount", rec.amount_wan == 880.5)
check("record.category C1", rec.category == "C1")

recs = [
    parse_record("碳核查采购", "https://www.gov.cn/1", "", "中标金额:200万元\n2026-09-01", "A"),
    parse_record("ESG报告编制", "https://www.gov.cn/2", "", "中标金额:3000万元\n2026-09-05", "A"),
    parse_record("节能改造", "https://www.gov.cn/3", "", "中标金额:6000万元\n2026-09-10", "A"),
    parse_record("无金额项目", "https://www.gov.cn/4", "", "2026-09-12", "A"),
]
stats = compute(recs)
check("total=4", stats.total == 4)
check("with_amount=3", stats.with_amount == 3)
check("total_amount=9200", stats.total_amount_wan == 9200.0)
check("bin 100-500=1", stats.by_amount_bin["100–500万"] == 1)
check("bin 1000-5000=1", stats.by_amount_bin["1000–5000万"] == 1)
check("bin >5000=1", stats.by_amount_bin[">5000万"] == 1)
check("top1 是 6000万", stats.top10_by_amount[0]["amount_wan"] == 6000.0)

table = render_table(recs)
check("表格含表头", "| # | 项目名称" in table)

# 6) 摘要(LLM 未启用时走确定性抽取式)
sample = (
    "中国神华发布2026年可持续发展报告。报告披露范围一碳排放下降5%。"
    "公司新增两座光伏电站。员工工伤率同比下降。董事会设立ESG委员会。"
)
summ = summarize_text(sample, focus="中国神华ESG", max_sentences=3)
check("摘要非空", len(summ) > 10)
print(f"  摘要样例: {summ[:80]}...")

print("\nLLM 是否启用:", CONFIG.llm_enabled, "(未启用则走本地抽取式摘要,完全确定性)")
print("\n全部离线自测通过 ✅")
