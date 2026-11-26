"""集中读取 LLM、搜索后端与推送配置（环境变量 / 可选 .env）。

- 不配置任何 Key 也能运行：调用方（各编排脚本）会自动进入离线 demo 模式。
- LLM 沿用 OpenAI 兼容协议，DeepSeek 只填 DEEPSEEK_API_KEY 即可自动补全地址与模型。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:  # python-dotenv 是可选项
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(*args, **kwargs):  # type: ignore[misc]
        return False

load_dotenv()

_DEFAULT_MODEL = "gpt-4o-mini"


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


@dataclass(frozen=True)
class Settings:
    # LLM
    api_key: str | None
    base_url: str | None
    model: str
    timeout: float
    # 搜索后端（二者配置其一即可，均不配则降级到 DDG / Bing 网页抓取）
    serper_key: str | None
    bocha_key: str | None
    # 推送（企业微信 / 钉钉机器人 webhook，二选一）
    wecom_webhook: str | None
    dingtalk_webhook: str | None

    @property
    def llm_enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def search_key_enabled(self) -> bool:
        return bool(self.serper_key or self.bocha_key)


def _load() -> Settings:
    deepseek_key = _first_env("DEEPSEEK_API_KEY")
    api_key = _first_env(
        "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "MOONSHOT_API_KEY"
    )
    base_url = _first_env("OPENAI_BASE_URL", "LLM_BASE_URL")
    model = _first_env("OPENAI_MODEL", "LLM_MODEL")

    # 只设置了 DEEPSEEK_API_KEY 时，自动补上 DeepSeek 默认地址与模型
    if base_url is None and deepseek_key and api_key == deepseek_key:
        base_url = "https://api.deepseek.com/v1"
        model = model or "deepseek-chat"

    try:
        timeout = float(_first_env("LLM_TIMEOUT") or "60")
    except ValueError:
        timeout = 60.0

    return Settings(
        api_key=api_key,
        base_url=base_url,
        model=model or _DEFAULT_MODEL,
        timeout=timeout,
        serper_key=_first_env("SERPER_API_KEY"),
        bocha_key=_first_env("BOCHA_API_KEY"),
        wecom_webhook=_first_env("WECOM_WEBHOOK"),
        dingtalk_webhook=_first_env("DINGTALK_WEBHOOK"),
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = _load()
    return _settings
