"""内容总结:优先 LLM(OpenAI 兼容,可接智谱 GLM/OpenAI);无 key 时降级为本地抽取式摘要。

确定性体现:
- LLM 段使用固定 system prompt + 结构化输出要求,把"自由发挥"约束成可解析的字段;
- 降级段是纯算法(TF 句子打分),完全确定性、可复现。
"""
from __future__ import annotations

import json
import re
from typing import Iterable

from .config import CONFIG


def _extractive_summary(text: str, max_sentences: int = 5) -> str:
    """简单 TF 句子打分摘要(无需 LLM、无需额外依赖)。"""
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[。!!?;])\s+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 8]
    if len(sentences) <= max_sentences:
        return " ".join(sentences)

    words = [w for w in re.findall(r"[一-龥]{2,}|[A-Za-z]+", text.lower())]
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    # 归一化避免长句必胜
    scored = []
    for s in sentences:
        ws = re.findall(r"[一-龥]{2,}|[A-Za-z]+", s.lower())
        score = sum(freq.get(w, 0) for w in ws) / (len(ws) + 1)
        scored.append((score, s))
    top = sorted(scored, key=lambda x: -x[0])[:max_sentences]
    # 按原文顺序输出
    top_s = {id(s) for _, s in top}
    return " ".join(s for s in sentences if id(s) in top_s)


def llm_complete(system: str, user: str, temperature: float = 0.2) -> str:
    """调用 OpenAI 兼容接口。无 key 抛 RuntimeError。"""
    from openai import OpenAI

    client = OpenAI(api_key=CONFIG.llm_api_key, base_url=CONFIG.llm_base_url)
    resp = client.chat.completions.create(
        model=CONFIG.llm_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def summarize_text(text: str, focus: str = "", max_sentences: int = 5) -> str:
    """总结一段正文。focus 为关注点(如"政策对煤炭行业的影响")。"""
    if not text:
        return ""
    if CONFIG.llm_enabled:
        sys = (
            "你是严谨的 ESG 研究分析师。基于给定正文做事实性总结,只使用正文信息,"
            "不得编造。输出 3-5 条要点,每条一句话,带可量化的关键数字(若有)。"
            f"关注点:{focus or 'ESG 相关动态'}。"
        )
        try:
            return llm_complete(sys, text[: CONFIG.fetch_max_chars])
        except Exception as e:
            # 降级,不中断流水线
            return f"[LLM 调用失败,降级为抽取式摘要] {_extractive_summary(text, max_sentences)}\n# err: {e}"
    return _extractive_summary(text, max_sentences)


def llm_json(system: str, user: str, schema_hint: str) -> dict | list:
    """要求 LLM 返回 JSON。失败返回空 dict/list。"""
    if not CONFIG.llm_enabled:
        return {}
    full_system = system + f"\n必须只输出合法 JSON,不要任何解释文字。结构:\n{schema_hint}"
    raw = llm_complete(full_system, user, temperature=0.1)
    raw = raw.strip()
    # 去掉可能的 ```json 围栏
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {}
