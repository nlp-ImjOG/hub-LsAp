"""ESG 投标情报脚本入口：历史复盘 + 每日监控。

在 skill 根目录运行：
    python scripts/run.py review --start 2024-12 --end 2026-11 --offline
    python scripts/run.py daily --date 2026-11-26 --days 14 --offline
    python scripts/run.py review --dry-run --start 2024-12 --end 2026-11
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date
from pathlib import Path

from tender.pipeline import (
    ConfigError,
    compute_daily_window,
    compute_review_window,
    generate_daily,
    generate_review,
)
from tender.queries import build_daily_queries, build_review_queries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ESG 投标情报：历史复盘 + 每日监控 + Markdown 台账")
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="近 N 年 ESG/双碳中标复盘")
    review.add_argument("--focus", default="ESG/双碳", help="关注方向，默认 ESG/双碳")
    review.add_argument("--start", default=None, help="开始月份 YYYY-MM，默认结束月前两年")
    review.add_argument("--end", default=None, help="结束月份 YYYY-MM，默认上一个自然月")
    review.add_argument("--offline", action="store_true", help="使用固定 fixture")
    review.add_argument("--dry-run", action="store_true", help="只打印检索词")
    review.add_argument("--max-sources", type=int, default=None)
    review.add_argument("--out", default="reports")
    review.add_argument("--env-file", default=None)
    review.add_argument("--verbose", action="store_true")

    daily = sub.add_parser("daily", help="每日新增招标监控与日报")
    daily.add_argument("--date", default=None, help="日报日期 YYYY-MM-DD，默认今天")
    daily.add_argument("--days", type=int, default=7, help="回看天数，默认 7")
    daily.add_argument("--offline", action="store_true", help="使用固定 fixture")
    daily.add_argument("--dry-run", action="store_true", help="只打印检索词")
    daily.add_argument("--max-sources", type=int, default=None)
    daily.add_argument("--out", default="reports")
    daily.add_argument("--ledger", default=None, help="台账路径，默认 reports/ESG招标跟踪台账.md")
    daily.add_argument("--no-fetch", action="store_true", help="不抓正文，直接用搜索摘要")
    daily.add_argument("--env-file", default=None)
    daily.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if getattr(args, "no_fetch", False):
        os.environ["FETCH_ENABLED"] = "false"

    today = date.today()
    try:
        if args.command == "review":
            start, end = compute_review_window(args.start, args.end, today)
            if args.dry_run:
                queries = build_review_queries(start.year, end.year)
                print(f"检索词 {len(queries)} 条（{start} ~ {end}）：")
                for index, query in enumerate(queries, start=1):
                    print(f"{index:02d}. [{query.category}] {query.text}")
                return 0
            result = asyncio.run(
                generate_review(
                    args.focus,
                    args.start,
                    args.end,
                    offline=args.offline,
                    out_dir=Path(args.out),
                    env_file=args.env_file,
                    max_sources=args.max_sources,
                )
            )
        else:
            report_date = date.fromisoformat(args.date) if args.date else today
            if args.dry_run:
                window_start, window_end = compute_daily_window(report_date, args.days)
                queries = build_daily_queries(report_date, args.days)
                print(f"检索词 {len(queries)} 条（{window_start} ~ {window_end}）：")
                for index, query in enumerate(queries, start=1):
                    print(f"{index:02d}. [{query.category}] {query.text}")
                return 0
            result = asyncio.run(
                generate_daily(
                    report_date,
                    args.days,
                    offline=args.offline,
                    out_dir=Path(args.out),
                    ledger_path=Path(args.ledger) if args.ledger else None,
                    env_file=args.env_file,
                    max_sources=args.max_sources,
                )
            )
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI 顶层兜底
        logging.exception("生成失败")
        print(f"生成失败：{exc}", file=sys.stderr)
        return 1

    print(f"报告已生成：{result.markdown_path}")
    if result.ledger_path:
        print(f"台账：{result.ledger_path}")
    print(f"运行记录：{result.run_path}")
    if result.warnings:
        print(f"警告 {len(result.warnings)} 条：")
        for warning in result.warnings[:10]:
            print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
