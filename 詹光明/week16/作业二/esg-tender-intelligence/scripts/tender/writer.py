"""Markdown 组装：历史复盘 + 每日日报 + 台账。"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from jinja2 import Environment

from .filter import priority
from .models import DailyReport, ReviewReport, Tender, TenderStatus

REVIEW_TEMPLATE = """# {{ report.focus }} 投标市场复盘（{{ period_label }}）

> 统计窗口：{{ report.period_start }} 至 {{ report.period_end }} ｜ 样本：{{ stats.n }} 条（金额披露 {{ stats.amount_disclosed }} 条）｜ 编制日期：{{ report.generated_at }} ｜ 来源：{{ report.sources|length }} 条

## 一页纸速览

{% for line in report.insights.summary %}- {{ line }}
{% endfor %}

## 二、样本与方法

- **时间窗口：** {{ report.period_start }} 至 {{ report.period_end }}。
- **样本量：** {{ stats.n }} 条，其中 {{ stats.amount_disclosed }} 条披露金额；不代表全市场普查。
- **来源：** {{ report.sources|length }} 个来源，含政府采购、公共资源交易、央企采购平台及主流媒体。
- **金额口径：** 优先中标/成交金额；候选人报价单独标注；预算/上限不混入金额分布。
- **纳入标准：** ESG、可持续发展、双碳相关的咨询、报告、碳核算/碳足迹、双碳规划、零碳园区、碳管理平台、ESG 评价等服务；排除纯设备、EPC、工程总包。

### 年度构成

| 年度 | 项目数 | 已披露金额（万元） | 中位数（万元） |
|---|---:|---:|---:|
{% for year, row in stats.years.items() %}| {{ year }} | {{ row.n }} | {{ row.sum }} | {{ row.median }} |
{% endfor %}| **合计** | **{{ stats.n }}** | **{{ stats.total }}** | **{{ stats.median }}** |

## 三、市场总览

### 3.1 金额分布

| 金额区间 | 项目数 | 金额合计（万元） | 金额占比 |
|---|---:|---:|---:|
{% for name, row in stats.buckets.items() if row.n %}| {{ name }} | {{ row.n }} | {{ row.sum }} | {{ row.share }}% |
{% endfor %}

### 3.2 类别结构

| 类别 | 项目数 | 金额合计（万元） | 金额占比 | 中位数（万元） |
|---|---:|---:|---:|---:|
{% for name, row in stats.categories.items() %}| {{ name }} | {{ row.n }} | {{ row.sum }} | {{ row.share }}% | {{ row.median }} |
{% endfor %}

### 3.3 区域与竞争

**区域分布：** {% for region, count in stats.regions.items() %}{{ region }} {{ count }}{% if not loop.last %}、{% endif %}{% endfor %}。

**中标方出现频次（样本）：**

| 中标方 | 出现次数 |
|---|---:|
{% for winner, count in stats.winners.items() %}| {{ winner }} | {{ count }} |
{% endfor %}

**金额 Top 10：**

| 项目 | 采购人 | 金额（万元） | 类别 |
|---|---|---:|---|
{% for item in stats.top_projects %}| {{ item.project }} | {{ item.buyer }} | {{ item.amount }} | {{ item.category }} |
{% endfor %}

## 四、热点招标分析

{% for topic in report.insights.hot_topics %}### {{ loop.index }}. {{ topic.topic }}

- 项目数：{{ topic.count }}
- 金额：{{ topic.amount }}
- 驱动：{{ topic.driver }}
- 代表项目：{% for item in top_by_category.get(topic.topic, []) %}{{ item.project }}（{{ item.amount }} 万元）{% if not loop.last %}；{% endif %}{% endfor %}

{% endfor %}

## 五、投标策略建议

**建议：**
{% for item in report.insights.recommendations %}- {{ item }}
{% endfor %}

**风险：**
{% for item in report.insights.risks %}- {{ item }}
{% endfor %}

## 附录 A 样本明细

| # | 年份 | 项目 | 采购人 | 类别 | 金额（万元） | 中标方/候选人 | 地区 | 来源 |
|---:|---|---|---|---|---:|---|---|---|
{% for tender in report.tenders %}| {{ loop.index }} | {{ tender.year or "—" }} | {{ tender.project }} | {{ tender.buyer or "未披露" }} | {{ tender.category }} | {{ tender.amount if tender.amount is not none else "未披露" }} | {{ tender.winner or "未披露" }} | {{ tender.region or "未披露" }} | {{ tender.source_id or "—" }} |
{% endfor %}

## 附录 B 来源清单

| 编号 | 标题 | 发布机构 | 日期 | URL |
|---|---|---|---|---|
{% for source in report.sources %}| {{ source.sid }} | {{ source.title }} | {{ source.site or "未披露" }} | {{ source.published_at or "未披露" }} | {{ source.url }} |
{% endfor %}

## 附录 C 方法与局限

- 公开网页检索无法保证全量；样本、金额披露率和区域分布均受检索命中影响。
- 部分项目只披露预算或候选人报价，已按金额类型标注，不混入中标金额分布。
- 多平台重复公告已按“项目名称 + 采购人”去重；多标段项目按公告总金额计一次。
- 关键数字、金额与中标方请以官方公告原文为准。

{% if report.gaps %}**质量提示：**
{% for gap in report.gaps %}- {{ gap }}
{% endfor %}{% endif %}

## 免责声明

本报告基于公开信息整理，不构成投资建议或投标承诺。金额、中标方与日期请以官方公告原文为准。
"""

DAILY_TEMPLATE = """# ESG 招标日报 {{ report.report_date }}

> 监控窗口：{{ report.window_start }} 至 {{ report.window_end }} ｜ 新增：{{ tenders|length }} 条 ｜ 高优先级：{{ high_priority|length }} 条 ｜ 来源：{{ sources|length }} 个{{ " ｜ **离线样例（固定 fixture）**" if report.offline else "" }}

## 推送摘要

{% for line in report.insights.summary %}- {{ line }}
{% endfor %}

{% if report.insights.actions %}**建议动作：**
{% for action in report.insights.actions %}- {{ action }}
{% endfor %}{% endif %}

## 一、今日必看（P0/P1）

| 优先级 | 项目 | 采购人 | 预算/中标（万元） | 截止 | 分类 | 来源 |
|---|---|---|---|---|---|---|
{% for tender in must_see %}| **{{ tender.priority }}** | {{ tender.project }} | {{ tender.buyer or "未披露" }} | {{ amount_label(tender) }} | {{ tender.deadline or "未披露" }} | {{ tender.category }} | {{ tender.source_id or tender.source_url or "—" }} |
{% endfor %}
{% if not must_see %}| — | 本期无 P0/P1 项目 | — | — | — | — | — |
{% endif %}

## 二、新增招标（按分类）

{% for category, items in by_category.items() %}### {{ category }}

{% for tender in items %}- **{{ tender.project }}**（{{ tender.buyer or "未披露" }}，{{ amount_label(tender) }}，截止 {{ tender.deadline or "未披露" }}，{{ tender.priority }}）
  - 来源：{{ tender.source_id or tender.source_url or "—" }}
{% endfor %}
{% endfor %}

## 三、中标/候选人（投标参考）

| 项目 | 采购人 | 中标方 | 金额（万元） | 日期 | 分类 | 来源 |
|---|---|---|---|---|---|---|
{% for tender in awards %}| {{ tender.project }} | {{ tender.buyer or "未披露" }} | {{ tender.winner or "待核实" }} | {{ amount_label(tender) }} | {{ tender.publish_date or "未披露" }} | {{ tender.category }} | {{ tender.source_id or tender.source_url or "—" }} |
{% endfor %}
{% if not awards %}| — | — | — | — | — | — | — |
{% endif %}

## 四、截止提醒

| 截止日 | 项目 | 采购人 | 预算/中标（万元） | 剩余天数 |
|---|---|---|---|---:|
{% for tender in deadlines %}| {{ tender.deadline }} | {{ tender.project }} | {{ tender.buyer or "未披露" }} | {{ amount_label(tender) }} | {{ days_left(tender) }} |
{% endfor %}
{% if not deadlines %}| — | 本期无截止日期信息 | — | — | — |
{% endif %}

## 五、台账更新

- 新增 {{ added }} 条，更新 {{ updated }} 条，台账共 {{ ledger_count }} 条。
- 台账文件：`{{ report.ledger_path or "ESG招标跟踪台账.md" }}`

## 六、信息缺口

{% if report.gaps %}{% for gap in report.gaps %}- {{ gap }}
{% endfor %}{% else %}- 未发现额外缺口；仍建议以官方原文复核金额与截止日期。
{% endif %}

## 附录 来源清单

| 编号 | 标题 | 站点 | URL |
|---|---|---|---|
{% for source in sources %}| {{ source.sid }} | {{ source.title }} | {{ source.site or "未披露" }} | {{ source.url }} |
{% endfor %}

## 免责声明

本日报基于公开信息整理，不构成投标承诺或投资建议；金额、截止日期、资格条件以官方公告原文为准。
"""


def _fmt_amount(value: float | None) -> str:
    if value is None:
        return "未披露"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def amount_label(tender: Tender) -> str:
    if tender.award is not None:
        return _fmt_amount(tender.award)
    if tender.budget is not None:
        return f"预算 {_fmt_amount(tender.budget)}"
    if tender.ceiling is not None:
        return f"上限 {_fmt_amount(tender.ceiling)}"
    return "未披露"


def days_left(tender: Tender, today: date) -> str:
    if tender.deadline is None:
        return "—"
    delta = (tender.deadline - today).days
    if delta < 0:
        return "已截止"
    return str(delta)


def _environment() -> Environment:
    env = Environment(autoescape=False, trim_blocks=False, lstrip_blocks=True)
    env.globals["amount_label"] = amount_label
    return env


def render_review(report: ReviewReport, stats: dict[str, object], top_by_category: dict[str, list[Tender]]) -> str:
    env = _environment()
    template = env.from_string(REVIEW_TEMPLATE)
    markdown = template.render(
        report=report,
        stats=stats,
        top_by_category=top_by_category,
        period_label=f"{report.period_start.year}年{report.period_start.month}月—{report.period_end.year}年{report.period_end.month}月",
    )
    return re.sub(r"\n{3,}", "\n\n", markdown).lstrip()


def render_daily(
    report: DailyReport,
    *,
    added: int,
    updated: int,
    ledger_count: int,
    sources: list,
) -> str:
    tenders = sorted(report.tenders, key=lambda t: (t.priority, t.deadline or date.max))
    must_see = [t for t in tenders if t.priority in {"P0", "P1"}]
    awards = [t for t in tenders + report.reference_tenders if t.status in {TenderStatus.awarded, TenderStatus.candidate}]
    deadlines = sorted([t for t in tenders if t.deadline], key=lambda t: t.deadline)  # type: ignore[arg-type]
    by_category: dict[str, list[Tender]] = defaultdict(list)
    for tender in tenders:
        by_category[tender.category or "其他"].append(tender)
    env = _environment()
    env.globals["days_left"] = lambda tender: days_left(tender, report.report_date)
    template = env.from_string(DAILY_TEMPLATE)
    markdown = template.render(
        report=report,
        tenders=tenders,
        high_priority=[t for t in tenders if t.priority in {"P0", "P1"}],
        must_see=must_see,
        awards=awards,
        deadlines=deadlines,
        by_category=dict(by_category),
        sources=sources,
        added=added,
        updated=updated,
        ledger_count=ledger_count,
    )
    return re.sub(r"\n{3,}", "\n\n", markdown).lstrip()
