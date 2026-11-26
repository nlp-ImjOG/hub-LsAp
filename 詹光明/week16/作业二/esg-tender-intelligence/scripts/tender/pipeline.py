"""主流程：历史复盘 + 每日监控。"""

from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import Settings, load_settings
from .fetch import Fetcher
from .filter import assign_sids, dedupe_sources, dedupe_tenders, priority
from .ledger import load_ledger, merge_ledger, save_ledger
from .llm import LLMClient, extract_tenders, write_daily_insights, write_review_insights
from .models import DailyReport, ReviewReport, RunResult, Source, Tender, TenderStatus
from .offline import build_offline_daily, build_offline_review, top_by_category
from .queries import Query, build_daily_queries, build_review_queries
from .report import write_daily, write_review
from .search import BochaSearchClient
from .stats import compute_stats

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    pass


def _parse_month(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.split("-", 1))
        if not 1 <= month <= 12:
            raise ValueError
        return year, month
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"月份格式应为 YYYY-MM，收到 {value!r}") from exc


def compute_review_window(start: str | None, end: str | None, today: date) -> tuple[date, date]:
    end_year, end_month = _parse_month(end) if end else (today.year, today.month)
    if end is None:
        previous = today.replace(day=1) - timedelta(days=1)
        end_year, end_month = previous.year, previous.month
    if start:
        start_year, start_month = _parse_month(start)
    else:
        start_year, start_month = end_year - 2, end_month
    start_date = date(start_year, start_month, 1)
    end_date = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
    if start_date > end_date:
        raise ConfigError("--start 不能晚于 --end")
    return start_date, end_date


def compute_daily_window(report_date: date, days: int) -> tuple[date, date]:
    if days < 1:
        raise ConfigError("--days 必须 >= 1")
    return report_date - timedelta(days=days - 1), report_date


def _sources_from_outcomes(outcomes: list[Any]) -> list[Source]:
    sources: list[Source] = []
    for outcome in outcomes:
        if not outcome.ok:
            continue
        for result in outcome.results:
            if result.url:
                sources.append(
                    Source(
                        title=result.title,
                        url=result.url,
                        site=result.site,
                        snippet=result.snippet or result.summary,
                        published_at=result.published_at,
                    )
                )
    return dedupe_sources(sources)


def _query_log(outcomes: list[Any]) -> list[dict[str, object]]:
    return [
        {
            "query": outcome.query,
            "category": outcome.category,
            "results": len(outcome.results),
            "status": "ok" if outcome.ok else f"失败: {outcome.error or '无结果'}",
        }
        for outcome in outcomes
    ]


def _select_for_analysis(sources: list[Source], max_sources: int) -> list[Source]:
    ordered = sorted(
        sources,
        key=lambda s: (s.published_at or date.min, s.authority),
        reverse=True,
    )
    return assign_sids(ordered[:max_sources])


async def _search(queries: list[Query], settings: Settings) -> list[Any]:
    async with BochaSearchClient(settings) as searcher:
        return await searcher.search_many(queries, concurrency=3)


async def generate_review(
    focus: str,
    start: str | None,
    end: str | None,
    *,
    offline: bool = False,
    out_dir: Path = Path("reports"),
    env_file: str | None = None,
    generated_at: date | None = None,
    max_sources: int | None = None,
) -> RunResult:
    today = generated_at or date.today()
    period_start, period_end = compute_review_window(start, end, today)

    if offline:
        report = build_offline_review(focus, period_start, period_end, today)
        stats = compute_stats(report.tenders)
        return write_review(report, stats, top_by_category(report.tenders), out_dir)

    settings = load_settings(env_file)
    if not settings.bocha_api_key or not settings.llm_api_key:
        raise ConfigError("BOCHA_API_KEY / LLM_API_KEY 未配置；可先用 `--offline` 跑样例。")

    queries = build_review_queries(period_start.year, period_end.year)
    outcomes = await _search(queries, settings)
    sources = _select_for_analysis(_sources_from_outcomes(outcomes), max_sources or settings.max_sources)
    if not sources:
        raise RuntimeError("没有检索到可用来源")

    async with Fetcher(settings) as fetcher:
        await fetcher.fetch_many(sources)

    async with LLMClient(settings) as llm:
        tenders = await extract_tenders(llm, sources, focus, settings.llm_concurrency)
        tenders = dedupe_tenders(
            [t for t in tenders if not t.publish_date or period_start <= t.publish_date <= period_end]
        )
        if not tenders:
            raise RuntimeError("没有抽取到报告期内项目")
        stats = compute_stats(tenders)
        insights = await write_review_insights(llm, tenders, stats, focus)

    report = ReviewReport(
        focus=focus,
        period_start=period_start,
        period_end=period_end,
        generated_at=today,
        tenders=tenders,
        sources=sources,
        insights=insights,
        query_log=_query_log(outcomes),
        offline=False,
    )
    if len(tenders) < 10:
        report.gaps.append(f"本次仅抽取到 {len(tenders)} 条项目，样本偏小，结论需谨慎。")
    return write_review(report, stats, top_by_category(tenders), out_dir)


async def generate_daily(
    report_date: date,
    days: int,
    *,
    offline: bool = False,
    out_dir: Path = Path("reports"),
    ledger_path: Path | None = None,
    env_file: str | None = None,
    max_sources: int | None = None,
) -> RunResult:
    window_start, window_end = compute_daily_window(report_date, days)
    ledger_path = ledger_path or out_dir / "ESG招标跟踪台账.md"

    if offline:
        report = build_offline_daily(report_date, window_start, window_end, ledger_path)
        if not ledger_path.is_file():
            seed = Path(__file__).resolve().parent.parent / "fixtures" / "ledger_seed.md"
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            ledger_path.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")
        existing = load_ledger(ledger_path)
        merged, added, updated = merge_ledger(existing, report.tenders, report_date)
        save_ledger(ledger_path, merged)
        used_ids = {t.source_id for t in report.tenders + report.reference_tenders}
        sources = [s for s in report_sources(report) if s.sid in used_ids]
        return write_daily(
            report,
            added=added,
            updated=updated,
            ledger_count=len(merged),
            sources=sources,
            out_dir=out_dir,
        )

    settings = load_settings(env_file)
    if not settings.bocha_api_key or not settings.llm_api_key:
        raise ConfigError("BOCHA_API_KEY / LLM_API_KEY 未配置；可先用 `--offline` 跑样例。")

    queries = build_daily_queries(report_date, days)
    outcomes = await _search(queries, settings)
    sources = _select_for_analysis(_sources_from_outcomes(outcomes), max_sources or settings.max_sources)
    if not sources:
        raise RuntimeError("没有检索到可用来源")

    async with Fetcher(settings) as fetcher:
        await fetcher.fetch_many(sources)

    async with LLMClient(settings) as llm:
        tenders = await extract_tenders(llm, sources, "ESG/双碳招标", settings.llm_concurrency)

    new_tenders: list[Tender] = []
    reference: list[Tender] = []
    for tender in tenders:
        tender.priority = priority(tender, report_date)
        if tender.publish_date is None or window_start <= tender.publish_date <= window_end:
            new_tenders.append(tender)
        elif tender.status in {TenderStatus.awarded, TenderStatus.candidate}:
            reference.append(tender)
    reference = reference[:3]

    existing = load_ledger(ledger_path)
    merged, added, updated = merge_ledger(existing, new_tenders, report_date)
    save_ledger(ledger_path, merged)

    async with LLMClient(settings) as llm:
        insights = await write_daily_insights(llm, new_tenders)

    report = DailyReport(
        report_date=report_date,
        window_start=window_start,
        window_end=window_end,
        tenders=new_tenders,
        reference_tenders=reference,
        insights=insights,
        ledger_path=str(ledger_path),
        query_log=_query_log(outcomes),
        offline=False,
    )
    used_ids = {t.source_id for t in new_tenders + reference}
    used_sources = [s for s in sources if s.sid in used_ids]
    return write_daily(
        report,
        added=added,
        updated=updated,
        ledger_count=len(merged),
        sources=used_sources,
        out_dir=out_dir,
    )


def report_sources(report: DailyReport) -> list[Source]:
    """离线日报的 sources 从 fixture 读取；放在函数里避免循环 import。"""
    from .offline import _sources  # noqa: PLC0415

    return _sources("daily_sources.json")
