"""博查 Web Search 客户端：多路径解析、限流、重试、单条失败不中断。"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from datetime import date, datetime
from typing import Any

import httpx

from .config import Settings
from .models import Category, RawResult, SearchOutcome
from .queries import Query

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_VALUE_PATHS: tuple[tuple[str, ...], ...] = (
    ("data", "webPages", "value"),
    ("data", "webPages", "values"),
    ("data", "value"),
    ("data", "results"),
    ("data", "pages"),
    ("data", "items"),
    ("webPages", "value"),
    ("value",),
    ("results",),
)

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("name", "title", "headline"),
    "url": ("url", "link", "href"),
    "snippet": ("snippet", "description", "desc"),
    "summary": ("summary", "longDescription", "long_description"),
    "site": ("siteName", "site_name", "site", "source"),
    "published_at": ("datePublished", "date_published", "publishedAt", "pubDate"),
}

_TAG_RE = re.compile(r"<[^>]+>")
_RETRYABLE = {429, 500, 502, 503, 504}


def strip_html(text: str) -> str:
    if not text:
        return ""
    return _TAG_RE.sub("", text).replace("&nbsp;", " ").replace("&amp;", "&").strip()


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _field(item: dict[str, Any], name: str) -> Any:
    return _first(item, *_FIELD_ALIASES[name])


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    for path in _VALUE_PATHS:
        node: Any = payload
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, list):
            return [x for x in node if isinstance(x, dict)]
    return []


def parse_search_response(payload: dict[str, Any]) -> list[RawResult]:
    results: list[RawResult] = []
    for item in _extract_items(payload):
        url = str(_field(item, "url") or "").strip()
        title = strip_html(str(_field(item, "title") or ""))
        if not url and not title:
            continue
        results.append(
            RawResult(
                title=title,
                url=url,
                snippet=strip_html(str(_field(item, "snippet") or ""))[:500],
                summary=strip_html(str(_field(item, "summary") or "")),
                site=strip_html(str(_field(item, "site") or "")),
                published_at=parse_date(_field(item, "published_at")),
            )
        )
    return results


class _RateLimiter:
    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class BochaSearchClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._limiter = _RateLimiter(settings.bocha_min_interval_s)
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._settings.bocha_timeout_s,
                headers={
                    "Authorization": f"Bearer {self._settings.bocha_api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": _USER_AGENT,
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search(self, query: Query) -> SearchOutcome:
        if not self._settings.bocha_api_key:
            return SearchOutcome(
                query=query.text,
                category=query.category,
                ok=False,
                error="BOCHA_API_KEY 未配置",
            )

        body = {
            "query": query.text,
            "summary": True,
            "count": self._settings.search_count,
            "freshness": "noLimit",
        }
        last_error = ""
        for attempt in range(1, self._settings.bocha_max_retries + 1):
            await self._limiter.acquire()
            started = time.monotonic()
            try:
                response = await (await self._http()).post(self._settings.bocha_base_url, json=body)
            except httpx.TimeoutException:
                last_error = "请求超时"
            except httpx.HTTPError as exc:
                last_error = f"网络错误: {exc.__class__.__name__}: {exc}"
            else:
                latency = int((time.monotonic() - started) * 1000)
                if response.status_code in _RETRYABLE and attempt < self._settings.bocha_max_retries:
                    last_error = f"HTTP {response.status_code}"
                    await asyncio.sleep((2 ** (attempt - 1)) + random.random())
                    continue
                if response.status_code != 200:
                    return SearchOutcome(
                        query=query.text,
                        category=query.category,
                        ok=False,
                        error=f"HTTP {response.status_code}",
                        latency_ms=latency,
                    )
                try:
                    payload = response.json()
                except ValueError:
                    return SearchOutcome(
                        query=query.text,
                        category=query.category,
                        ok=False,
                        error="响应不是 JSON",
                        latency_ms=latency,
                    )
                results = parse_search_response(payload)
                return SearchOutcome(
                    query=query.text,
                    category=query.category,
                    ok=bool(results),
                    results=results,
                    error=None if results else "未解析到结果",
                    latency_ms=latency,
                    top_level_keys=list(payload.keys()) if isinstance(payload, dict) else [],
                )

            logger.warning("检索失败（第 %d 次）: %s | %s", attempt, query.text, last_error)
            if attempt < self._settings.bocha_max_retries:
                await asyncio.sleep((2 ** (attempt - 1)) + random.random())

        return SearchOutcome(
            query=query.text,
            category=query.category,
            ok=False,
            error=last_error,
        )

    async def search_many(self, queries: list[Query], concurrency: int = 3) -> list[SearchOutcome]:
        semaphore = asyncio.Semaphore(concurrency)

        async def run(query: Query) -> SearchOutcome:
            async with semaphore:
                return await self.search(query)

        try:
            return await asyncio.gather(*(run(q) for q in queries))
        finally:
            await self.aclose()

    async def __aenter__(self) -> BochaSearchClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


def flatten_outcomes(outcomes: list[SearchOutcome]) -> list[RawResult]:
    """把多轮检索结果摊平，保留来源信息由上层补充。"""
    flat: list[RawResult] = []
    for outcome in outcomes:
        if outcome.ok:
            flat.extend(outcome.results)
    return flat


def category_of_outcome(outcomes: list[SearchOutcome], url: str) -> Category:
    """按命中该 URL 的第一个查询类别给来源归类。"""
    for outcome in outcomes:
        if any(result.url == url for result in outcome.results):
            return outcome.category
    return Category.industry
