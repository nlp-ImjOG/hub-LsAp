"""LLM：逐来源抽取招标项目 + 生成复盘/日报洞察。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date
from typing import Any

import httpx

from .config import Settings
from .filter import amount_type_from_status, classify_tender, dedupe_tenders, parse_amount, status_from_text
from .models import (
    AmountType,
    DailyInsights,
    ReviewInsights,
    Source,
    Tender,
    TenderStatus,
)
from .search import parse_date

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
                {"role": "user", "content": "上面的输出不是合法 JSON。请只输出一个 JSON 对象，不要解释、不要 Markdown 围栏。"},
            ]
            try:
                return parse_json(await self.chat(repair, json_mode=True))
            except LLMError:
                raise first_error

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


EXTRACT_SYSTEM = """你是招投标情报分析师。只使用 <source> 中的信息，不得编造金额、日期、中标方或链接。
返回 JSON 对象：
{"tender":{"project":"项目名称","buyer":"采购人","region":"地区","category":"分类","status":"招标|候选人|中标/成交|合同|终止/流标","publish_date":"YYYY-MM-DD 或 null","deadline":"YYYY-MM-DD 或 null","budget":数字或null,"ceiling":数字或null,"award":数字或null,"amount_type":"预算|最高限价|中标/成交|候选人报价|合同|未披露","winner":"中标方，未知留空","notes":"关键资格/服务期/备注"}}
金额单位统一万元；没有就 null。project 必须具体；如果只是一篇泛泛的行业文章、不是具体招标/中标项目，返回 {"tender": null}。
category 只能从以下选一个：ESG报告/信息披露、ESG咨询/管理提升/评级、碳盘查/碳核算/碳足迹、碳资产/碳交易/CCER、双碳规划/零碳园区/碳预算、碳管理/ESG数字化平台、ESG评价/工程ESG、绿色金融/转型金融、ESG培训/能力建设、其他。
候选人不能写成中标人；预算不能写成中标金额。"""


REVIEW_SYSTEM = """你是招投标市场分析师。基于给定的统计与项目清单，写复盘洞察，不得引入新事实。
返回 JSON：
{"summary":["3-5条，每条≤80字"],"hot_topics":[{"topic":"...","count":"...","amount":"...","driver":"..."}],"recommendations":["..."],"risks":["..."]}
summary 要突出金额分布、数量与金额倒挂、最热赛道；recommendations 要可执行。"""


DAILY_SYSTEM = """你是招投标情报编辑。基于给定新增项目，写日报摘要，不得引入新事实。
返回 JSON：
{"summary":["3-5条，每条≤70字"],"actions":["1-3条建议动作"]}
summary 要突出今日新增、P0/P1、截止提醒、竞争对手中标；actions 要具体。"""


async def extract_tender(client: LLMClient, source: Source, focus: str) -> Tender | None:
    text = (source.content or source.snippet)[:5000]
    user = (
        f"关注方向：{focus}\n来源编号：{source.sid}\n标题：{source.title}\n"
        f"站点：{source.site}\n发布日期：{source.published_at or '未披露'}\n"
        f"<source>\n{text}\n</source>"
    )
    try:
        payload = await client.chat_json(
            [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user}]
        )
    except LLMError as exc:
        logger.warning("抽取失败 %s: %s", source.sid, exc)
        return None
    raw = payload.get("tender")
    if not isinstance(raw, dict):
        return None

    project = str(raw.get("project") or "").strip()
    if not project:
        return None
    status = status_from_text(str(raw.get("status") or source.title + " " + source.snippet))
    category = str(raw.get("category") or "").strip()
    if category not in {
        "ESG报告/信息披露", "ESG咨询/管理提升/评级", "碳盘查/碳核算/碳足迹",
        "碳资产/碳交易/CCER", "双碳规划/零碳园区/碳预算", "碳管理/ESG数字化平台",
        "ESG评价/工程ESG", "绿色金融/转型金融", "ESG培训/能力建设", "其他",
    }:
        category = classify_tender(source.title + " " + source.snippet)

    amount_type = str(raw.get("amount_type") or "").strip()
    if amount_type not in {item.value for item in AmountType}:
        amount_type = amount_type_from_status(status).value

    budget = parse_amount(raw.get("budget"))
    ceiling = parse_amount(raw.get("ceiling"))
    award = parse_amount(raw.get("award"))
    publish_date = parse_date(raw.get("publish_date")) or source.published_at
    deadline = parse_date(raw.get("deadline"))
    winner = str(raw.get("winner") or "").strip()
    if "候选人" in winner and status is TenderStatus.awarded:
        status = TenderStatus.candidate
        amount_type = AmountType.candidate.value

    return Tender(
        project=project,
        buyer=str(raw.get("buyer") or "").strip(),
        region=str(raw.get("region") or "").strip(),
        category=category,
        status=status,
        publish_date=publish_date,
        deadline=deadline,
        budget=budget,
        ceiling=ceiling,
        award=award,
        amount_type=AmountType(amount_type),
        winner=winner,
        source_id=source.sid,
        source_url=source.url,
        source_site=source.site,
        year=publish_date.year if publish_date else None,
        notes=str(raw.get("notes") or "").strip(),
        confidence="高" if source.fetch_status == "page" else "中",
    )


async def extract_tenders(
    client: LLMClient, sources: list[Source], focus: str, concurrency: int = 3
) -> list[Tender]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run(source: Source) -> Tender | None:
        async with semaphore:
            return await extract_tender(client, source, focus)

    results = await asyncio.gather(*(run(source) for source in sources))
    tenders = dedupe_tenders([tender for tender in results if tender is not None])
    if not tenders:
        raise LLMError("LLM 未从任何来源中抽取到招标项目")
    return tenders


async def write_review_insights(
    client: LLMClient, tenders: list[Tender], stats: dict[str, object], focus: str
) -> ReviewInsights:
    payload = {
        "focus": focus,
        "stats": {
            "n": stats["n"],
            "total": stats["total"],
            "median": stats["median"],
            "mean": stats["mean"],
            "categories": stats["categories"],
            "buckets": stats["buckets"],
            "top_projects": stats["top_projects"],
        },
    }
    user = f"统计与项目（JSON）：\n{json.dumps(payload, ensure_ascii=False)}"
    try:
        data = await client.chat_json(
            [{"role": "system", "content": REVIEW_SYSTEM}, {"role": "user", "content": user}]
        )
    except LLMError as exc:
        logger.warning("复盘洞察失败，使用模板兜底: %s", exc)
        return _fallback_review_insights(stats, focus)

    def strings(key: str) -> list[str]:
        value = data.get(key)
        return [str(x).strip() for x in value if str(x).strip()] if isinstance(value, list) else []

    topics = data.get("hot_topics")
    hot_topics = []
    if isinstance(topics, list):
        for row in topics:
            if isinstance(row, dict) and row.get("topic"):
                hot_topics.append({k: str(row.get(k, "")) for k in ("topic", "count", "amount", "driver")})
    return ReviewInsights(
        summary=strings("summary")[:5] or _fallback_review_insights(stats, focus).summary,
        hot_topics=hot_topics or _fallback_review_insights(stats, focus).hot_topics,
        recommendations=strings("recommendations")[:6],
        risks=strings("risks")[:5],
    )


async def write_daily_insights(client: LLMClient, tenders: list[Tender]) -> DailyInsights:
    payload = [
        {
            "project": t.project,
            "buyer": t.buyer,
            "amount": t.award if t.award is not None else t.budget,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "priority": t.priority,
            "status": t.status.value,
        }
        for t in tenders[:12]
    ]
    user = f"新增项目（JSON）：\n{json.dumps(payload, ensure_ascii=False)}"
    try:
        data = await client.chat_json(
            [{"role": "system", "content": DAILY_SYSTEM}, {"role": "user", "content": user}]
        )
    except LLMError as exc:
        logger.warning("日报摘要失败，使用模板兜底: %s", exc)
        return _fallback_daily_insights(tenders)

    def strings(key: str) -> list[str]:
        value = data.get(key)
        return [str(x).strip() for x in value if str(x).strip()] if isinstance(value, list) else []

    return DailyInsights(
        summary=strings("summary")[:5] or _fallback_daily_insights(tenders).summary,
        actions=strings("actions")[:3],
    )


def _fallback_review_insights(stats: dict[str, object], focus: str) -> ReviewInsights:
    categories = stats.get("categories") or {}
    top_categories = list(categories.items())[:3] if isinstance(categories, dict) else []
    summary = [
        f"样本 {stats['n']} 个项目，已披露金额 {stats['total']} 万元，中位数 {stats['median']} 万元。",
        "金额高度集中：大额项目贡献主要金额，报告类项目数量多但单价低。",
        "建议按“报告走量、咨询提价、规划/平台找联合体”分层打法。",
    ]
    hot_topics = [
        {
            "topic": name,
            "count": str(data.get("n", "")),
            "amount": str(data.get("sum", "")),
            "driver": "政策与客户需求驱动",
        }
        for name, data in top_categories
    ]
    return ReviewInsights(
        summary=summary,
        hot_topics=hot_topics,
        recommendations=[
            f"围绕{focus}建立标准化报告产品，控制交付成本。",
            "把评级提升、碳核算、CBAM 打包进咨询项目，提高客单价。",
            "大型规划/平台项目优先与规划院、软件商组成联合体。",
        ],
        risks=[
            "公开数据不完整，样本可能低估长尾项目。",
            "预算与中标金额口径混淆会高估市场。",
            "平台类项目资质门槛高，纯咨询机构独立投标风险大。",
        ],
    )


def _fallback_daily_insights(tenders: list[Tender]) -> DailyInsights:
    p0 = [t for t in tenders if t.priority == "P0"]
    p1 = [t for t in tenders if t.priority == "P1"]
    deadlines = sorted([t for t in tenders if t.deadline], key=lambda t: t.deadline)  # type: ignore[arg-type]
    summary = [
        f"本期新增 {len(tenders)} 条，P0 {len(p0)} 条、P1 {len(p1)} 条。",
        f"最值得关注：{tenders[0].project if tenders else '暂无'}。",
    ]
    if deadlines:
        summary.append(f"最近截止：{deadlines[0].project}（{deadlines[0].deadline}）。")
    return DailyInsights(
        summary=summary,
        actions=["优先确认 P0 项目的报名与资格条件。", "平台类项目同步联系软件/集成商。", "报告类项目准备同行业案例。"],
    )
