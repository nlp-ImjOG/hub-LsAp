"""真实联网搜索与正文抓取：Bing / DuckDuckGo 双引擎自动降级，无内置假数据。"""

from __future__ import annotations

import re
import sys
import urllib.parse
from typing import Any

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}
TIMEOUT = 20


def _get(url: str, params: dict[str, Any] | None = None) -> requests.Response:
    resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


BING_FRESHNESS = {"day": "ez1", "week": "ez2", "month": "ez3", "year": "ez4"}
DDG_FRESHNESS = {"day": "d", "week": "w", "month": "m", "year": "y"}


def search_bing(query: str, limit: int = 8, freshness: str | None = None) -> list[dict[str, str]]:
    params = {"q": query, "count": str(limit), "setlang": "zh-cn"}
    if freshness in BING_FRESHNESS:
        params["filters"] = f'ex1:"{BING_FRESHNESS[freshness]}"'
    resp = _get("https://cn.bing.com/search", params)
    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict[str, str]] = []
    for li in soup.select("li.b_algo"):
        link = li.select_one("h2 a")
        if not link or not link.get("href"):
            continue
        caption = li.select_one(".b_caption p") or li.select_one(".b_algoSlug")
        results.append(
            {
                "title": link.get_text(" ", strip=True),
                "url": link["href"],
                "snippet": caption.get_text(" ", strip=True) if caption else "",
                "engine": "bing",
            }
        )
        if len(results) >= limit:
            break
    return results


def _unwrap_ddg(href: str) -> str:
    if href.startswith("//duckduckgo.com/l/"):
        query = urllib.parse.urlparse("https:" + href).query
        target = urllib.parse.parse_qs(query).get("uddg")
        if target:
            return urllib.parse.unquote(target[0])
    return href


def search_360(query: str, limit: int = 8, freshness: str | None = None) -> list[dict[str, str]]:
    """360 搜索（中文结果质量最好，优先使用）。无需 API Key。"""
    resp = _get("https://www.so.com/s", {"q": query, "src": "srp"})
    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select("h3 a[data-mdurl]"):
        url = (anchor.get("data-mdurl") or "").strip()
        title = anchor.get_text(" ", strip=True)
        if not url or not title or url in seen:
            continue
        seen.add(url)
        container = anchor.find_parent("li") or anchor.find_parent("div")
        snippet = ""
        if container:
            desc = container.select_one(".res-desc, .res-rich, .res-comm-con")
            snippet = (desc or container).get_text(" ", strip=True)
            snippet = snippet.replace(title, "").strip()[:400]
        results.append({"title": title, "url": url, "snippet": snippet, "engine": "360"})
        if len(results) >= limit:
            break
    return results


def search_ddg(query: str, limit: int = 8, freshness: str | None = None) -> list[dict[str, str]]:
    params = {"q": query}
    if freshness in DDG_FRESHNESS:
        params["df"] = DDG_FRESHNESS[freshness]
    resp = _get("https://html.duckduckgo.com/html/", params)
    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict[str, str]] = []
    for node in soup.select("div.result"):
        link = node.select_one("a.result__a")
        if not link or not link.get("href"):
            continue
        snippet = node.select_one(".result__snippet")
        results.append(
            {
                "title": link.get_text(" ", strip=True),
                "url": _unwrap_ddg(link["href"]),
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                "engine": "duckduckgo",
            }
        )
        if len(results) >= limit:
            break
    return results


def search(
    query: str, limit: int = 8, backend: str = "auto", freshness: str | None = None
) -> list[dict[str, str]]:
    """按 backend 检索；auto 时 360 → Bing → DuckDuckGo 依次降级。"""
    order = ["360", "bing", "duckduckgo"] if backend == "auto" else [backend]
    matchers = {
        "360": search_360,
        "bing": search_bing,
        "duckduckgo": search_ddg,
    }
    for engine in order:
        try:
            matcher = matchers[engine]
            results = matcher(query, limit, freshness)
            if results:
                return results
            print(f"[warn] {engine} 无结果：{query}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - 引擎失败时降级
            print(f"[warn] {engine} 失败（{exc}）：{query}", file=sys.stderr)
    return []


def fetch_text(url: str, limit: int = 5000) -> str:
    """抓取页面并提取纯文本；失败返回空串，由调用方降级为搜索摘要。"""
    try:
        resp = _get(url)
        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return ""
        resp.encoding = resp.apparent_encoding or resp.encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        return text[:limit]
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 正文抓取失败（{exc}）：{url}", file=sys.stderr)
        return ""
