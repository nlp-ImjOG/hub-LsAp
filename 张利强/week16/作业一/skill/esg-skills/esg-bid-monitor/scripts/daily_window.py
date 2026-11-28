"""计算每日推送窗口：`[昨天 00:00, 今天 00:00]`（Asia/Shanghai）。

宿主机时区不一定是 UTC+8，因此窗口在这里用 `zoneinfo` 显式计算，
cron / launchd 只负责按本地时间发起调用。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TIMEZONE = "Asia/Shanghai"


def compute_window(now: datetime | None = None) -> dict[str, str]:
    tz = ZoneInfo(TIMEZONE)
    current = (now or datetime.now(tz)).astimezone(tz)
    today = current.date()
    start = datetime.combine(today - timedelta(days=1), time.min, tzinfo=tz)
    end = datetime.combine(today, time.min, tzinfo=tz)
    return {
        "timezone": TIMEZONE,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="输出每日推送窗口（Asia/Shanghai）"
    )
    parser.add_argument(
        "--now",
        default=None,
        help="覆盖当前时间，ISO 8601 格式；用于测试或补跑",
    )
    args = parser.parse_args(argv)

    now = None
    if args.now:
        try:
            now = datetime.fromisoformat(args.now)
        except ValueError:
            print(f"错误：--now 不是合法 ISO 8601 时间：{args.now!r}", file=sys.stderr)
            return 2
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo(TIMEZONE))

    print(json.dumps(compute_window(now), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
