"""OpenAI 兼容 LLM：逐来源抽取条目 + 生成一页纸速览/行动建议。

设计原则：
1. 只让模型做“从给定资料中抽取/归纳”，不让它自由检索或补事实。
2. 返回 JSON，解析失败重试一次，仍失败则该来源跳过。
3. LLM 挂掉不能让整条流水线挂掉——上层可降级到离线模板。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from .config import Settings
from .models import Category, Executive, Item, Source

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*(.*?)\s*```\s*$", re.DOTALL)


class LLMError(RuntimeError):
    pass


def strip_fence(text: str) -> str:
    match = _FENCE_RE.match(text or "")
    return match.group(1).strip() if match else (text or "").strip()


def extract_json_object(text: str) -> str | None:
    start = (text or "").find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def parse_json(text: str) -> dict[str, Any]:
    cleaned = strip_fence(text)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        block = extract_json_object(cleaned)
        if not block:
            raise LLMError("LLM 返回中找不到 JSON 对象")
        try:
            value = json.loads(block)
        except json.JSONDecodeError as exc:
            raise LLMError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(value, dict):
        raise LLMError("LLM 返回的 JSON 不是对象")
    return value


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._settings.llm_timeout_s,
                headers={
                    "Authorization": f"Bearer {self._settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        if not self._settings.llm_api_key:
            raise LLMError("LLM_API_KEY 未配置")
        body: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": messages,
            "temperature": self._settings.llm_temperature,
            "max_tokens": self._settings.llm_max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        url = self._settings.llm_base_url.rstrip("/") + "/chat/completions"
        response = await (await self._http()).post(url, json=body)
        if response.status_code == 400 and json_mode:
            # 少数网关不支持 response_format，退化为纯文本 + 解析层兜底
            body.pop("response_format", None)
            response = await (await self._http()).post(url, json=body)
        if response.status_code != 200:
            raise LLMError(f"LLM HTTP {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
            message = payload["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM 响应不是有效 JSON，或缺少 choices[0].message") from exc
        return str(message.get("content") or message.get("reasoning_content") or "")

    async def chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        text = await self.chat(messages, json_mode=True)
        try:
            return parse_json(text)
        except LLMError as first_error:
            repair = [
                *messages,
                {"role": "assistant", "content": text[:2000]},
                {
                    "role": "user",
                    "content": "上面的输出不是合法 JSON。请只输出一个 JSON 对象，不要解释、不要 Markdown 围栏。",
                },
            ]
            try:
                return parse_json(await self.chat(repair, json_mode=True))
            except LLMError:
                raise first_error

    async def __aenter__(self) -> LLMClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


ANALYZE_SYSTEM = """你是严谨的 ESG 分析师。只使用 <source> 中的信息，不得编造数字、日期、政策文号、评级或链接。
如果资料不足以支持一条有实质影响的 ESG 信息，返回 {"items": []}。
返回 JSON 对象，格式：
{"items":[{"title":"不超过30字","fact":"谁、何时、做了什么，含原文关键数字","impact":"对客户哪个 ESG 维度、什么程度、为什么","impact_level":"高|中|低","recommendation":"客户可执行的动作","subcategory":"国内政策|国际标准|评级|市场|最佳实践|经营|安全|治理"}]}
每个来源最多 2 条；fact 必须能在原文找到依据。
严格区分集团与上市公司（如国家能源集团 ≠ 中国神华）。
评级类信息必须写机构、评级日期、是否本月变动；没有变动就写“本月无变动，最新为{日期}{等级}”。"""


EXEC_SYSTEM = """你是 ESG 月报主编。基于给定条目写一页纸速览和行动建议，不得引入新事实。
返回 JSON 对象：
{"summary":["3-5条，每条≤60字"],"short_actions":["1个月内"],"mid_actions":["1-3个月"],"long_actions":["3-12个月"],"risk_opportunities":[{"dimension":"环境|社会|治理|市场","risk":"...","opportunity":"..."}]}
summary 总字数不超过 300 字。"""


def _source_text(source: Source) -> str:
    text = source.content or source.snippet
    return text[:5000]


async def analyze_source(client: LLMClient, source: Source, client_name: str, industry: str) -> list[Item]:
    user = (
        f"客户：{client_name}\n行业：{industry}\n"
        f"来源编号：{source.sid}\n标题：{source.title}\n站点：{source.site}\n"
        f"发布日期：{source.published_at or '未披露'}\n"
        f"<source>\n{_source_text(source)}\n</source>"
    )
    try:
        payload = await client.chat_json(
            [{"role": "system", "content": ANALYZE_SYSTEM}, {"role": "user", "content": user}]
        )
    except LLMError as exc:
        logger.warning("抽取失败 %s: %s", source.sid, exc)
        return []

    items: list[Item] = []
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = []
    for raw in raw_items[:2]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        fact = str(raw.get("fact") or "").strip()
        impact = str(raw.get("impact") or "").strip()
        recommendation = str(raw.get("recommendation") or "").strip()
        if not (title and fact and impact and recommendation):
            continue
        level = str(raw.get("impact_level") or "中").strip()
        if level not in {"高", "中", "低"}:
            level = "中"
        subcategory = str(raw.get("subcategory") or "").strip()
        if not subcategory:
            subcategory = "国内政策" if source.category == Category.policy else "市场"
        items.append(
            Item(
                category=source.category,
                subcategory=subcategory,
                title=title[:40],
                fact=fact,
                source_ids=[source.sid],
                impact=impact,
                impact_level=level,
                recommendation=recommendation,
                period_tag="报告期后" if source.date_status.value == "after_window" else "本月",
            )
        )
    return items


def _dedup_items(items: list[Item]) -> list[Item]:
    kept: list[Item] = []
    for item in items:
        if any(item.title == existing.title for existing in kept):
            continue
        kept.append(item)
    return kept


async def analyze_sources(
    client: LLMClient,
    sources: list[Source],
    client_name: str,
    industry: str,
    concurrency: int = 3,
) -> list[Item]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run(source: Source) -> list[Item]:
        async with semaphore:
            return await analyze_source(client, source, client_name, industry)

    batches = await asyncio.gather(*(run(source) for source in sources))
    items = _dedup_items([item for batch in batches for item in batch])
    if not items:
        raise LLMError("LLM 未从任何来源中抽取到有效条目")
    return items


async def write_executive(client: LLMClient, items: list[Item], client_name: str, industry: str) -> Executive:
    payload_items = [
        {
            "title": item.title,
            "fact": item.fact,
            "impact": item.impact,
            "impact_level": item.impact_level,
            "source_ids": item.source_ids,
        }
        for item in items
    ]
    user = (
        f"客户：{client_name}\n行业：{industry}\n"
        f"条目（JSON）：\n{json.dumps(payload_items, ensure_ascii=False)}"
    )
    try:
        payload = await client.chat_json(
            [{"role": "system", "content": EXEC_SYSTEM}, {"role": "user", "content": user}]
        )
    except LLMError as exc:
        logger.warning("速览生成失败，使用模板兜底: %s", exc)
        return _fallback_executive(items, client_name, industry)

    def strings(key: str) -> list[str]:
        value = payload.get(key)
        if not isinstance(value, list):
            return []
        return [str(x).strip() for x in value if str(x).strip()]

    risk = payload.get("risk_opportunities")
    risks = []
    if isinstance(risk, list):
        for row in risk:
            if isinstance(row, dict) and row.get("dimension") and row.get("risk") and row.get("opportunity"):
                risks.append({k: str(row[k]) for k in ("dimension", "risk", "opportunity")})

    return Executive(
        summary=strings("summary")[:5] or _fallback_executive(items, client_name, industry).summary,
        short_actions=strings("short_actions")[:4],
        mid_actions=strings("mid_actions")[:4],
        long_actions=strings("long_actions")[:4],
        risk_opportunities=risks or _fallback_executive(items, client_name, industry).risk_opportunities,
    )


def _fallback_executive(items: list[Item], client_name: str, industry: str) -> Executive:
    high = [item for item in items if item.impact_level == "高"]
    top = high[:3] or items[:3]
    summary = [
        f"{item.title}：{item.fact[:50]}" for item in top
    ]
    summary.append(f"建议{client_name}优先跟踪高影响事项，并把 ESG 要求纳入四季度经营与披露安排。")
    return Executive(
        summary=summary[:5],
        short_actions=["梳理本月高影响事项的责任部门与时间表。"],
        mid_actions=["将 ESG 指标纳入年度预算与绩效考核。"],
        long_actions=["完善 ESG 数据与披露体系，准备下一年度报告。"],
        risk_opportunities=[
            {"dimension": "环境", "risk": "碳价与甲烷/碳足迹披露压力", "opportunity": "瓦斯利用、CCUS、绿电"},
            {"dimension": "社会", "risk": "安全生产与外包队伍合规", "opportunity": "智能矿山与安全培训"},
            {"dimension": "治理", "risk": "关联交易与披露不完整", "opportunity": "内控与 ESG 数据中台"},
            {"dimension": "市场", "risk": "煤价波动与 CBAM/供应链要求", "opportunity": "煤电联营与转型金融"},
        ],
    )
