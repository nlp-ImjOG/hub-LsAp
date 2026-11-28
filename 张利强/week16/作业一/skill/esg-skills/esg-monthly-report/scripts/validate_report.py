"""校验 ESG 月报的引用与日期。

规则（与 SKILL.md 保持一致）：
- 跳过标题、空行、分隔线、代码围栏、引用块。
- 其余非空行必须含 ``[来源: http(s)://...]``，或整行为“暂无数据”。
- 剥离 URL 后出现的日期必须落在目标自然月内。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

CITATION_RE = re.compile(r"\[来源:\s*https?://[^\]]+\]")
URL_RE = re.compile(r"https?://\S+")
DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
SLASH_DATE_RE = re.compile(r"(?<!\d)(\d{4})/(\d{1,2})/(\d{1,2})(?!\d)")
CN_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
CN_MONTH_RE = re.compile(r"(?<!\d)(\d{4})年(\d{1,2})月(?!\d)")
NO_DATA_LINES = {"暂无数据", "暂无数据。"}
TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?$")


def _target_month(month: str) -> tuple[int, int]:
    try:
        parsed = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise ValueError(f"month must be YYYY-MM, got {month!r}") from exc
    return parsed.year, parsed.month


def _check_date(year: int, month: int, day: int, target: tuple[int, int]) -> str | None:
    try:
        date(year, month, day)
    except ValueError:
        return "日期无效"
    if (year, month) != target:
        return "日期越界"
    return None


def validate_report_text(text: str, month: str) -> dict:
    target = _target_month(month)
    violations: list[dict] = []
    checked_lines = 0
    in_code = False

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()

        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line:
            continue
        if line.startswith("#") or line.startswith(">"):
            continue
        if line in {"---", "***", "___"}:
            continue
        if "-" in line and TABLE_SEPARATOR_RE.fullmatch(line):
            continue

        checked_lines += 1

        content = re.sub(r"^([-*]|\d+[.)])\s+", "", line).strip() or line
        if content in NO_DATA_LINES:
            continue

        if not CITATION_RE.search(line):
            violations.append({"line": number, "reason": "缺少 [来源: URL]"})

        without_urls = URL_RE.sub("", content)
        dates: list[tuple[int, int, int]] = []
        dates.extend((int(y), int(m), int(d)) for y, m, d in DATE_RE.findall(without_urls))
        dates.extend((int(y), int(m), int(d)) for y, m, d in SLASH_DATE_RE.findall(without_urls))
        cn_date_matches = list(CN_DATE_RE.finditer(without_urls))
        dates.extend(
            (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            for match in cn_date_matches
        )
        for year, mon, day in dates:
            reason = _check_date(year, mon, day, target)
            if reason:
                violations.append(
                    {
                        "line": number,
                        "reason": f"{reason}：{year:04d}-{mon:02d}-{day:02d}",
                    }
                )

        for match in CN_MONTH_RE.finditer(without_urls):
            if any(
                covered.start() <= match.start() and match.end() <= covered.end()
                for covered in cn_date_matches
            ):
                continue
            year, mon = int(match.group(1)), int(match.group(2))
            reason = _check_date(year, mon, 1, target)
            if reason:
                violations.append(
                    {"line": number, "reason": f"{reason}：{year:04d}-{mon:02d}"}
                )

    if checked_lines == 0:
        violations.append({"line": 0, "reason": "报告为空，没有任何可校验内容"})

    return {
        "ok": not violations,
        "month": month,
        "violations": violations,
        "checked_lines": checked_lines,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 ESG 月报的引用与日期")
    parser.add_argument("--file", required=True, help="待校验的 Markdown 文件")
    parser.add_argument("--month", required=True, help="目标自然月，格式 YYYY-MM")
    args = parser.parse_args(argv)

    try:
        text = Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"错误：无法读取 {args.file}: {exc}", file=sys.stderr)
        return 2

    try:
        result = validate_report_text(text, args.month)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
