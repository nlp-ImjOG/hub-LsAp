"""分布统计:纯确定性算法。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, asdict
from statistics import mean, median

from .extract import BidRecord, CATEGORIES

AMOUNT_BINS = [
    ("<100万", 0, 100),
    ("100–500万", 100, 500),
    ("500–1000万", 500, 1000),
    ("1000–5000万", 1000, 5000),
    (">5000万", 5000, float("inf")),
]


@dataclass
class Stats:
    total: int = 0
    with_amount: int = 0
    total_amount_wan: float = 0.0
    avg_amount_wan: float = 0.0
    median_amount_wan: float = 0.0
    by_category: dict = None
    by_amount_bin: dict = None
    top10_by_amount: list = None
    by_cred: dict = None

    def to_dict(self) -> dict:
        return asdict(self)


def compute(records: list[BidRecord]) -> Stats:
    amounts = [r.amount_wan for r in records if r.amount_wan and r.amount_wan > 0]
    cat_counter = Counter(CATEGORIES[r.category] for r in records)
    cred_counter = Counter(r.source_cred for r in records)

    bins = {label: 0 for label, _, _ in AMOUNT_BINS}
    for a in amounts:
        for label, lo, hi in AMOUNT_BINS:
            if lo <= a < hi:
                bins[label] += 1
                break

    top10 = sorted(
        [r for r in records if r.amount_wan],
        key=lambda r: r.amount_wan,
        reverse=True,
    )[:10]

    return Stats(
        total=len(records),
        with_amount=len(amounts),
        total_amount_wan=round(sum(amounts), 2),
        avg_amount_wan=round(mean(amounts), 2) if amounts else 0,
        median_amount_wan=round(median(amounts), 2) if amounts else 0,
        by_category=dict(cat_counter),
        by_amount_bin={k: bins[k] for k in [l for l, _, _ in AMOUNT_BINS]},
        top10_by_amount=[
            {"title": r.title, "winner": r.winner, "amount_wan": r.amount_wan, "url": r.url}
            for r in top10
        ],
        by_cred=dict(cred_counter),
    )


def render_table(records: list[BidRecord]) -> str:
    """渲染项目明细 Markdown 表格。"""
    header = "| # | 项目名称 | 招标单位 | 中标单位 | 金额(万元) | 日期 | 类别 | 可信度 | 来源 |\n|---|---|---|---|---|---|---|---|---|\n"
    rows = []
    for i, r in enumerate(records, 1):
        amt = f"{r.amount_wan}" if r.amount_wan else "待核实"
        rows.append(
            f"| {i} | {r.title[:30]} | {r.bidder[:15]} | {r.winner[:15]} | {amt} | {r.date} | {CATEGORIES[r.category]} | {r.source_cred} | [链接]({r.url}) |"
        )
    return header + "\n".join(rows)
