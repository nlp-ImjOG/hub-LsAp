"""去重、时间窗口、分类、相关性打分与来源选择。"""

from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Category, DateStatus, Source

POLICY_WORDS = (
    "政策", "条例", "准则", "指引", "通知", "办法", "规划", "标准", "披露",
    "碳市场", "碳排放权", "CBAM", "ISSB", "MSCI", "评级", "监管",
)
ESG_WORDS = ("ESG", "可持续", "双碳", "碳达峰", "碳中和", "气候", "碳排放", "碳足迹", "绿色")
INDUSTRY_EXTRA = ("安全生产", "生态修复", "甲烷", "CCUS", "煤电", "水资源", "职业健康")

_KEEP_QUERY = {"id", "articleid", "guid", "p", "newsid", "contentid"}
_OFFICIAL_DOMAINS = (
    "gov.cn", "edu.cn", "ifrs.org", "mee.gov.cn", "ccgp.gov.cn", "sse.com.cn",
    "hkexnews.hk", "cninfo.com.cn", "chinaclear.cn",
)
_COMPANY_DOMAINS = ("shenhuachina.com", "chnenergy.com.cn", "csec.com", "cnenergy.com.cn")
_AGGREGATORS = (
    "jianyu360", "zhaobiao", "rccchina", "chinabidding", "qianlima", "bidcenter",
    "caizhaowang", "zgggzy", "lubanlebiao", "shuidi", "zhiliaobiaoxun",
)


def normalize_url(url: str) -> str:
    """去掉 www、fragment、跟踪参数，保留可能有意义的 id。"""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = parts.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parts.path) or "/"
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if k.lower() in _KEEP_QUERY]
    return urlunsplit((parts.scheme or "https", host, path, urlencode(kept), ""))


def title_key(title: str) -> str:
    return re.sub(r"[\W_]+", "", title.lower())


def is_duplicate_title(a: str, b: str) -> bool:
    if not a or not b or len(a) < 8 or len(b) < 8:
        return False
    return SequenceMatcher(None, title_key(a), title_key(b)).ratio() >= 0.92


def dedup_sources(sources: list[Source]) -> list[Source]:
    """按规范化 URL + 标题相似度去重，保留先出现的来源。"""
    kept: list[Source] = []
    seen_urls: dict[str, Source] = {}
    for source in sources:
        key = normalize_url(source.url) if source.url else ""
        if key and key in seen_urls:
            source.duplicate_of = seen_urls[key].sid or seen_urls[key].url
            continue
        duplicate = next(
            (existing for existing in kept if is_duplicate_title(source.title, existing.title)),
            None,
        )
        if duplicate is not None:
            source.duplicate_of = duplicate.sid or duplicate.url
            continue
        kept.append(source)
        if key:
            seen_urls[key] = source
    return kept


def classify_source(source: Source, client: str, peers: list[str]) -> Category:
    text = f"{source.title} {source.snippet}"
    if client and client in text:
        return Category.company
    if any(peer in text for peer in peers):
        return Category.benchmark
    if source.category == Category.policy or any(word in text for word in POLICY_WORDS):
        return Category.policy
    return Category.industry


def authority_score(source: Source) -> int:
    host = (urlsplit(source.url).hostname or "").lower()
    if any(host.endswith(domain) for domain in _OFFICIAL_DOMAINS):
        return 3
    if any(host.endswith(domain) for domain in _COMPANY_DOMAINS):
        return 3
    if any(token in host for token in _AGGREGATORS):
        return 1
    return 2


def relevance_score(source: Source, client: str, industry: str, terms: list[str]) -> int:
    text = f"{source.title} {source.snippet} {source.content[:500]}"
    score = 0
    if client and client in text:
        score += 3
    if industry and industry in text:
        score += 2
    score += sum(1 for term in terms if term and term in text)
    score += sum(1 for word in ESG_WORDS if word in text)
    score += sum(1 for word in INDUSTRY_EXTRA if word in text)
    if any(word in text for word in POLICY_WORDS):
        score += 1
    score += source.authority
    return min(score, 20)


def apply_window(
    sources: list[Source], start: date, end: date, generated_at: date
) -> tuple[list[Source], list[Source], list[Source]]:
    """按发布日期分成：报告期内 / 报告期后 / 窗口外。"""
    in_window: list[Source] = []
    after_window: list[Source] = []
    background: list[Source] = []
    for source in sources:
        published = source.published_at
        if published is None:
            source.date_status = DateStatus.unverified
            in_window.append(source)
        elif start <= published <= end:
            source.date_status = DateStatus.verified
            in_window.append(source)
        elif end < published <= generated_at:
            source.date_status = DateStatus.after_window
            after_window.append(source)
        else:
            source.date_status = DateStatus.outside_window
            background.append(source)
    return in_window, after_window, background


def _sort_key(source: Source) -> tuple[int, int, int, date]:
    status_rank = 2 if source.date_status == DateStatus.verified else 1
    return (
        status_rank,
        source.relevance,
        source.authority,
        source.published_at or date.min,
    )


def select_sources(
    sources: list[Source],
    *,
    client: str,
    industry: str,
    peers: list[str],
    terms: list[str],
    start: date,
    end: date,
    generated_at: date,
    max_sources: int = 15,
) -> tuple[list[Source], list[Source], list[Source]]:
    """去重、分类、打分，按配额选出报告期内来源，并返回报告期后来源。"""
    sources = dedup_sources(sources)
    for source in sources:
        source.category = classify_source(source, client, peers)
        source.authority = authority_score(source)
        source.relevance = relevance_score(source, client, industry, terms)

    in_window, after_window, background = apply_window(sources, start, end, generated_at)
    ordered = sorted(in_window, key=_sort_key, reverse=True)

    quotas = {
        Category.policy: 5,
        Category.industry: 5,
        Category.company: 5,
        Category.benchmark: 3,
    }
    selected: list[Source] = []
    seen: set[str] = set()

    def add(source: Source) -> None:
        if len(selected) >= max_sources:
            return
        key = normalize_url(source.url) if source.url else title_key(source.title)
        if key and key in seen:
            return
        seen.add(key)
        selected.append(source)

    for category, quota in quotas.items():
        for source in [s for s in ordered if s.category == category][:quota]:
            add(source)

    for source in ordered:
        add(source)
        if len(selected) >= max_sources:
            break

    selected_after = sorted(after_window, key=_sort_key, reverse=True)[:2]

    for index, source in enumerate(selected + selected_after, start=1):
        source.sid = f"S{index}"
    return selected, selected_after, background
