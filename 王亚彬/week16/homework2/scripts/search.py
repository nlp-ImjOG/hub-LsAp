"""确定性搜索：按预定义关键词模板搜索，返回结构化结果。

用法：
    python search.py --company 中国神华 --month 2026-11
    python search.py --company 中国神华 --month 2026-11 --query-only
"""
import argparse
import json
from datetime import date, timedelta


def month_range(ym: str):
    """输入 '2026-11'，返回 (start, end)。"""
    year, month = map(int, ym.split("-"))
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return str(start), str(end)


def build_queries(company: str, ym: str, industry: str = "煤炭 能源") -> list:
    """生成固定搜索词模板——这就是 script 的确定性价值。"""
    year, month = ym.split("-")
    return [
        f"{year}年{int(month)}月 ESG 政策 新规 信息披露",
        f"证监会 ESG 信息披露 标准 {year}",
        f"可持续发展 评级 标准 最新 {year}",
        f"{industry} ESG 最佳实践 {year}",
        f"{industry} 绿色转型 碳中和 动态 {int(month)}月",
        f"{company} ESG {year} 可持续发展",
        f"{company} 碳减排 治理 动态 {int(month)}月",
        "中煤能源 兖矿能源 ESG 评级 2026",
    ]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--company", default="中国神华")
    p.add_argument("--month", default="2026-11")
    p.add_argument("--industry", default="煤炭 能源")
    p.add_argument("--query-only", action="store_true", help="只输出关键词，不搜索")
    args = p.parse_args()

    start, end = month_range(args.month)
    queries = build_queries(args.company, args.month, args.industry)
    out = {"company": args.company, "window": [start, end], "queries": queries}
    if args.query_only:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    # 实际搜索由 Agent 用 WebSearch 工具执行这些 query；
    # 这里只负责确定性地产出搜索词和时间窗口，避免模型临场遗漏或算错日期。
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
