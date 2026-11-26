"""离线样例模式：用固定 fixture 跑通完整流水线，不需要 API Key。

用途：
1. 没配 Key 时也能演示报告结构；
2. 单元测试不依赖网络；
3. 作为“检索/抽取失败”时的兜底输出样例。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from .models import Executive, Item, ReportData, Source

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _load(name: str) -> object:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value).date()


def build_offline_report(
    client: str,
    industry: str,
    period_start: date,
    period_end: date,
    generated_at: date,
) -> ReportData:
    sources = [
        Source(
            **{
                **row,
                "published_at": _parse_date(row.get("published_at")),
            }
        )
        for row in _load("sample_sources.json")  # type: ignore[union-attr]
    ]
    items = [Item(**row) for row in _load("sample_items.json")]  # type: ignore[union-attr]
    executive = Executive(**_load("sample_executive.json"))  # type: ignore[arg-type]
    query_log = _load("sample_queries.json")  # type: ignore[assignment]

    gaps = [
        "本报告为离线样例，使用固定 fixture 数据，不代表实时检索结果。",
        "S17 为评级背景（2026-06-29），不在报告期内；S18 为 11-19 发布的报告期后数据，已在正文标注。",
    ]
    if client != "中国神华" or industry != "煤炭":
        gaps.append(
            f"离线 fixture 固定为中国神华/煤炭；当前参数（{client}/{industry}）仅用于演示流程。"
        )
    if period_start != date(2026, 10, 1):
        gaps.append(
            f"离线 fixture 固定为 2026-10；当前报告期 {period_start} 至 {period_end} 仅用于演示流程。"
        )

    return ReportData(
        client=client,
        industry=industry,
        period_start=period_start,
        period_end=period_end,
        generated_at=generated_at,
        summary=executive.summary,
        items=items,
        sources=sources,
        executive=executive,
        gaps=gaps,
        query_log=query_log,  # type: ignore[arg-type]
        offline=True,
    )
