"""网页抓取 + 正文抽取(trafilatura,本地免费)。

确定性体现:把"原始 HTML → 干净正文"这件噪声很大的事交给确定性库处理,
只把 ≤ N 字符的干净正文交给下游(LLM/抽取器),显著降低 token 消耗与幻觉。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import CONFIG


def _cache_path(url: str) -> Path:
    Path(CONFIG.cache_dir).mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(url.encode("utf-8")).hexdigest()
    return Path(CONFIG.cache_dir) / f"page_{h}.json"


def fetch_text(url: str, use_cache: bool = True) -> str:
    """抓取 url 并返回干净正文;失败返回空串。"""
    if use_cache:
        p = _cache_path(url)
        if p.exists():
            return json.loads(p.read_text("utf-8")).get("text", "")

    import trafilatura

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        ) or ""
    except Exception:
        return ""

    text = text[: CONFIG.fetch_max_chars]

    if use_cache:
        _cache_path(url).write_text(
            json.dumps({"url": url, "text": text}, ensure_ascii=False), "utf-8"
        )
    return text
