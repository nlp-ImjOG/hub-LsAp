"""配置:通过环境变量读取,所有脚本共用。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # --- 搜索后端 ---
    search_backend: str = field(default_factory=lambda: os.getenv("ESG_SEARCH_BACKEND", "ddgs"))
    # ddgs(DuckDuckGo)免费免 key;可选 tavily
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    search_max_per_query: int = field(default_factory=lambda: int(os.getenv("ESG_SEARCH_MAX", "8")))

    # --- 抓取 ---
    fetch_timeout: int = field(default_factory=lambda: int(os.getenv("ESG_FETCH_TIMEOUT", "20")))
    fetch_max_chars: int = field(default_factory=lambda: int(os.getenv("ESG_FETCH_MAX_CHARS", "6000")))

    # --- LLM 总结(可选;无 key 时降级为本地抽取式摘要)---
    llm_base_url: str = field(default_factory=lambda: os.getenv("ESG_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"))
    llm_api_key: str = field(default_factory=lambda: os.getenv("ESG_LLM_API_KEY", os.getenv("ZHIPUAI_API_KEY", "")))
    llm_model: str = field(default_factory=lambda: os.getenv("ESG_LLM_MODEL", "glm-4-flash"))

    # --- 缓存 ---
    cache_dir: str = field(default_factory=lambda: os.getenv("ESG_CACHE_DIR", ".esg_cache"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


CONFIG = Config()
