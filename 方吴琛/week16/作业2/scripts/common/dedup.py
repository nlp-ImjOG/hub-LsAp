"""去重与域名白名单过滤。纯确定性算法。"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .search import SearchResult

# A 级/B 级域名白名单(与作业1 reference/sources.md 对齐)
A_DOMAINS = {
    "gov.cn", "csrc.gov.cn", "mee.gov.cn", "ndrc.gov.cn", "miit.gov.cn",
    "pbc.gov.cn", "nfra.gov.cn",
    "sse.com.cn", "szse.cn", "bse.cn", "hkex.com.hk", "hkexnews.hk",
    "cninfo.com.cn",
    "ifrs.org", "globalreporting.org", "sasb.org", "fsb-tcfd.org",
    "tnfd.global", "msci.com", "sustainalytics.com", "ftserussell.com", "unpri.org",
}
B_DOMAINS = {
    "caixin.com", "yicai.com", "stcn.com", "cnstock.com", "21jingji.com",
    "reuters.com", "bloomberg.com", "cls.cn", "jiemian.com",
}


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        # 取后两段作为根域(简化,不处理 .com.cn 之外的复杂后缀)
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    except Exception:
        return ""


def credibility(url: str) -> str:
    d = domain_of(url)
    if any(d == a or d.endswith("." + a) for a in A_DOMAINS):
        return "A"
    if any(d == b or d.endswith("." + b) for b in B_DOMAINS):
        return "B"
    return "C"


def normalize_title(t: str) -> str:
    return re.sub(r"\s+|[-_—–:：【】\[\]()]", "", t).lower()


def dedup(results: list[SearchResult]) -> list[SearchResult]:
    """按 标题归一化 + url 去重;同标题保留 A>B>C、url 更长者。"""
    seen_title: dict[str, SearchResult] = {}
    seen_url: set[str] = set()
    for r in results:
        if not r.url or r.url in seen_url:
            continue
        key = normalize_title(r.title)
        if not key:
            continue
        prev = seen_title.get(key)
        cred_new = credibility(r.url)
        if prev is None:
            seen_title[key] = r
            seen_url.add(r.url)
        else:
            order = {"A": 0, "B": 1, "C": 2}
            if order[cred_new] < order[credibility(prev.url)]:
                seen_url.discard(prev.url)
                seen_title[key] = r
                seen_url.add(r.url)
    return list(seen_title.values())
