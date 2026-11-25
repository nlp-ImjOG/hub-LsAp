"""统一搜索接口:默认 ddgs(DuckDuckGo,免费免 key),可选 Tavily。

确定性体现:同 query → 同结果(可缓存),结构化字段(title/url/snippet),
便于下游脚本消费,而非把原始 HTML 丢给 LLM 自由发挥。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .config import CONFIG


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = ""  # 后端标识

    def to_dict(self) -> dict:
        return asdict(self)


def _cache_path(query: str) -> Path:
    Path(CONFIG.cache_dir).mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(query.encode("utf-8")).hexdigest()
    return Path(CONFIG.cache_dir) / f"search_{h}.json"


def _search_ddgs(query: str, max_results: int) -> list[SearchResult]:
    from ddgs import DDGS  # 延迟导入

    out: list[SearchResult] = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            out.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href") or r.get("url") or "",
                    snippet=r.get("body") or r.get("snippet") or "",
                    source="ddgs",
                )
            )
    return out


def _search_tavily(query: str, max_results: int) -> list[SearchResult]:
    import requests

    key = CONFIG.tavily_api_key
    if not key:
        raise RuntimeError("TAVILY_API_KEY 未设置")
    resp = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": key, "query": query, "max_results": max_results, "search_depth": "advanced"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("content", ""),
            source="tavily",
        )
        for item in data.get("results", [])
    ]


def search(query: str, max_results: int | None = None, use_cache: bool = True) -> list[SearchResult]:
    """单次检索。默认带磁盘缓存,保证可重复。"""
    n = max_results or CONFIG.search_max_per_query
    if use_cache:
        p = _cache_path(query)
        if p.exists():
            return [SearchResult(**d) for d in json.loads(p.read_text("utf-8"))]

    backend = CONFIG.search_backend
    if backend == "tavily":
        results = _search_tavily(query, n)
    else:
        results = _search_ddgs(query, n)

    if use_cache:
        _cache_path(query).write_text(
            json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2), "utf-8"
        )
    return results


def search_many(queries: Iterable[str], max_results: int | None = None) -> dict[str, list[SearchResult]]:
    """批量检索,返回 {query: [results]}。"""
    return {q: search(q, max_results) for q in queries}
