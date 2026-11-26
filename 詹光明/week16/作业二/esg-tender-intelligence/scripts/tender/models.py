"""数据契约：招标项目、来源、复盘/日报。"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class TenderStatus(StrEnum):
    tender = "招标"
    candidate = "候选人"
    awarded = "中标/成交"
    contract = "合同"
    terminated = "终止/流标"
    expired = "已截止"
    unknown = "未披露"


class AmountType(StrEnum):
    budget = "预算"
    ceiling = "最高限价"
    award = "中标/成交"
    candidate = "候选人报价"
    contract = "合同"
    unknown = "未披露"


class Tender(BaseModel):
    tid: str = ""
    project: str
    buyer: str = ""
    region: str = ""
    category: str = ""
    status: TenderStatus = TenderStatus.unknown
    publish_date: date | None = None
    deadline: date | None = None
    budget: float | None = None
    ceiling: float | None = None
    award: float | None = None
    amount_type: AmountType = AmountType.unknown
    winner: str = ""
    source_id: str = ""
    source_url: str = ""
    source_site: str = ""
    priority: str = "P2"
    period_tag: str = "本期"
    year: int | None = None
    notes: str = ""
    confidence: str = "中"
    first_seen: date | None = None
    last_seen: date | None = None

    @property
    def amount(self) -> float | None:
        """金额分析优先用中标/成交，其次候选人报价。"""
        if self.amount_type in (AmountType.award, AmountType.contract):
            return self.award
        if self.amount_type == AmountType.candidate:
            return self.award
        return None


class Source(BaseModel):
    sid: str = ""
    title: str = ""
    url: str = ""
    site: str = ""
    published_at: date | None = None
    snippet: str = ""
    content: str = ""
    authority: int = 2
    fetch_status: str = "snippet"
    duplicate_of: str | None = None


class RawResult(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""
    summary: str = ""
    site: str = ""
    published_at: date | None = None


class SearchOutcome(BaseModel):
    query: str
    category: str = ""
    ok: bool = True
    results: list[RawResult] = Field(default_factory=list)
    error: str | None = None
    latency_ms: int = 0
    top_level_keys: list[str] = Field(default_factory=list)


class ReviewInsights(BaseModel):
    summary: list[str] = Field(default_factory=list)
    hot_topics: list[dict[str, str]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class DailyInsights(BaseModel):
    summary: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


class ReviewReport(BaseModel):
    focus: str
    period_start: date
    period_end: date
    generated_at: date
    tenders: list[Tender]
    sources: list[Source]
    insights: ReviewInsights
    gaps: list[str] = Field(default_factory=list)
    query_log: list[dict[str, object]] = Field(default_factory=list)
    offline: bool = False


class DailyReport(BaseModel):
    report_date: date
    window_start: date
    window_end: date
    tenders: list[Tender]
    reference_tenders: list[Tender] = Field(default_factory=list)
    insights: DailyInsights
    ledger_path: str = ""
    gaps: list[str] = Field(default_factory=list)
    query_log: list[dict[str, object]] = Field(default_factory=list)
    offline: bool = False


class RunResult(BaseModel):
    markdown_path: str
    ledger_path: str = ""
    run_path: str = ""
    warnings: list[str] = Field(default_factory=list)
