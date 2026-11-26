"""网页抓取 + 正文抽取（去脚本/样式/导航，压缩空白）。"""
from __future__ import annotations

import re

import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def fetch_html(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def extract_text(html: str, max_chars: int = 6000) -> str:
    """从 HTML 抽取正文：优先 BeautifulSoup，退化为正则。"""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
    except Exception:  # noqa: BLE001
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)

    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t　]+", " ", text)
    return text[:max_chars]


def fetch(url: str, max_chars: int = 6000) -> str:
    """抓取并返回纯文本正文。"""
    return extract_text(fetch_html(url), max_chars)
