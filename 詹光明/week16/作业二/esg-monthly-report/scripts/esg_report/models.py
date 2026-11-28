"""数据契约：来源、条目、报告。"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class Category(StrEnum):
    policy = "policy"
    industry = "industry"
    company = "company"
    benchmark = "benchmark"


class DateStatus(StrEnum):
    verified = "verified"          # 发布日期在报告期内
    after_window = "after_window"  # 报告期后、编制日前
    outside_window = "outside_window"
    unverified = "unverified"      # 无发布日期，保留但标注


class Source(BaseModel):
    sid: str = ""
    title: str = ""
    url: str = ""
    site: str = ""
    published_at: date | None = None
    snippet: str = ""
    content: str = ""
    category: Category = Category.industry
    authority: int = 2  # 1 聚合 / 2 媒体 / 3 官方
    relevance: int = 0
    date_status: DateStatus = DateStatus.unverified
    fetch_status: str = "snippet"  # page / snippet / blocked / error
    duplicate_of: str | None = None


class Item(BaseModel):
    category: Category
    subcategory: str = ""
    title: str
    fact: str
    source_ids: list[str] = Field(default_factory=list)
    impact: str = ""
    impact_level: str = "中"  # 高 / 中 / 低
    recommendation: str = ""
    period_tag: str = "本月"  # 本月 / 报告期后


class RawResult(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""
    summary: str = ""
    site: str = ""
    published_at: date | None = None


class SearchOutcome(BaseModel):
    query: str
    category: Category
    ok: bool = True
    results: list[RawResult] = Field(default_factory=list)
    error: str | None = None
    latency_ms: int = 0
    top_level_keys: list[str] = Field(default_factory=list)


class Executive(BaseModel):
    summary: list[str] = Field(default_factory=list)
    short_actions: list[str] = Field(default_factory=list)
    mid_actions: list[str] = Field(default_factory=list)
    long_actions: list[str] = Field(default_factory=list)
    risk_opportunities: list[dict[str, str]] = Field(default_factory=list)


class ReportData(BaseModel):
    client: str
    industry: str
    period_start: date
    period_end: date
    generated_at: date
    summary: list[str] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    executive: Executive = Field(default_factory=Executive)
    gaps: list[str] = Field(default_factory=list)
    query_log: list[dict[str, object]] = Field(default_factory=list)
    offline: bool = False


class RunResult(BaseModel):
    report: ReportData
    markdown_path: str
    sources_path: str
    run_path: str
    warnings: list[str] = Field(default_factory=list)
