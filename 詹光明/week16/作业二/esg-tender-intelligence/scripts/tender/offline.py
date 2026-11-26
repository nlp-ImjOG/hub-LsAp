"""离线样例：用固定 fixture 跑通复盘与日报。"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from .models import DailyInsights, DailyReport, ReviewInsights, ReviewReport, Source, Tender

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _load(name: str) -> object:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _tenders(name: str) -> list[Tender]:
    return [Tender(**row) for row in _load(name)]  # type: ignore[union-attr]


def _sources(name: str) -> list[Source]:
    return [Source(**row) for row in _load(name)]  # type: ignore[union-attr]


def build_offline_review(
    focus: str, period_start: date, period_end: date, generated_at: date
) -> ReviewReport:
    tenders = [
        tender
        for tender in _tenders("review_tenders.json")
        if (tender.year or 0) == 0 or period_start.year <= (tender.year or 0) <= period_end.year
    ]
    report = ReviewReport(
        focus=focus,
        period_start=period_start,
        period_end=period_end,
        generated_at=generated_at,
        tenders=tenders,
        sources=_sources("review_sources.json"),
        insights=ReviewInsights(**_load("review_insights.json")),  # type: ignore[arg-type]
        query_log=_load("review_queries.json"),  # type: ignore[arg-type]
        offline=True,
    )
    report.gaps.extend(
        [
            "本报告为离线样例，使用固定 fixture 数据，不代表实时检索结果。",
            "样本为 51 条公开可核实项目，其中 3 条为第一候选人/预成交报价，已在明细中标注。",
        ]
    )
    if (period_start, period_end) != (date(2024, 12, 1), date(2026, 11, 30)):
        report.gaps.append(
            f"离线 fixture 固定为 2024-12 至 2026-11；当前窗口 {period_start} 至 {period_end} 仅用于演示。"
        )
    return report


def build_offline_daily(
    report_date: date,
    window_start: date,
    window_end: date,
    ledger_path: Path,
) -> DailyReport:
    report = DailyReport(
        report_date=report_date,
        window_start=window_start,
        window_end=window_end,
        tenders=_tenders("daily_tenders.json"),
        reference_tenders=_tenders("daily_reference.json"),
        insights=DailyInsights(**_load("daily_insights.json")),  # type: ignore[arg-type]
        ledger_path=str(ledger_path),
        query_log=_load("daily_queries.json"),  # type: ignore[arg-type]
        offline=True,
    )
    report.gaps.extend(
        [
            "本报告为离线样例，使用固定 fixture 数据，不代表实时检索结果。",
            "临空经济区 836 万为估算、公告日期待核实；宁波舟山港预算与资格条件未披露。",
        ]
    )
    if (window_start, window_end) != (date(2026, 11, 13), date(2026, 11, 26)):
        report.gaps.append(
            f"离线 fixture 固定为 2026-11-13 至 2026-11-26；当前窗口 {window_start} 至 {window_end} 仅用于演示。"
        )
    return report


def top_by_category(tenders: list[Tender], limit: int = 3) -> dict[str, list[Tender]]:
    grouped: dict[str, list[Tender]] = defaultdict(list)
    for tender in tenders:
        grouped[tender.category or "其他"].append(tender)
    return {
        category: sorted(items, key=lambda t: t.amount or 0, reverse=True)[:limit]
        for category, items in grouped.items()
    }
