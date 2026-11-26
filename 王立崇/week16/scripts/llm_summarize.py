"""LLM 结构化摘要 / 相关性筛选 / 去重（OpenAI 兼容协议）。

无 Key 时由编排脚本降级为规则抽取，不调用本模块。
"""
from __future__ import annotations

import json
import re
from typing import Any

try:
    from . import config
except ImportError:  # 直接 `python llm_summarize.py` 运行时
    import config  # type: ignore

_client = None

_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        s = config.get_settings()
        if not s.llm_enabled:
            raise RuntimeError("未配置 API Key，无法调用 LLM")
        _client = OpenAI(
            api_key=s.api_key, base_url=s.base_url, timeout=s.timeout, max_retries=1
        )
    return _client


def extract_json(raw: str) -> dict[str, Any] | list[Any]:
    """从模型输出里抠出 JSON（处理 ```json 代码块、前后废话）。"""
    text = (raw or "").strip()
    candidates: list[str] = [text]
    m = _FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    start, end = text.find("["), text.rfind("]")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
    raise ValueError(f"无法从模型输出中解析 JSON：{raw!r}")


def complete(system: str, user: str, *, temperature: float = 0.0, json_mode: bool = False) -> str:
    s = config.get_settings()
    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs: dict[str, Any] = dict(model=s.model, messages=msgs, temperature=temperature)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = get_client().chat.completions.create(**kwargs)
    except Exception:
        if json_mode:  # 部分兼容服务不支持 response_format，去掉后重试
            kwargs.pop("response_format")
            resp = get_client().chat.completions.create(**kwargs)
        else:
            raise
    return (resp.choices[0].message.content or "").strip()


# ---- 业务级封装 ------------------------------------------------------------

_DEFAULT_FIELDS = ["title", "source", "date", "summary", "esg_relevance", "suggestion"]


def summarize_documents(
    docs: list[dict[str, str]],
    instruction: str,
    fields: list[str] | None = None,
    temperature: float = 0.0,
) -> list[dict[str, Any]]:
    """把一批检索到的文档（title/url/snippet/text）交给 LLM 做结构化摘要。

    要求 LLM 返回 JSON 数组，每项只包含 `fields` 指定字段。
    调用方用 extract_json 解析。
    """
    fields = fields or _DEFAULT_FIELDS
    payload = json.dumps(docs, ensure_ascii=False)[:20000]  # 控制上下文长度
    system = (
        "你是 ESG 咨询顾问助手。请对给定的检索结果做筛选、去重与结构化摘要。\n"
        f"只输出 JSON 数组，每项包含字段：{', '.join(fields)}。"
        "剔除与主题无关、重复、广告或无法确认来源的条目；"
        "若缺少日期则留空字符串；summary 用中文一两句概括事实，esg_relevance 说明与 ESG/双碳 的关联，"
        "suggestion 给出对客户的一句话建议（无建议则留空）。"
    )
    user = f"检索主题：{instruction}\n\n检索结果：\n{payload}"
    raw = complete(system, user, temperature=temperature, json_mode=True)
    data = extract_json(raw)
    return data if isinstance(data, list) else [data]


def dedupe(items: list[dict[str, Any]], key: str = "title") -> list[dict[str, Any]]:
    """按标题归一化去重（去空白/标点/大小写），保留首次出现。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        norm = re.sub(r"[\W_]+", "", str(it.get(key, ""))).lower()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(it)
    return out
