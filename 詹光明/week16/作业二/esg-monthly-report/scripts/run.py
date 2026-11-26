"""ESG 月报脚本入口。

在 skill 根目录运行：
    python scripts/run.py --offline --client 中国神华 --industry 煤炭 --month 2026-10
    python scripts/run.py --client 中国神华 --industry 煤炭 --month 2026-10
    python scripts/run.py --dry-run --month 2026-10
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from esg_report.pipeline import ConfigError, generate, preview_queries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ESG 月报生成器（检索 + 筛选 + LLM 抽取 + 质量校验）")
    parser.add_argument("--client", default="中国神华", help="客户名称，默认 中国神华")
    parser.add_argument("--industry", default="煤炭", help="所属行业，默认 煤炭")
    parser.add_argument(
        "--month",
        default=None,
        help="报告期 YYYY-MM；默认上一个自然月",
    )
    parser.add_argument("--offline", action="store_true", help="使用固定 fixture，不调用搜索/LLM")
    parser.add_argument("--dry-run", action="store_true", help="只打印检索词，不执行")
    parser.add_argument("--no-fetch", action="store_true", help="不抓取网页正文，直接用搜索摘要")
    parser.add_argument("--max-sources", type=int, default=None, help="最多分析多少条来源")
    parser.add_argument("--out", default="reports", help="输出目录，默认 reports")
    parser.add_argument("--env-file", default=None, help="指定 .env 路径")
    parser.add_argument("--verbose", action="store_true", help="打印调试日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.no_fetch:
        os.environ["FETCH_ENABLED"] = "false"

    if args.dry_run:
        queries = preview_queries(args.client, args.industry, args.month)
        print(f"检索词 {len(queries)} 条：")
        for index, query in enumerate(queries, start=1):
            print(f"{index:02d}. [{query.category.value}] {query.text}")
        return 0

    try:
        result = asyncio.run(
            generate(
                args.client,
                args.industry,
                args.month,
                offline=args.offline,
                out_dir=Path(args.out),
                env_file=args.env_file,
                max_sources=args.max_sources,
            )
        )
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI 顶层兜底，打印可读错误
        logging.exception("生成失败")
        print(f"生成失败：{exc}", file=sys.stderr)
        return 1

    report = result.report
    print(f"报告已生成：{result.markdown_path}")
    print(
        f"来源 {len(report.sources)} 条｜条目 {len(report.items)} 条｜"
        f"警告 {len(result.warnings)} 条｜离线={report.offline}"
    )
    if result.warnings:
        for warning in result.warnings:
            print(f"  - {warning}")
    print(f"来源 JSON：{result.sources_path}")
    print(f"运行记录：{result.run_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
