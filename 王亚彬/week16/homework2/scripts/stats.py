"""确定性统计：金额分档、类型汇总。

用法：
    python stats.py bids.json
输入 JSON 列表，每项含 amount_wan (数字或 null)、type、region。
"""
import json
import sys
from collections import Counter


BUCKETS = [(0, 50, "<50万"), (50, 100, "50-100万"),
           (100, 300, "100-300万"), (300, 10**9, ">300万")]


def bucket(amount):
    if amount is None:
        return "未披露"
    for lo, hi, name in BUCKETS:
        if lo <= amount < hi:
            return name
    return "未知"


def analyze(rows: list) -> dict:
    known = [r for r in rows if r.get("amount_wan") is not None]
    return {
        "total": len(rows),
        "with_amount": len(known),
        "amount_distribution": dict(Counter(bucket(r.get("amount_wan")) for r in rows)),
        "type_distribution": dict(Counter(r.get("type", "未分类") for r in rows)),
        "region_distribution": dict(Counter(r.get("region", "未知") for r in rows)),
        "avg_amount_wan": round(sum(r["amount_wan"] for r in known) / len(known), 1) if known else None,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python stats.py bids.json")
        sys.exit(1)
    rows = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(analyze(rows), ensure_ascii=False, indent=2))
