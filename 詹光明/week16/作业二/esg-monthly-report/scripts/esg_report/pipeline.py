"""主流水线：窗口 → 检索 → 去重/筛选 → 抓取 → LLM 抽取 → 组装 → 校验 → 落盘。"""

from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import Settings, load_settings
from .fetch import Fetcher
from .filter import select_sources
from .llm import LLMClient, analyze_sources, write_executive
from .models import DateStatus, ReportData, RunResult, Source
from .offline import build_offline_report
from .queries import INDUSTRY_TERMS, PEERS, Query, build_queries
from .report import build_and_write
from .search import BochaSearchClient

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    pass


def compute_window(month: str | None, today: date) -> tuple[date, date]:
    """month 形如 2026-10；为空时取 today 的上一个自然月。"""
    if month:
        try:
            year, mon = (int(part) for part in month.split("-", 1))
            start = date(year, mon, 1)
        except (ValueError, TypeError) as exc:
            raise ConfigError(f"--month 格式应为 YYYY-MM，收到 {month!r}") from exc
    else:
        first_of_this_month = today.replace(day=1)
        previous = first_of_this_month - timedelta(days=1)
        start = date(previous.year, previous.month, 1)
        year, mon = start.year, start.month
    end = date(year, mon, calendar.monthrange(year, mon)[1])
    return start, end


def _terms(industry: str) -> list[str]:
    return INDUSTRY_TERMS.get(industry, [industry, "ESG", "碳中和", "绿色转型"])


def _peers(industry: str) -> list[str]:
    return PEERS.get(industry, ["行业龙头"])


def _sources_from_outcomes(outcomes: list[Any]) -> list[Source]:
    sources: list[Source] = []
    for outcome in outcomes:
        if not outcome.ok:
            continue
        for result in outcome.results:
            if not result.url:
                continue
            sources.append(
                Source(
                    title=result.title,
                    url=result.url,
                    site=result.site,
                    published_at=result.published_at,
                    snippet=result.snippet or result.summary,
                    category=outcome.category,
                )
            )
    return sources


def _query_log(outcomes: list[Any]) -> list[dict[str, object]]:
    return [
        {
            "query": outcome.query,
            "category": outcome.category.value,
            "results": len(outcome.results),
            "status": "ok" if outcome.ok else f"失败: {outcome.error or '无结果'}",
        }
        for outcome in outcomes
    ]


async def generate(
    client: str,
    industry: str,
    month: str | None,
    *,
    offline: bool = False,
    out_dir: Path = Path("reports"),
    env_file: str | None = None,
    generated_at: date | None = None,
    max_sources: int | None = None,
) -> RunResult:
    today = generated_at or date.today()
    start, end = compute_window(month, today)

    if offline:
        report = build_offline_report(client, industry, start, end, today)
        return build_and_write(report, out_dir, run_meta={"mode": "offline"})

    settings: Settings = load_settings(env_file)
    if not settings.bocha_api_key:
        raise ConfigError("BOCHA_API_KEY 未配置；可先用 `--offline` 跑样例。")
    if not settings.llm_api_key:
        raise ConfigError("LLM_API_KEY 未配置；可先用 `--offline` 跑样例。")

    queries = build_queries(client, industry, start.year, start.month)
    logger.info("检索词 %d 条，窗口 %s ~ %s", len(queries), start, end)

    async with BochaSearchClient(settings) as searcher:
        outcomes = await searcher.search_many(queries, concurrency=3)

    raw_sources = _sources_from_outcomes(outcomes)
    logger.info("检索结果 %d 条（去重前）", len(raw_sources))

    selected, selected_after, background = select_sources(
        raw_sources,
        client=client,
        industry=industry,
        peers=_peers(industry),
        terms=_terms(industry),
        start=start,
        end=end,
        generated_at=today,
        max_sources=max_sources or settings.max_sources,
    )
    logger.info("选中来源 %d 条（报告期后 %d 条）", len(selected), len(selected_after))
    if not selected:
        raise RuntimeError("没有选中任何来源，请检查检索词或 API 配额")

    async with Fetcher(settings) as fetcher:
        await fetcher.fetch_many(selected + selected_after)

    # 抓取后可能补到发布日期：重新判定窗口，剔除被证实为旧闻的来源，并重排 SID。
    for source in selected + selected_after:
        if source.published_at is None:
            continue
        if start <= source.published_at <= end:
            source.date_status = DateStatus.verified
        elif end < source.published_at <= today:
            source.date_status = DateStatus.after_window
        else:
            source.date_status = DateStatus.outside_window
    combined = [
        source for source in selected + selected_after if source.date_status != DateStatus.outside_window
    ]
    for index, source in enumerate(combined, start=1):
        source.sid = f"S{index}"
    selected = [source for source in combined if source.date_status != DateStatus.after_window]
    selected_after = [source for source in combined if source.date_status == DateStatus.after_window]
    if not selected:
        raise RuntimeError("抓取后没有报告期内的来源，请检查日期解析或放宽窗口")

    async with LLMClient(settings) as llm:
        items = await analyze_sources(
            llm, selected + selected_after, client, industry, settings.llm_concurrency
        )
        executive = await write_executive(llm, items, client, industry)

    gaps: list[str] = []
    if background:
        gaps.append(f"{len(background)} 条窗口外来源未纳入正文，避免把旧闻写成本月动态。")
    unverified = [s.sid for s in selected + selected_after if s.date_status.value == "unverified"]
    if unverified:
        gaps.append(f"以下来源无发布日期，已保留但需人工核实：{', '.join(unverified)}")

    report = ReportData(
        client=client,
        industry=industry,
        period_start=start,
        period_end=end,
        generated_at=today,
        summary=executive.summary,
        items=items,
        sources=selected + selected_after,
        executive=executive,
        gaps=gaps,
        query_log=_query_log(outcomes),
        offline=False,
    )
    return build_and_write(
        report,
        out_dir,
        run_meta={
            "mode": "live",
            "settings": settings.masked(),
            "raw_source_count": len(raw_sources),
            "background_count": len(background),
        },
    )


def preview_queries(client: str, industry: str, month: str | None, today: date | None = None) -> list[Query]:
    start, _ = compute_window(month, today or date.today())
    return build_queries(client, industry, start.year, start.month)
