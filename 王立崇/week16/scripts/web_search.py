"""互联网搜索：多后端、带降级。

优先级：Serper（Google，需 SERPER_API_KEY）→ 博查（中文，需 BOCHA_API_KEY）
       → DuckDuckGo HTML → Bing HTML（两者无需 Key，免费网页抓取）。

返回统一结构 SearchResult，调用方无需关心具体后端。
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

import requests

try:
    from . import config
except ImportError:  # 直接 `python web_search.py` 运行时
    import config  # type: ignore

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    date: str = ""
    source: str = ""


# ---- 各后端实现 ------------------------------------------------------------

def _serper(query: str, num: int) -> list[SearchResult]:
    key = config.get_settings().serper_key
    if not key:
        return []
    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query, "num": num, "gl": "cn", "hl": "zh-cn"},
        timeout=20,
    )
    resp.raise_for_status()
    out: list[SearchResult] = []
    for it in resp.json().get("organic", []):
        out.append(
            SearchResult(
                title=it.get("title", ""),
                url=it.get("link", ""),
                snippet=it.get("snippet", ""),
                date=it.get("date", ""),
                source="serper",
            )
        )
    return out


def _bocha(query: str, num: int) -> list[SearchResult]:
    key = config.get_settings().bocha_key
    if not key:
        return []
    resp = requests.post(
        "https://api.bochaai.com/v1/web-search",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"query": query, "count": num, "summary": True},
        timeout=20,
    )
    resp.raise_for_status()
    pages = resp.json().get("data", {}).get("webPages", {}).get("value", [])
    out: list[SearchResult] = []
    for it in pages:
        out.append(
            SearchResult(
                title=it.get("name", ""),
                url=it.get("url", ""),
                snippet=it.get("snippet", ""),
                date=it.get("dateLastCrawled", ""),
                source="bocha",
            )
        )
    return out


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _ddg(query: str, num: int) -> list[SearchResult]:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    html = resp.text
    links = re.findall(
        r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>', html
    )
    snips = re.findall(
        r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL
    )
    out: list[SearchResult] = []
    for i, (href, title) in enumerate(links[:num]):
        snippet = _strip_tags(snips[i]).strip() if i < len(snips) else ""
        out.append(
            SearchResult(title=_strip_tags(title).strip(), url=href, snippet=snippet, source="duckduckgo")
        )
    return out


def _bing(query: str, num: int) -> list[SearchResult]:
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "count": num})
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    html = resp.text
    out: list[SearchResult] = []
    for href, title in re.findall(
        r'<li class="b_algo".*?<h2><a href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL
    ):
        out.append(SearchResult(title=_strip_tags(title).strip(), url=href, source="bing"))
    return out[:num]


# ---- 统一入口 --------------------------------------------------------------

_BACKENDS = (_serper, _bocha, _ddg, _bing)


def search(query: str, num: int = 10) -> list[SearchResult]:
    """依次尝试各后端，返回第一个非空结果集；全部失败返回空列表。"""
    for backend in _BACKENDS:
        try:
            results = backend(query, num)
        except Exception as exc:  # noqa: BLE001 —— 后端可用性差异大，逐层降级
            print(f"[search] 后端 {backend.__name__} 失败：{exc}")
            continue
        if results:
            print(f"[search] {backend.__name__} 命中 {len(results)} 条：{query}")
            return results
    print(f"[search] 无可用后端，返回空：{query}")
    return []
