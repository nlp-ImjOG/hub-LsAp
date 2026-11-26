"""DeepSeek（OpenAI 兼容）调用封装：环境加载 + JSON 输出重试。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    raise SystemExit("缺少依赖 openai，请先执行: pip install -r requirements.txt")

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def load_dotenv() -> None:
    """从脚本目录向上查找 .env 并加载，已存在的环境变量不覆盖。"""
    for parent in Path(__file__).resolve().parents:
        env_file = parent / ".env"
        if not env_file.is_file():
            continue
        try:
            lines = env_file.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            lines = env_file.read_text(encoding="gbk", errors="ignore").splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return


def get_config() -> tuple[str, str, str]:
    load_dotenv()
    api_key = os.environ.get("DS_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
    base_url = (os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL).strip()
    model = (os.environ.get("LLM_MODEL") or DEFAULT_MODEL).strip()
    if not api_key:
        raise SystemExit(
            "未找到 DS_API_KEY：请在环境变量或仓库根目录 .env 中配置 "
            "DS_API_KEY / LLM_BASE_URL / LLM_MODEL 后重试。"
        )
    return api_key, base_url, model


def _extract_json(text: str) -> Any:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    end = max(text.rfind("}"), text.rfind("]"))
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法解析为 JSON：{text[:200]}...")


def chat_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.0,
    retries: int = 2,
    max_tokens: int | None = None,
) -> Any:
    """调用 LLM 并返回解析后的 JSON。失败时重试，最终抛 SystemExit。"""
    api_key, base_url, model = get_config()
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=180)
    last_error: Exception | None = None
    for _ in range(retries + 1):
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        try:
            try:
                resp = client.chat.completions.create(
                    **payload, response_format={"type": "json_object"}
                )
            except Exception:
                # 部分 OpenAI 兼容网关不支持 response_format，降级重试
                resp = client.chat.completions.create(**payload)
            content = (resp.choices[0].message.content or "").strip()
            return _extract_json(content)
        except Exception as exc:  # noqa: BLE001 - 网络与解析错误统一重试
            last_error = exc
    raise SystemExit(f"LLM 调用失败（模型 {model}）：{last_error}")
