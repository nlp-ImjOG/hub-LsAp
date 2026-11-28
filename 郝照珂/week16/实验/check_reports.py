"""Audit the four submitted reports against the FY2025 Apple financial statement tables."""
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Apple's FY2025 Q4 consolidated financial statements, pp. 1–3. Columns: FY2024, FY2025.
SALES = {
    "iPhone": (201183, 209586), "Mac": (29984, 33708), "iPad": (26694, 28023),
    "可穿戴设备、家居与配件": (37005, 35686), "服务": (96169, 109158),
    "美洲": (167045, 178353), "欧洲": (101328, 111032), "大中华区": (66952, 64377),
    "日本": (25052, 28703), "亚太其他地区": (30658, 33696),
}
D = Decimal
FINANCE = {
    r"净销售额": (391035, 416161), r"毛利": (180683, 195201), r"营业利润": (123216, 133050),
    r"净利润": (93736, 112010), r"(总资产|资产总额)": (364980, 359241),
    r"(总负债|负债总额)": (308030, 285508), r"股东权益": (56950, 73733),
    r"流动资产": (152987, 147957), r"流动负债": (176392, 165631),
    r"经营活动净?现金流": (118254, 111482), r"购建固定资产现金支出.*": (9447, 12715),
    r"自由现金流（.*": (108807, 98767),
    r"(经营现金流／净利润|利润现金转换率)": (100 * D(118254) / 93736, 100 * D(111482) / 112010),
    r"流动比率.*": (D(152987) / 176392, D(147957) / 165631),
    r"营业利润率.*": (100 * D(123216) / 391035, 100 * D(133050) / 416161),
}


def report_rows(path):
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("|"):
            cells = [c.strip().replace("*", "") for c in line.strip("|").split("|")]
            cells[0] = cells[0].replace("其他亚太地区", "亚太其他地区")
            rows.append(cells)
    return rows


def check(rows, reference):
    correct = 0
    differences = []
    for label, expected_values in reference.items():
        row = next((cells for cells in rows if re.fullmatch(label, cells[0])), [])
        for column, value in enumerate(expected_values, 1):
            if len(row) <= column:
                differences.append(f"{label} [{column}] 缺项")
                continue
            cell = re.sub(r"[,%倍\s]", "", row[column]).replace("−", "-")
            actual = D(cell)
            unit = D(1).scaleb(actual.as_tuple().exponent)
            expected = D(value).quantize(unit, rounding=ROUND_HALF_UP)
            if actual == expected:
                correct += 1
            else:
                differences.append(f"{row[0]} [{column}] 报告 {actual}，应为 {expected}")
    return correct, differences


def main():
    sales_reference = {}
    for label, (prior, current) in SALES.items():
        change = current - prior
        sales_reference[label] = (prior, current, change, D(100 * change) / prior,
                                  D(100 * current) / 416161, D(100 * change) / 25126)
    all_problems = []
    for group in ("实验/无脚本输出", "报告"):
        for title, reference in (("销售分析", sales_reference), ("财务分析", FINANCE)):
            correct, differences = check(report_rows(ROOT / group / f"{title}.md"), reference)
            total = sum(len(values) for values in reference.values())
            print(f"{group} {title}: {correct}/{total}")
            all_problems.extend(differences)
    for problem in all_problems:
        print(problem)
    return int(bool(all_problems))


if __name__ == "__main__":
    sys.exit(main())
