#!/usr/bin/env python3
"""Check basic citation and structure requirements of a Markdown report."""

import re
import sys
from pathlib import Path

REQUIRED = [
    "摘要",
    "方法",
    "关键发现",
    "风险",
    "来源",
]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_report.py report.md")
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    citations = set(re.findall(r"\[S(\d+)\]", text))
    missing_sections = [name for name in REQUIRED if name not in text]
    problems = []
    if not citations:
        problems.append("未发现 [S01] 形式的引用")
    if missing_sections:
        problems.append("缺少章节: " + ", ".join(missing_sections))
    if len(text) < 800:
        problems.append("报告长度过短，可能缺少必要论证")
    if problems:
        print("FAIL")
        for item in problems:
            print("- " + item)
        raise SystemExit(1)
    print("PASS")
    print(f"引用数量: {len(citations)}")


if __name__ == "__main__":
    main()