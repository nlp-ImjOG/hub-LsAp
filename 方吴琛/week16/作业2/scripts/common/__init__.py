"""common 包:配置/搜索/抓取/总结/去重。"""
from .config import CONFIG
from .search import SearchResult, search, search_many
from .fetcher import fetch_text
from .summarizer import summarize_text, llm_complete, llm_json
from .dedup import dedup, credibility, domain_of

__all__ = [
    "CONFIG", "SearchResult", "search", "search_many",
    "fetch_text", "summarize_text", "llm_complete", "llm_json",
    "dedup", "credibility", "domain_of",
]
