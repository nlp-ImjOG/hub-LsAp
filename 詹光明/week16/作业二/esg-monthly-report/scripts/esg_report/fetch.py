"""网页抓取：抓不到就降级到搜索摘要，绝不中断整条流水线。"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from .config import Settings
from .models import Source
from .search import parse_date

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    candidates = soup.select(
        "article, main, [role=main], .content, .article, .post, .detail, #content, #article"
    )
    if not candidates:
        candidates = [soup.body or soup]
    best = max(candidates, key=lambda node: len(node.get_text(" ", strip=True)))
    text = best.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def extract_published_date(html: str) -> date | None:
    soup = BeautifulSoup(html, "html.parser")
    for selector in (
        'meta[property="article:published_time"]',
        'meta[name="article:published_time"]',
        'meta[name="publishdate"]',
        'meta[name="pubdate"]',
        'meta[itemprop="datePublished"]',
    ):
        node = soup.select_one(selector)
        if node and node.get("content"):
            parsed = parse_date(str(node["content"]))
            if parsed:
                return parsed
    time_node = soup.select_one("time[datetime]")
    if time_node and time_node.get("datetime"):
        parsed = parse_date(str(time_node["datetime"]))
        if parsed:
            return parsed
    # 只在“发布/日期/时间”附近找日期，避免把版权年份、正文里的历史日期误当成发布日期。
    match = re.search(
        r"(?:发布|日期|时间|published|date)[^\d]{0,20}(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})",
        html[:20000],
        re.IGNORECASE,
    )
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def _is_blocked(url: str, blocked: tuple[str, ...]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in blocked)


class Fetcher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.fetch_concurrency)
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=self._settings.fetch_timeout_s,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_one(self, source: Source) -> Source:
        if not self._settings.fetch_enabled:
            source.fetch_status = "snippet"
            return source
        if not source.url.startswith(("http://", "https://")):
            source.fetch_status = "snippet"
            return source
        if _is_blocked(source.url, self._settings.blocked_domains):
            source.fetch_status = "blocked"
            return source

        try:
            async with self._semaphore:
                response = await (await self._http()).get(source.url)
            if response.status_code != 200:
                source.fetch_status = "error"
                return source
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not any(t in content_type for t in _HTML_TYPES):
                source.fetch_status = "snippet"
                return source
            text = extract_text(response.text)
            if len(text) < 80:
                source.fetch_status = "snippet"
                return source
            source.content = text[: self._settings.max_content_chars]
            source.fetch_status = "page"
            if source.published_at is None:
                source.published_at = extract_published_date(response.text)
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            logger.debug("抓取失败 %s: %s", source.url, exc)
            source.fetch_status = "error"
        except Exception as exc:  # noqa: BLE001 - 抓取不应中断研究
            logger.debug("抓取未预期错误 %s: %s", source.url, exc)
            source.fetch_status = "error"
        return source

    async def fetch_many(self, sources: list[Source]) -> list[Source]:
        if not sources:
            return sources
        await asyncio.gather(*(self.fetch_one(source) for source in sources))
        return sources

    async def __aenter__(self) -> Fetcher:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
