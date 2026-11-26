"""Markdown 组装：把结构化条目渲染成月报。"""

from __future__ import annotations

import re

from jinja2 import Environment

from .models import Category, Item, ReportData, Source

TEMPLATE = """{% macro item_block(item, idx) -%}
**{{ idx }}. {{ item.title }}**
- 事实：{{ item.fact }}
- 影响：**{{ item.impact_level }}**。{{ item.impact }}
- 建议：{{ item.recommendation }}
- 来源：{{ item.source_ids|map('source_ref')|join('') }}

{% endmacro %}
# {{ report.client }} ESG 月报（{{ period_label }}）

> 报告期：{{ report.period_start }} 至 {{ report.period_end }} ｜ 编制日期：{{ report.generated_at }} ｜ 来源数：{{ report.sources|length }} ｜ 条目数：{{ report.items|length }}{% if report.offline %} ｜ **离线样例（固定 fixture）**{% endif %}

## 一页纸速览

{% if report.summary %}{% for line in report.summary %}- {{ line }}
{% endfor %}{% else %}- 本月未生成速览，请检查 LLM 输出或使用 `--offline`。
{% endif %}

## 一、ESG 政策、评级与标准动态

### 1.1 国内政策与监管

{% if policy_cn %}{% for item in policy_cn %}{{ item_block(item, loop.index) }}{% endfor %}{% else %}本月未检索到重大国内政策动态。{% endif %}

### 1.2 国际框架与标准

{% if policy_intl %}{% for item in policy_intl %}{{ item_block(item, loop.index) }}{% endfor %}{% else %}本月未检索到重大国际标准动态。{% endif %}

### 1.3 评级与指数

{% if policy_rating %}{% for item in policy_rating %}{{ item_block(item, loop.index) }}{% endfor %}{% else %}本月未检索到评级机构对客户的直接评级变动；评级不是每月更新，最新结果见附录 A。{% endif %}

### 1.4 影响研判

| 事项 | 影响维度 | 程度 | 建议动作 | 来源 |
|---|---|---|---|---|
{% if policy %}{% for item in policy %}| {{ item.title }} | {{ item.subcategory }} | {{ item.impact_level }} | {{ item.recommendation }} | {{ item.source_ids|map('source_ref')|join('') }} |
{% endfor %}{% else %}| 本月未检索到重大政策事项 | — | — | — | — |
{% endif %}

## 二、行业动态与最佳实践

### 2.1 行业政策与市场

{% if industry_market %}{% for item in industry_market %}{{ item_block(item, loop.index) }}{% endfor %}{% else %}本月未检索到重大行业动态。{% endif %}

### 2.2 同业最佳实践

{% if best_practice %}{% for item in best_practice %}{{ item_block(item, loop.index) }}{% endfor %}{% else %}本月未检索到可提炼的同业最佳实践。{% endif %}

### 2.3 风险与机遇矩阵

| 维度 | 风险 | 机遇 |
|---|---|---|
{% for row in risk_rows %}| {{ row.dimension }} | {{ row.risk }} | {{ row.opportunity }} |
{% endfor %}

## 三、公司动态与对标分析

### 3.1 {{ report.client }}动态及 ESG 影响

{% if company_main %}{% for item in company_main %}{{ item_block(item, loop.index) }}{% endfor %}{% else %}本月未检索到客户公司重大动态。{% endif %}

### 3.2 对标企业关键 ESG 行动

| 对标企业 | 关键行动 | ESG 维度 | 对客户的启示 | 来源 |
|---|---|---|---|---|
{% if benchmark %}{% for item in benchmark %}| {{ item.title }} | {{ item.fact }} | {{ item.subcategory }} | {{ item.recommendation }} | {{ item.source_ids|map('source_ref')|join('') }} |
{% endfor %}{% else %}| 本月未检索到对标企业行动 | — | — | — | — |
{% endif %}

### 3.3 下月行动建议

**短期（1 个月内）**
{% if report.executive.short_actions %}{% for action in report.executive.short_actions %}- {{ action }}
{% endfor %}{% else %}- 梳理本月高影响事项的责任部门与时间表。
{% endif %}

**中期（1–3 个月）**
{% if report.executive.mid_actions %}{% for action in report.executive.mid_actions %}- {{ action }}
{% endfor %}{% else %}- 将 ESG 指标纳入年度预算与绩效考核。
{% endif %}

**长期（3–12 个月）**
{% if report.executive.long_actions %}{% for action in report.executive.long_actions %}- {{ action }}
{% endfor %}{% else %}- 完善 ESG 数据与披露体系。
{% endif %}

### 3.4 报告期后事项

{% if after_items %}{% for item in after_items %}{{ item_block(item, loop.index) }}{% endfor %}{% else %}本月未检索到需要单列的报告期后事项。{% endif %}

## 附录 A 信息来源清单

| 编号 | 标题 | 发布机构 | 发布日期 | URL | 可信度 |
|---|---|---|---|---|---|
{% for source in report.sources %}| {{ source.sid }} | {{ source.title }} | {{ source.site or "未披露" }} | {{ source.published_at or "未披露" }} | {{ source.url }} | {{ authority_label(source) }} |
{% endfor %}

## 附录 B 检索说明与信息缺口

**检索查询（{{ report.query_log|length }} 条）：**

| 查询 | 类别 | 结果数 | 状态 |
|---|---|---|---|
{% for row in report.query_log %}| {{ row.query }} | {{ row.category }} | {{ row.results }} | {{ row.status }} |
{% endfor %}

**信息缺口 / 质量提示：**

{% if report.gaps %}{% for gap in report.gaps %}- {{ gap }}
{% endfor %}{% else %}- 未发现额外缺口；仍建议以官方原文复核关键数字。
{% endif %}

## 免责声明

本报告基于公开信息整理，不构成投资建议；标注"未披露/待核实"的内容请以官方原文为准。报告中的影响判断与建议为研究分析，不构成客户决策的唯一依据。
"""


def source_ref(sid: str) -> str:
    return f"[{sid}]"


def authority_label(source: Source) -> str:
    return {3: "官方/公司", 2: "媒体", 1: "聚合"}.get(source.authority, "媒体")


def _trim_summary(summary: list[str], max_chars: int = 300) -> list[str]:
    kept: list[str] = []
    total = 0
    for line in summary:
        if total + len(line) > max_chars and kept:
            break
        kept.append(line)
        total += len(line)
    return kept


def _default_risk_rows() -> list[dict[str, str]]:
    return [
        {"dimension": "环境", "risk": "碳价、甲烷与碳足迹披露压力", "opportunity": "瓦斯利用、CCUS、绿电"},
        {"dimension": "社会", "risk": "深部开采与外包队伍安全合规", "opportunity": "智能矿山、安全培训"},
        {"dimension": "治理", "risk": "关联交易与披露完整性", "opportunity": "内控升级、ESG 数据中台"},
        {"dimension": "市场", "risk": "煤价波动、CBAM 与供应链要求", "opportunity": "煤电联营、转型金融"},
    ]


def render(report: ReportData) -> str:
    policy = [item for item in report.items if item.category == Category.policy]
    industry = [item for item in report.items if item.category == Category.industry]
    company = [item for item in report.items if item.category == Category.company]
    benchmark = [item for item in report.items if item.category == Category.benchmark]

    policy_cn = [i for i in policy if "国际" not in i.subcategory and "评级" not in i.subcategory]
    policy_intl = [i for i in policy if "国际" in i.subcategory]
    policy_rating = [i for i in policy if "评级" in i.subcategory]

    industry_market = [
        i for i in industry if i.subcategory != "最佳实践" and i.period_tag != "报告期后"
    ]
    industry_best = [i for i in industry if i.subcategory == "最佳实践"]
    benchmark_best = [i for i in benchmark if "警示" not in i.subcategory]
    best_practice = industry_best or benchmark_best or benchmark

    company_main = [i for i in company if i.period_tag != "报告期后"]
    after_items = [i for i in report.items if i.period_tag == "报告期后"]

    report.summary = _trim_summary(report.summary)
    risk_rows = report.executive.risk_opportunities or _default_risk_rows()

    env = Environment(autoescape=False, trim_blocks=False, lstrip_blocks=True)
    env.filters["source_ref"] = source_ref
    env.globals["authority_label"] = authority_label
    template = env.from_string(TEMPLATE)
    markdown = template.render(
        report=report,
        period_label=f"{report.period_start.year}年{report.period_start.month}月",
        policy=policy,
        policy_cn=policy_cn,
        policy_intl=policy_intl,
        policy_rating=policy_rating,
        industry_market=industry_market,
        best_practice=best_practice,
        company_main=company_main,
        benchmark=benchmark,
        after_items=after_items,
        risk_rows=risk_rows,
    )
    return re.sub(r"\n{3,}", "\n\n", markdown).lstrip()
