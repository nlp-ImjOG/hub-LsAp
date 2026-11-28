"""月度调度辅助脚本：判断今天是否是本月第 1 个工作日，并输出上个月 `YYYY-MM`。

OpenCode 没有内置调度器，cron 只能按固定日期触发。本脚本把“第 1 个工作日”
和 `target_month` 的计算集中到可测试的 Python 代码里，避免让模型在非交互的
`opencode run` 中自行推断“上个月”。

工作日默认按周一至周五计算；中国法定节假日通过 `--holiday` 显式传入
（可重复），节假日顺延到下一个工作日。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

EXIT_NOT_TODAY = 3


def first_workday(year: int, month: int, holidays: set[str]) -> date:
    current = date(year, month, 1)
    limit = date(year, month, 1) + timedelta(days=31)
    while current < limit:
        if current.weekday() < 5 and current.isoformat() not in holidays:
            return current
        current += timedelta(days=1)
    raise ValueError(f"{year:04d}-{month:02d} 没有可用工作日")


def target_month_for(today: date, holidays: set[str] | None = None) -> str | None:
    """今天命中本月第 1 个工作日时返回上个月，否则返回 None。"""

    holidays = holidays or set()
    if today != first_workday(today.year, today.month, holidays):
        return None

    first_of_month = today.replace(day=1)
    previous = first_of_month - timedelta(days=1)
    return f"{previous.year:04d}-{previous.month:02d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="判断是否为本月第 1 个工作日，并输出上个月 YYYY-MM"
    )
    parser.add_argument(
        "--today",
        default=None,
        help="覆盖今天，格式 YYYY-MM-DD；用于测试或补跑",
    )
    parser.add_argument(
        "--holiday",
        action="append",
        default=None,
        help="法定节假日 YYYY-MM-DD，可重复；节假日顺延到下一个工作日",
    )
    args = parser.parse_args(argv)

    if args.today:
        try:
            today = date.fromisoformat(args.today)
        except ValueError:
            print(f"错误：--today 必须是 YYYY-MM-DD，收到 {args.today!r}", file=sys.stderr)
            return 2
    else:
        today = date.today()

    holidays = set(args.holiday or [])
    target_month = target_month_for(today, holidays)
    if target_month is None:
        expected = first_workday(today.year, today.month, holidays)
        print(
            f"今天 {today.isoformat()} 不是本月第 1 个工作日"
            f"（应为 {expected.isoformat()}），跳过。",
            file=sys.stderr,
        )
        return EXIT_NOT_TODAY

    print(target_month)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
