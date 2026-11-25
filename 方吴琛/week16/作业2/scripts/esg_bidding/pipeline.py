"""ESG 投标信息汇总流水线(高代码版)。

汇总模式:查询矩阵 → 检索 → 抓取 → 字段抽取 → 去重 → 统计 → 报告。
监控模式:同上但限定近 24h,并与已推送清单比对去重。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from common import search, fetch_text, dedup, credibility, SearchResult
from .extract import parse_record, BidRecord, CATEGORIES
from .stats import compute, render_table, Stats


CORE_KEYWORDS = [
    "ESG", "可持续发展", "双碳", "碳中和", "碳达峰", "绿色金融", "绿色债券",
    "碳核查", "碳足迹", "碳资产", "温室气体", "节能", "环保", "绿色工厂",
    "清洁生产", "新能源", "储能", "环境监测", "生态修复", "生物多样性", "气候风险",
]
BID_VERBS = ["中标", "招标", "采购"]
REGIONS = ["", "北京", "上海", "广东", "浙江", "江苏"]  # 空=全国


@dataclass
class BiddingMetrics:
    queries: int = 0
    raw_results: int = 0
    dedup_results: int = 0
    fetched: int = 0
    records: int = 0
    with_amount: int = 0
    elapsed_sec: float = 0.0


def _build_queries(mode: str, region_filter: str | None) -> list[str]:
    qs: list[str] = []
    year = datetime.now().year
    regions = [region_filter] if region_filter else REGIONS
    time_word = "今日" if mode == "monitor" else f"{year-1} {year} 中标"
    for kw in CORE_KEYWORDS:
        for verb in BID_VERBS:
            for reg in regions:
                q = f"{kw} {verb}"
                if reg:
                    q = f"{reg} {q}"
                if mode == "monitor":
                    q = f"{q} 今日"
                else:
                    q = f"{q} {year-1}"
                qs.append(q)
    # 去重查询词
    return list(dict.fromkeys(qs))


def _to_records(results: list[SearchResult], metrics: BiddingMetrics) -> list[BidRecord]:
    recs: list[BidRecord] = []
    for r in results[:30]:  # 控制抓取规模
        text = fetch_text(r.url)
        if text:
            metrics.fetched += 1
        cred = credibility(r.url)
        rec = parse_record(r.title, r.url, r.snippet, text, cred)
        recs.append(rec)
        metrics.records += 1
        if rec.amount_wan:
            metrics.with_amount += 1
    return recs


def aggregate(out_dir: str | Path = "examples", region: str | None = None,
              max_queries: int | None = None) -> tuple[str, BiddingMetrics, Stats]:
    start = time.time()
    metrics = BiddingMetrics()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    queries = _build_queries("aggregate", region)
    if max_queries:
        queries = queries[:max_queries]

    raw: list[SearchResult] = []
    for q in queries:
        metrics.queries += 1
        raw.extend(search(q))
    metrics.raw_results = len(raw)
    uniq = dedup([r for r in raw if any(k in r.title + r.snippet for k in CORE_KEYWORDS)])
    metrics.dedup_results = len(uniq)

    records = _to_records(uniq, metrics)
    stats = compute(records)
    metrics.elapsed_sec = round(time.time() - start, 2)

    md = _render_aggregate_report(records, stats, metrics, region)
    fname = out_dir / f"ESG招投标汇总_{datetime.now().strftime('%Y%m%d')}.md"
    fname.write_text(md, "utf-8")
    # 同时落盘结构化清单
    (out_dir / "项目清单.json").write_text(
        json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2), "utf-8"
    )
    return str(fname), metrics, stats


def monitor(out_dir: str | Path = "examples", push_log: str | Path = "已推送招标.json") -> tuple[str, BiddingMetrics]:
    start = time.time()
    metrics = BiddingMetrics()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    push_log = Path(push_log)

    queries = _build_queries("monitor", None)[:40]
    raw: list[SearchResult] = []
    for q in queries:
        metrics.queries += 1
        raw.extend(search(q))
    metrics.raw_results = len(raw)

    # 按"今日"相关性再过滤(标题/snippet 命中核心词)
    uniq = dedup([r for r in raw if any(k in r.title + r.snippet for k in CORE_KEYWORDS)])
    metrics.dedup_results = len(uniq)

    # 与已推送去重
    pushed: set[str] = set()
    if push_log.exists():
        pushed = {x["url"] for x in json.loads(push_log.read_text("utf-8"))}
    new = [r for r in uniq if r.url not in pushed]
    metrics.fetched = len(new)

    records = _to_records(new, metrics)
    metrics.elapsed_sec = round(time.time() - start, 2)

    md = _render_daily_push(records, metrics)
    fname = out_dir / f"每日ESG招标推送_{datetime.now().strftime('%Y-%m-%d')}.md"
    fname.write_text(md, "utf-8")

    # 更新已推送
    pushed.update(r.url for r in new)
    push_log.write_text(json.dumps([{"url": u} for u in pushed], ensure_ascii=False), "utf-8")
    return str(fname), metrics


def _render_aggregate_report(records: list[BidRecord], stats: Stats, metrics: BiddingMetrics, region) -> str:
    cat_rows = "\n".join(f"| {k} | {v} | {round(v/stats.total*100,1) if stats.total else 0}% |"
                         for k, v in sorted(stats.by_category.items(), key=lambda x: -x[1]))
    bin_rows = "\n".join(f"| {k} | {v} | {round(v/stats.with_amount*100,1) if stats.with_amount else 0}% |"
                         for k, v in stats.by_amount_bin.items())
    top_rows = "\n".join(f"| {i+1} | {t['title'][:30]} | {t['winner'][:15]} | {t['amount_wan']} | [链接]({t['url']}) |"
                         for i, t in enumerate(stats.top10_by_amount))
    return f"""# ESG 相关招投标汇总分析报告

> 数据区间:近 2 年 ｜ 地域:{region or '全国'} ｜ 生成:{datetime.now().strftime('%Y-%m-%d')}
> 生成方式:高代码脚本流水线

## 1. 概要
- 样本:{stats.total} 条(去重后),其中披露金额 {stats.with_amount} 条
- 总中标金额:约 {round(stats.total_amount_wan/10000, 2)} 亿元
- 平均/中位数:{stats.avg_amount_wan} / {stats.median_amount_wan} 万元

## 2. 数据说明
- 来源:ddgs 检索(覆盖政府/商业平台公开页)
- 筛选:核心关键词命中 + 招标/中标/采购动词
- 局限:DuckDuckGo 对中文招标平台覆盖有限,金额披露率受限于公告页;生产环境建议接 ccgp/cebpubservice 专用抓取

## 3. 按项目类型分布
| 类型 | 数量 | 占比 |
|---|---|---|
{cat_rows}

## 4. 中标金额分布
| 金额区间(万元) | 项目数 | 占比 |
|---|---|---|
{bin_rows}

## 5. TOP 10 大项目
| # | 项目名称 | 中标单位 | 金额(万元) | 来源 |
|---|---|---|---|---|
{top_rows}

## 6. 按来源可信度分布
{stats.by_cred}

## 7. 项目明细
{render_table(records[:30])}

## 流水线指标
查询 {metrics.queries} ｜ 原始 {metrics.raw_results} ｜ 去重 {metrics.dedup_results} ｜ 抓取 {metrics.fetched} ｜ 耗时 {metrics.elapsed_sec}s
"""


def _render_daily_push(records: list[BidRecord], metrics: BiddingMetrics) -> str:
    today = datetime.now().strftime('%Y-%m-%d')
    table = render_table(records[:20]) if records else "| (今日无新增) | | | | | | | | |"
    highlights = "\n".join(
        f"- **{r.title[:40]}**:{r.snippet[:80]}… 金额 {'有' if r.amount_wan else '待核实'}"
        for r in records[:3]
    ) or "(暂无)"
    return f"""# 每日 ESG 招标推送 · {today}

> 新增条数:{len(records)} ｜ 生成方式:高代码脚本流水线(监控模式)

## 重点关注
{highlights}

## 今日新增项目
{table}

## 流水线指标
查询 {metrics.queries} ｜ 原始 {metrics.raw_results} ｜ 去重后新增 {metrics.dedup_results} ｜ 耗时 {metrics.elapsed_sec}s
"""
