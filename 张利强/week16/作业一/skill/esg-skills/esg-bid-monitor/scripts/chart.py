"""ESG 招投标金额分桶图。

分桶固定为 (0,50]、(50,100]、(100,200]、(200,500]、(>500]，单位为万元。
有效记录 >=5 时输出柱状图 + 饼图；1-4 条只输出柱状图并标注样本量；
0 条不生成文件。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

BUCKET_LABELS = ["≤50万", "50-100万", "100-200万", "200-500万", ">500万"]
BUCKET_BINS = [0, 50, 100, 200, 500, float("inf")]
FONT_CANDIDATES = ["PingFang SC", "Heiti TC", "STHeiti", "Arial Unicode MS", "DejaVu Sans"]


def parse_amount_wan(value: object) -> float | None:
    """只接受正数与纯数字字符串（允许千分位逗号）；单位、负数、0 返回 None。"""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None

    if not math.isfinite(number) or number <= 0:
        return None
    return number


def bucket_amounts(values: list[float]) -> dict[str, int]:
    if not values:
        return {label: 0 for label in BUCKET_LABELS}
    series = pd.cut(
        pd.Series(values, dtype="float64"),
        bins=BUCKET_BINS,
        labels=BUCKET_LABELS,
        right=True,
    )
    counts = series.value_counts().reindex(BUCKET_LABELS, fill_value=0)
    return {label: int(counts[label]) for label in BUCKET_LABELS}


def _setup_font() -> None:
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    chosen = [name for name in FONT_CANDIDATES if name in available]
    if not chosen:
        print(
            "警告：未找到候选中文字体，图表中的中文可能显示为方框。",
            file=sys.stderr,
        )
    plt.rcParams["font.sans-serif"] = chosen + ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def _is_tender(record: dict) -> bool:
    return record.get("announcement_type") == "tender"


def generate_chart(
    records: list[dict],
    output_prefix: str,
    title: str | None = None,
    scope: str = "award",
) -> dict:
    if scope not in {"award", "all"}:
        raise ValueError("scope 只能是 award 或 all")

    candidates = [record for record in records if isinstance(record, dict)]
    if scope == "award":
        amount_records = [record for record in candidates if not _is_tender(record)]
        excluded = len(candidates) - len(amount_records)
    else:
        amount_records = candidates
        excluded = 0

    amounts = [parse_amount_wan(record.get("amount_wan")) for record in amount_records]
    values = [amount for amount in amounts if amount is not None]
    counts = bucket_amounts(values)
    output = f"{output_prefix}.png"

    if not values:
        Path(output).unlink(missing_ok=True)
        if excluded:
            note = (
                f"仅统计中标金额，已排除 {excluded} 条招标公告预算；"
                "无有效中标金额，未生成图表"
            )
        else:
            note = "无有效金额，未生成图表"
        return {
            "generated": False,
            "chart": None,
            "records": len(records),
            "valid_amounts": 0,
            "buckets": counts,
            "output": None,
            "note": note,
        }

    _setup_font()
    labels = BUCKET_LABELS
    counts_list = [counts[label] for label in labels]
    chart_title = title or "ESG 招投标金额分布"

    notes: list[str] = []
    if excluded:
        notes.append(f"仅统计中标金额，已排除 {excluded} 条招标公告预算")
    if len(values) < 5:
        notes.append("样本量较小，分布仅供参考")
    note = "；".join(notes) or None

    if len(values) >= 5:
        fig, (ax_bar, ax_pie) = plt.subplots(1, 2, figsize=(12, 5))
        ax_bar.bar(labels, counts_list, color="#4C78A8")
        ax_bar.set_title("金额分桶（项目数）")
        ax_bar.set_ylabel("项目数")
        ax_bar.tick_params(axis="x", rotation=20)
        ax_pie.pie(
            counts_list,
            labels=labels,
            autopct="%1.0f%%",
            startangle=90,
            colors=plt.cm.Blues([0.35, 0.45, 0.55, 0.65, 0.75]),
        )
        ax_pie.set_title("金额分桶占比")
        chart_type = "bar+pie"
    else:
        fig, ax_bar = plt.subplots(figsize=(8, 5))
        ax_bar.bar(labels, counts_list, color="#4C78A8")
        ax_bar.set_title(f"{chart_title}（样本量较小，分布仅供参考）")
        ax_bar.set_ylabel("项目数")
        ax_bar.tick_params(axis="x", rotation=20)
        chart_type = "bar"

    fig.suptitle(chart_title)
    fig.tight_layout()
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)

    return {
        "generated": True,
        "chart": chart_type,
        "records": len(records),
        "valid_amounts": len(values),
        "buckets": counts,
        "output": output,
        "note": note,
    }


def _load_records(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        if "records" not in data:
            raise ValueError("对象输入必须包含 records 键")
        data = data["records"]
    if not isinstance(data, list):
        raise ValueError("输入必须是记录数组或包含 records 的对象")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 ESG 招投标金额分桶图")
    parser.add_argument("--input", required=True, help="记录 JSON 文件")
    parser.add_argument("--output-prefix", required=True, help="输出 PNG 前缀")
    parser.add_argument("--title", default=None, help="图表标题")
    parser.add_argument(
        "--scope",
        choices=("award", "all"),
        default="award",
        help="award=只统计中标金额（默认），all=同时统计招标预算",
    )
    args = parser.parse_args(argv)

    try:
        records = _load_records(args.input)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：无法读取 {args.input}: {exc}", file=sys.stderr)
        return 2

    try:
        result = generate_chart(
            records, args.output_prefix, title=args.title, scope=args.scope
        )
    except Exception as exc:  # noqa: BLE001 - CLI 边界统一转成退出码 2
        print(f"错误：生成图表失败：{exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
