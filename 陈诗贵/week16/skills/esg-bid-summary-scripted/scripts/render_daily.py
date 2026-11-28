"""ESG 招标日报：按日期过滤 + 确定性关注度规则 + 模板渲染（不调用 LLM）。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from analyze_bids import fmt_amount, parse_amount, parse_date, record_key

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = SKILL_ROOT / "output"

KEYWORDS = ("ESG", "双碳", "碳", "绿电", "CCUS", "甲烷", "可持续", "节能", "减排")
LEVEL_ORDER = {"高": 0, "中": 1, "低": 2}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ESG 招标日报（确定性渲染）")
    parser.add_argument("--input", default=str(DEFAULT_OUT_DIR / "bids_raw.json"))
    parser.add_argument("--date", default=None, help="日报日期 YYYY-MM-DD，默认取数据中的最新日期")
    parser.add_argument("--out", default=None)
    return parser.parse_args(argv)


def attention_level(record: dict, amount: int | None) -> tuple[str, str]:
    has_keyword = any(keyword in record["title"] for keyword in KEYWORDS)
    if amount is not None and amount >= 50_000_000:
        return "高", "金额超过 5000 万元"
    if amount is not None and amount >= 10_000_000:
        return ("高" if has_keyword else "中"), ("金额超过 1000 万元" + ("，且标题含 ESG 相关关键词" if has_keyword else ""))
    if has_keyword:
        return "中", "标题含 ESG/双碳相关关键词"
    return "低", "金额较小且未命中关键词"


def cell(text: str | None) -> str:
    return (text or "-").replace("|", "／").replace("\n", " ").strip()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_file():
        raise SystemExit(f"找不到采集结果：{input_path}，请先运行 collect_bids.py")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    records = data.get("items", [])

    target = parse_date(args.date) if args.date else None
    if target is None and not args.date:
        dates = [parse_date(r.get("publish_date")) for r in records]
        target = max((d for d in dates if d), default=dt.date.today())
    if target is None:
        raise SystemExit("--date 必须是 YYYY-MM-DD")

    daily = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        if parse_date(record.get("publish_date")) != target or record.get("date_unverified"):
            continue
        key = record_key(record)
        if key in seen:
            continue
        seen.add(key)
        daily.append({**record, "amount_yuan": parse_amount(record.get("amount_raw"))[0]})
    rows = []
    for record in daily:
        level, reason = attention_level(record, record["amount_yuan"])
        rows.append({**record, "level": level, "reason": reason})
    rows.sort(key=lambda r: (LEVEL_ORDER[r["level"]], -(r["amount_yuan"] or 0), r["title"]))

    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"ESG招标日报_{target.isoformat()}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [f"# ESG 招标日报（{target.isoformat()}）\n"]
    if not rows:
        lines.append("当日无新增 ESG 相关招标。\n")
        lines.append("> 说明：本日报只统计公告日期等于当日的记录；未使用历史数据填充。")
    else:
        lines.append(f"共 {len(rows)} 条新增相关招标。\n")
        lines.append("| # | 关注度 | 方向 | 项目名称 | 采购人 | 中标单位 | 金额 | 公告日期 | 来源 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for index, row in enumerate(rows, start=1):
            lines.append(
                f"| {index} | {row['level']} | {cell(row.get('industry'))} | {cell(row['title'])} | "
                f"{cell(row.get('buyer'))} | {cell(row.get('winner'))} | {fmt_amount(row['amount_yuan'])} | "
                f"{cell(row.get('publish_date'))} | {cell(row.get('source'))} |"
            )
        high = [row for row in rows if row["level"] == "高"]
        lines.append("\n## 重点关注\n")
        if high:
            for row in high:
                lines.append(
                    f"- **{row['title']}**（{row.get('industry') or '方向未注明'}）："
                    f"{row['reason']}；金额 {fmt_amount(row['amount_yuan'])}。"
                    f"{('采购人：' + row['buyer'] + '。') if row.get('buyer') else ''}"
                    f"{('来源：' + row['url']) if row.get('url') else ''}"
                )
        else:
            lines.append("当日无需重点关注的项目。")
        lines.append(
            "\n> 关注度规则（脚本确定性执行）：金额 ≥5000 万元为“高”；≥1000 万元为“中”，"
            "标题含 ESG 相关关键词时升为“高”；其余命中关键词为“中”，否则为“低”。"
        )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"当日记录 {len(rows)} 条（高 {sum(1 for r in rows if r['level'] == '高')} / 中 {sum(1 for r in rows if r['level'] == '中')} / 低 {sum(1 for r in rows if r['level'] == '低')}）")
    print(f"输出：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
