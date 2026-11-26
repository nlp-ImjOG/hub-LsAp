"""ESG 投标历史汇总：金额换算、窗口过滤、去重与确定性统计（不调用 LLM）。"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import math
import re
import statistics
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = SKILL_ROOT / "output"

BUCKETS = [
    ("<100万", 0, 1_000_000),
    ("100-500万", 1_000_000, 5_000_000),
    ("500-1000万", 5_000_000, 10_000_000),
    ("1000-5000万", 10_000_000, 50_000_000),
    (">5000万", 50_000_000, math.inf),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ESG 投标历史汇总（确定性统计）")
    parser.add_argument("--input", default=str(DEFAULT_OUT_DIR / "bids_raw.json"))
    parser.add_argument("--as-of", dest="as_of", default=None, help="统计截止日，默认取数据中的最大日期")
    parser.add_argument("--months", type=int, default=24, help="历史窗口月数")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args(argv)


def parse_date(text: str | None) -> dt.date | None:
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def minus_months(value: dt.date, months: int) -> dt.date:
    year = value.year + (value.month - 1 - months) // 12
    month = (value.month - 1 - months) % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def parse_amount(raw: str | None) -> tuple[int | None, str]:
    """把中文金额字符串换算为元；返回 (元, 备注)。"""
    if not raw:
        return None, "未披露"
    text = raw.translate(str.maketrans("０１２３４５６７８９．，", "0123456789.,")).replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(亿|万)", text)
    if match:
        value = float(match.group(1)) * (100_000_000 if match.group(2) == "亿" else 10_000)
        return int(round(value)), ""
    match = re.search(r"(\d+(?:\.\d+)?)\s*元", text)
    if match:
        return int(round(float(match.group(1)))), ""
    if re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", text):
        return int(round(float(text.strip()))), "无单位，按元处理"
    return None, "无法解析"


def fmt_amount(yuan: int | None) -> str:
    if yuan is None:
        return "未披露"
    if yuan >= 100_000_000:
        return f"{yuan / 100_000_000:.2f} 亿元"
    if yuan >= 10_000:
        return f"{yuan / 10_000:,.0f} 万元"
    return f"{yuan:,.0f} 元"


def cell(text: str | None) -> str:
    return (text or "-").replace("|", "／").replace("\n", " ").strip()


def record_key(record: dict) -> tuple[str, str, str]:
    title = re.sub(r"[^一-鿿A-Za-z0-9]", "", record.get("title", ""))
    return (record.get("publish_date") or "", title, record.get("buyer") or "")


def compute(records: list[dict], as_of: dt.date, months: int) -> dict:
    start = minus_months(as_of, months)
    in_window: list[dict] = []
    excluded: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    duplicates = 0
    amount_notes: list[str] = []

    for record in records:
        date_value = parse_date(record.get("publish_date"))
        if not date_value:
            excluded.append({**record, "exclude_reason": "日期缺失"})
            continue
        if record.get("date_unverified"):
            excluded.append({**record, "exclude_reason": "日期未能在原文核实"})
            continue
        if date_value < start or date_value > as_of:
            excluded.append({**record, "exclude_reason": f"窗口外（{start} 至 {as_of}）"})
            continue
        key = record_key(record)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        yuan, note = parse_amount(record.get("amount_raw"))
        if note and note != "未披露":
            amount_notes.append(f"{record['title']}：{note}（{record.get('amount_raw')}）")
        in_window.append({**record, "amount_yuan": yuan, "amount_note": note})

    amounts = [r["amount_yuan"] for r in in_window if r["amount_yuan"] is not None]
    by_industry: dict[str, dict] = {}
    by_region: dict[str, dict] = {}
    by_buyer: dict[str, dict] = {}
    by_quarter: dict[str, dict] = {}
    for record in in_window:
        date_value = parse_date(record["publish_date"])
        quarter = f"{date_value.year}-Q{(date_value.month - 1) // 3 + 1}"
        industry = record.get("industry") or "其他"
        region = record.get("region") or "未注明"
        buyer = record.get("buyer") or "未注明"
        for bucket, key in (
            (by_industry, industry),
            (by_region, region),
            (by_buyer, buyer),
            (by_quarter, quarter),
        ):
            entry = bucket.setdefault(key, {"count": 0, "amount": 0, "disclosed": 0})
            entry["count"] += 1
            if record["amount_yuan"] is not None:
                entry["amount"] += record["amount_yuan"]
                entry["disclosed"] += 1

    bucket_rows = []
    for label, low, high in BUCKETS:
        count = sum(1 for value in amounts if low <= value < high)
        bucket_rows.append({"label": label, "count": count})

    def ranked(mapping: dict[str, dict]) -> list[dict]:
        rows = [{"name": name, **stats} for name, stats in mapping.items()]
        rows.sort(key=lambda row: (-row["count"], -row["amount"], row["name"]))
        return rows

    top_projects = sorted(
        (r for r in in_window if r["amount_yuan"] is not None),
        key=lambda r: -r["amount_yuan"],
    )[:5]

    return {
        "window": {"start": start.isoformat(), "end": as_of.isoformat(), "months": months},
        "summary": {
            "projects": len(in_window),
            "with_amount": len(amounts),
            "without_amount": len(in_window) - len(amounts),
            "total_amount": sum(amounts) if amounts else None,
            "average_amount": (sum(amounts) / len(amounts)) if amounts else None,
            "median_amount": statistics.median(amounts) if amounts else None,
            "min_amount": min(amounts) if amounts else None,
            "max_amount": max(amounts) if amounts else None,
            "duplicates_removed": duplicates,
            "excluded": len(excluded),
        },
        "buckets": bucket_rows,
        "by_industry": ranked(by_industry),
        "by_region": ranked(by_region)[:5],
        "top_buyers": ranked(by_buyer)[:5],
        "by_quarter": [{"quarter": q, **stats} for q, stats in sorted(by_quarter.items())],
        "top_projects": [
            {
                "title": r["title"],
                "buyer": r.get("buyer"),
                "winner": r.get("winner"),
                "amount": r["amount_yuan"],
                "date": r["publish_date"],
                "source": r.get("source"),
                "url": r.get("url"),
            }
            for r in top_projects
        ],
        "excluded": excluded,
        "amount_notes": amount_notes,
    }


def build_markdown(analysis: dict) -> str:
    summary = analysis["summary"]
    window = analysis["window"]
    projects = summary["projects"]

    def pct(count: int, total: int) -> str:
        return f"{count / total * 100:.1f}%" if total else "0.0%"

    lines: list[str] = []
    lines.append(f"# ESG 相关中标情况汇总分析（{window['start']} 至 {window['end']}）\n")
    lines.append(
        f"> 统计窗口：{window['months']} 个月　|　入窗项目：{projects} 个　|　"
        f"披露金额项目：{summary['with_amount']} 个　|　数据来源：公开互联网检索\n"
    )

    lines.append("## 一、总体概览\n")
    lines.append("| 指标 | 数值 |\n|---|---|")
    lines.append(f"| 入窗项目数 | {projects} |")
    lines.append(f"| 披露金额项目数 | {summary['with_amount']} |")
    lines.append(f"| 未披露金额项目数 | {summary['without_amount']} |")
    lines.append(f"| 累计中标金额 | {fmt_amount(summary['total_amount'])} |")
    lines.append(f"| 平均金额 | {fmt_amount(int(summary['average_amount']) if summary['average_amount'] else None)} |")
    lines.append(f"| 金额中位数 | {fmt_amount(int(summary['median_amount']) if summary['median_amount'] else None)} |")
    lines.append(f"| 单项目最大金额 | {fmt_amount(summary['max_amount'])} |")
    lines.append(f"| 去重记录数 | {summary['duplicates_removed']} |")

    lines.append("\n## 二、热点招标方向\n")
    lines.append("### 2.1 方向排名\n")
    lines.append("| 排名 | 方向 | 项目数 | 占比 | 累计金额（披露部分） |\n|---|---|---|---|---|")
    for index, row in enumerate(analysis["by_industry"], start=1):
        lines.append(
            f"| {index} | {cell(row['name'])} | {row['count']} | {pct(row['count'], projects)} | {fmt_amount(row['amount'])} |"
        )
    lines.append("\n### 2.2 季度分布\n")
    lines.append("| 季度 | 项目数 | 累计金额（披露部分） |\n|---|---|---|")
    for row in analysis["by_quarter"]:
        lines.append(f"| {row['quarter']} | {row['count']} | {fmt_amount(row['amount'])} |")

    lines.append("\n## 三、中标金额分布\n")
    lines.append("### 3.1 金额区间\n")
    lines.append("| 区间 | 项目数 | 占披露金额项目 |\n|---|---|---|")
    for row in analysis["buckets"]:
        lines.append(f"| {row['label']} | {row['count']} | {pct(row['count'], summary['with_amount'])} |")
    lines.append("\n### 3.2 大额项目 Top 5\n")
    if analysis["top_projects"]:
        lines.append("| 项目 | 采购人 | 中标单位 | 金额 | 公告日期 |\n|---|---|---|---|---|")
        for row in analysis["top_projects"]:
            lines.append(
                f"| {cell(row['title'])} | {cell(row['buyer'])} | {cell(row['winner'])} | "
                f"{fmt_amount(row['amount'])} | {cell(row['date'])} |"
            )
    else:
        lines.append("无可比金额数据。")

    lines.append("\n## 四、地区与采购人分布\n")
    lines.append("### 4.1 地区 Top 5\n")
    if analysis["by_region"]:
        lines.append("| 地区 | 项目数 | 累计金额（披露部分） |\n|---|---|---|")
        for row in analysis["by_region"]:
            lines.append(f"| {cell(row['name'])} | {row['count']} | {fmt_amount(row['amount'])} |")
    else:
        lines.append("无地区数据。")
    lines.append("\n### 4.2 重点采购人 Top 5\n")
    if analysis["top_buyers"]:
        lines.append("| 采购人 | 项目数 | 累计金额（披露部分） |\n|---|---|---|")
        for row in analysis["top_buyers"]:
            lines.append(f"| {cell(row['name'])} | {row['count']} | {fmt_amount(row['amount'])} |")
    else:
        lines.append("无采购人数据。")

    lines.append("\n## 五、结论与建议\n")
    facts: list[str] = []
    if projects:
        top = analysis["by_industry"][0] if analysis["by_industry"] else None
        if top:
            facts.append(
                f"项目数最多的方向为 {top['name']}（{top['count']} 个，占 {pct(top['count'], projects)}，"
                f"披露金额累计 {fmt_amount(top['amount'])}）。"
            )
        if summary["median_amount"] is not None:
            facts.append(
                f"披露金额项目中，中位数为 {fmt_amount(int(summary['median_amount']))}，"
                f"均值为 {fmt_amount(int(summary['average_amount']))}，"
                f"最大单项目为 {fmt_amount(summary['max_amount'])}。"
            )
        big = next((row for row in analysis["buckets"] if row["label"] == ">5000万"), None)
        if big and summary["with_amount"]:
            facts.append(
                f"5000 万元以上大额项目 {big['count']} 个，占披露金额项目的 {pct(big['count'], summary['with_amount'])}。"
            )
        if analysis["top_buyers"]:
            buyer = analysis["top_buyers"][0]
            facts.append(
                f"采购频次最高的采购人为 {buyer['name']}（{buyer['count']} 个项目，"
                f"占 {pct(buyer['count'], projects)}）。"
            )
    if not facts:
        facts.append("本期无入窗项目，无法形成统计结论。")
    lines.extend(f"- {fact}" for fact in facts)
    lines.append("\n> 以上结论均由脚本基于入窗数据直接计算，未使用估算值；未披露金额的项目不参与金额统计。")

    lines.append("\n## 附录：数据口径与校验告警\n")
    lines.append(
        f"- 窗口：{window['start']} 至 {window['end']}（{window['months']} 个月，按自然月计算）\n"
        f"- 窗口外/日期异常剔除：{summary['excluded']} 条\n"
        f"- 去重规则：(公告日期, 项目名称, 采购人) 相同视为重复，保留首条\n"
        f"- 金额换算：亿元 ×1e8，万元 ×1e4，元按原值；无单位数字按元处理并告警\n"
        f"- 中位数/均值只统计披露金额的项目"
    )
    if analysis["amount_notes"]:
        lines.append("\n金额口径告警：")
        lines.extend(f"- {note}" for note in analysis["amount_notes"])
    if analysis["excluded"]:
        lines.append("\n未纳入统计的记录：")
        for record in analysis["excluded"][:20]:
            lines.append(
                f"- {record.get('title')}（{record.get('publish_date') or '无日期'}）：{record['exclude_reason']}"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_file():
        raise SystemExit(f"找不到采集结果：{input_path}，请先运行 collect_bids.py")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    records = data.get("items", [])
    if not records:
        raise SystemExit("采集结果中没有项目记录，无法统计（不会用假数据填充）。")

    as_of = parse_date(args.as_of) if args.as_of else None
    if as_of is None:
        dates = [parse_date(r.get("publish_date")) for r in records]
        as_of = max((d for d in dates if d), default=dt.date.today())
    if as_of is None:
        raise SystemExit("无法确定统计截止日，请传入 --as-of")

    analysis = compute(records, as_of, args.months)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = build_markdown(analysis)

    analysis_file = out_dir / "bids_analysis.json"
    report_file = out_dir / f"ESG投标汇总_{analysis['window']['end']}.md"
    analysis_file.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    report_file.write_text(markdown, encoding="utf-8")

    s = analysis["summary"]
    print(f"统计窗口：{analysis['window']['start']} ~ {analysis['window']['end']}")
    print(
        f"入窗项目 {s['projects']} 个（披露金额 {s['with_amount']} 个），"
        f"累计 {fmt_amount(s['total_amount'])}，中位数 {fmt_amount(int(s['median_amount']) if s['median_amount'] else None)}"
    )
    print(f"输出：{report_file}")
    print(f"      {analysis_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
