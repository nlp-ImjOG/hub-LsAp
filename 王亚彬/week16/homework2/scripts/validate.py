"""校验报告格式：三块齐全、每条有链接和日期。

用法：
    python validate.py report.md
"""
import re
import sys


def check(path: str) -> dict:
    text = open(path, encoding="utf-8").read()
    sections = ["## 一、", "## 二、", "## 三、"]
    result = {
        "sections_present": {s: s in text for s in sections},
        "link_count": len(re.findall(r"\[[^\]]+\]\(https?://[^)]+\)", text)),
        "date_count": len(re.findall(r"\d{4}-\d{2}-\d{2}", text)),
    }
    result["passed"] = (
        all(result["sections_present"].values())
        and result["link_count"] >= 6
        and result["date_count"] >= 6
    )
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python validate.py report.md")
        sys.exit(1)
    r = check(sys.argv[1])
    print(r)
    sys.exit(0 if r["passed"] else 1)
