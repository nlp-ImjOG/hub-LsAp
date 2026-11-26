"""配置：从 .env / 环境变量读取，未设置时用默认值。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 反爬站点：直接不抓，降级用搜索摘要。
DEFAULT_BLOCKED_DOMAINS: tuple[str, ...] = (
    "mp.weixin.qq.com",
    "zhihu.com",
    "xiaohongshu.com",
    "weibo.com",
    "douban.com",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 博查搜索
    bocha_api_key: str = ""
    bocha_base_url: str = "https://api.bocha.cn/v1/web-search"
    bocha_timeout_s: float = 20.0
    bocha_max_retries: int = 3
    bocha_min_interval_s: float = 1.0
    search_count: int = 10

    # LLM（OpenAI 兼容）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout_s: float = 120.0
    llm_temperature: float = 0.2
    llm_max_tokens: int = 8192
    llm_concurrency: int = 3

    # 抓取
    fetch_enabled: bool = True
    fetch_timeout_s: float = 12.0
    fetch_max_bytes: int = 2 * 1024 * 1024
    fetch_concurrency: int = 5
    max_content_chars: int = 6000
    blocked_domains: tuple[str, ...] = DEFAULT_BLOCKED_DOMAINS

    # 报告
    max_sources: int = 15

    def masked(self) -> dict[str, object]:
        def mask(value: str) -> str:
            if not value:
                return "(未设置)"
            return f"{value[:6]}…{value[-4:]}" if len(value) > 12 else "(已设置)"

        return {
            "bocha": {"base_url": self.bocha_base_url, "api_key": mask(self.bocha_api_key)},
            "llm": {
                "base_url": self.llm_base_url,
                "model": self.llm_model,
                "api_key": mask(self.llm_api_key),
            },
            "search_count": self.search_count,
            "max_sources": self.max_sources,
            "fetch_enabled": self.fetch_enabled,
        }


def load_settings(env_file: str | None = None) -> Settings:
    """加载配置；默认依次查找当前目录、skill 根目录的 .env。"""
    if env_file:
        path = Path(env_file)
        if path.is_file():
            return Settings(_env_file=str(path))
        return Settings()

    # scripts/esg_report/config.py -> esg_report -> scripts -> skill 根目录
    script_root = Path(__file__).resolve().parents[1]
    skill_root = Path(__file__).resolve().parents[2]
    for candidate in (Path(".env"), skill_root / ".env", script_root / ".env"):
        if candidate.is_file():
            return Settings(_env_file=str(candidate))
    return Settings()
