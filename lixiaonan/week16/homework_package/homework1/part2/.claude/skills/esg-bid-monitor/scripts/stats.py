#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ESG 标讯库统计脚本（纯 Python 标准库，无第三方依赖）

用法:
    python stats.py [bids.jsonl路径] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--out stats.json]

- 缺省输入路径依次尝试: ./data/bids.jsonl, <skill包>/../../../data/bids.jsonl
- 时间过滤按 publish_date 闭区间；不带参数则统计全库
- 统计结果 JSON 输出到 stdout；--out 指定时同时落盘

统计维度: 总量 / 阶段分布 / 主题分布(多标签) / 项目类型 / 地区Top10 / 采购人类型 /
          月度趋势 / 金额分桶与集中趋势 / 中标企业Top10 / 采购人Top10 / 来源构成 / 金额缺失率
"""
import argparse
import json
import os
import statistics
from collections import Counter, defaultdict

# 金额分桶（单位：万元），左闭右开；最后一桶右端为无穷
BUCKETS = [
    ("<50万", 0.0, 50.0),
    ("50-100万", 50.0, 100.0),
    ("100-500万", 100.0, 500.0),
    ("500-1000万", 500.0, 1000.0),
    ("1000-5000万", 1000.0, 5000.0),
    ("5000万-1亿", 5000.0, 10000.0),
    ("≥1亿", 10000.0, float("inf")),
]


def default_input():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [
        os.path.join(os.getcwd(), "data", "bids.jsonl"),
        os.path.normpath(os.path.join(here, "..", "..", "..", "data", "bids.jsonl")),
    ]
    for p in cands:
        if os.path.isfile(p):
            return p
    return cands[0]


def in_range(date_str, start, end):
    if not date_str:
        return False
    if start and date_str < start:
        return False
    if end and date_str > end:
        return False
    return True


def bucket_of(amount):
    for label, lo, hi in BUCKETS:
        if lo <= amount < hi:
            return label
    return None


def main():
    ap = argparse.ArgumentParser(description="ESG 标讯库统计")
    ap.add_argument("input", nargs="?", default=None, help="bids.jsonl 路径")
    ap.add_argument("--start-date", default=None, help="起始日期 YYYY-MM-DD（含）")
    ap.add_argument("--end-date", default=None, help="截止日期 YYYY-MM-DD（含）")
    ap.add_argument("--out", default=None, help="统计结果 JSON 落盘路径")
    args = ap.parse_args()

    path = args.input or default_input()
    if not os.path.isfile(path):
        print(json.dumps({"error": f"input not found: {path}"}, ensure_ascii=False))
        sys_exit = 1
        raise SystemExit(sys_exit)

    records, malformed = [], []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                malformed.append(lineno)
                continue
            if in_range(rec.get("publish_date"), args.start_date, args.end_date):
                records.append(rec)

    total = len(records)
    stage_c, theme_c, industry_c, buyer_type_c, source_c = Counter(), Counter(), Counter(), Counter(), Counter()
    region_c, buyer_c, winner_c = Counter(), Counter(), Counter()
    winner_amt = defaultdict(float)
    monthly = defaultdict(lambda: {"count": 0, "amount_wan": 0.0})
    amounts = []

    for r in records:
        amount = r.get("amount_wan")
        has_amount = isinstance(amount, (int, float))

        for t in (r.get("theme") or []):
            theme_c[t] += 1
        for key, counter in (("stage", stage_c), ("industry_type", industry_c),
                             ("buyer_type", buyer_type_c), ("source_name", source_c)):
            if r.get(key):
                counter[r[key]] += 1
        if r.get("region"):
            region_c[r["region"]] += 1
        if r.get("buyer"):
            buyer_c[r["buyer"]] += 1

        month = (r.get("publish_date") or "")[:7]
        if month:
            monthly[month]["count"] += 1
            if has_amount:
                monthly[month]["amount_wan"] += amount

        if has_amount:
            amounts.append(float(amount))

        winner = r.get("winner")
        if winner:
            winner_c[winner] += 1
            if has_amount:
                winner_amt[winner] += float(amount)

    missing = total - len(amounts)
    buckets = {label: 0 for label, _, _ in BUCKETS}
    for a in amounts:
        label = bucket_of(a)
        if label:
            buckets[label] += 1

    amount_stats = {
        "with_amount": len(amounts),
        "missing": missing,
        "missing_rate": round(missing / total, 4) if total else 0.0,
        "buckets": buckets,
    }
    if amounts:
        amount_stats.update({
            "total_wan": round(sum(amounts), 2),
            "mean_wan": round(statistics.mean(amounts), 2),
            "median_wan": round(statistics.median(amounts), 2),
            "min_wan": round(min(amounts), 2),
            "max_wan": round(max(amounts), 2),
        })

    result = {
        "input": os.path.abspath(path),
        "window": {"start": args.start_date, "end": args.end_date},
        "total": total,
        "malformed_lines": malformed,
        "stage": dict(stage_c.most_common()),
        "theme_counts": dict(theme_c.most_common()),
        "industry_type": dict(industry_c.most_common()),
        "buyer_type": dict(buyer_type_c.most_common()),
        "region_top10": [{"region": k, "count": v} for k, v in region_c.most_common(10)],
        "monthly": [
            {"month": m, "count": v["count"], "amount_wan": round(v["amount_wan"], 2)}
            for m, v in sorted(monthly.items())
        ],
        "amount": amount_stats,
        "top_winners": [
            {"winner": w, "count": c, "amount_wan_sum": round(winner_amt[w], 2)}
            for w, c in winner_c.most_common(10)
        ],
        "top_buyers": [{"buyer": k, "count": v} for k, v in buyer_c.most_common(10)],
        "sources": dict(source_c.most_common()),
    }

    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        out_dir = os.path.dirname(os.path.abspath(args.out))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out + "\n")
    print(out)


if __name__ == "__main__":
    main()
