"""检索词：历史复盘 + 每日监控。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Query:
    text: str
    category: str = ""
    lang: str = "zh"


def month_label(day: date) -> str:
    return f"{day.year}年{day.month}月"


def build_review_queries(start_year: int, end_year: int) -> list[Query]:
    """近 N 年复盘：按年度 × 主题组合，覆盖中标/成交/候选人。"""
    core = [
        ("ESG 中标", "ESG报告/信息披露"),
        ("ESG报告 中标", "ESG报告/信息披露"),
        ("ESG咨询 中标", "ESG咨询/管理提升/评级"),
        ("碳核算 中标", "碳盘查/碳核算/碳足迹"),
        ("碳足迹 中标", "碳盘查/碳核算/碳足迹"),
        ("零碳园区 中标", "双碳规划/零碳园区/碳预算"),
        ("碳管理平台 中标", "碳管理/ESG数字化平台"),
        ("可持续发展报告 成交", "ESG报告/信息披露"),
    ]
    queries: list[Query] = []
    for year in range(start_year, end_year + 1):
        for text, category in core:
            queries.append(Query(f"{text} {year}", category))
    queries.extend(
        [
            Query("site:ccgp.gov.cn ESG 中标公告", "ESG报告/信息披露"),
            Query("site:chnenergybidding.com.cn ESG 中标", "ESG咨询/管理提升/评级"),
            Query("site:bidding.csg.cn ESG 中标", "ESG咨询/管理提升/评级"),
            Query("ESG 候选人公示 碳", "碳盘查/碳核算/碳足迹"),
        ]
    )
    return _dedup(queries)


def build_daily_queries(day: date, days: int = 1) -> list[Query]:
    """日报：最近 N 天的新招标/采购/候选人。"""
    label = month_label(day)
    queries = [
        Query(f"ESG 招标 {label}", "ESG报告/信息披露"),
        Query(f"ESG 采购 {label}", "ESG咨询/管理提升/评级"),
        Query(f"可持续发展报告 采购 {label}", "ESG报告/信息披露"),
        Query(f"碳足迹 招标 {label}", "碳盘查/碳核算/碳足迹"),
        Query(f"碳核算 招标 {label}", "碳盘查/碳核算/碳足迹"),
        Query(f"零碳园区 招标 {label}", "双碳规划/零碳园区/碳预算"),
        Query(f"碳管理平台 招标 {label}", "碳管理/ESG数字化平台"),
        Query(f"能碳平台 采购 {label}", "碳管理/ESG数字化平台"),
        Query("site:ccgp.gov.cn ESG 招标", "ESG报告/信息披露"),
        Query("site:chnenergybidding.com.cn ESG 采购", "ESG咨询/管理提升/评级"),
        Query("site:bidding.csg.cn 碳 招标", "碳盘查/碳核算/碳足迹"),
    ]
    return _dedup(queries)


def _dedup(queries: list[Query]) -> list[Query]:
    seen: set[str] = set()
    unique: list[Query] = []
    for query in queries:
        key = query.text.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(query)
    return unique
