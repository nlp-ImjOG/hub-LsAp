"""案例2 —— ESG 投标信息汇总编排脚本（高代码实现）。

两种模式：
  history —— 汇总过去 N 年 ESG/可持续发展/双碳 相关中标信息，做热点与金额分布分析；
  daily   —— 监控当天新增招标/中标信息，去重后推送（企业微信/钉钉 webhook）并落盘。

用法：
  python esg_bid_monitor.py --mode history --years 2 --out ../作业1/案例2-ESG投标/output
  python esg_bid_monitor.py --mode daily --push --out ../作业1/案例2-ESG投标/output
  python esg_bid_monitor.py --demo --mode history --out ../作业1/案例2-ESG投标/output
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

import requests

try:
    from . import config, web_search, llm_summarize, report_writer, demo_data
except ImportError:  # 直接 `python esg_bid_monitor.py` 运行时
    import config  # type: ignore
    import web_search  # type: ignore
    import llm_summarize  # type: ignore
    import report_writer  # type: ignore
    import demo_data  # type: ignore

BID_QUERIES = [
    "ESG 中标公告",
    "可持续发展报告 编制 咨询 中标",
    "双碳 碳达峰 碳中和 方案 中标",
    "碳核查 碳盘查 中标",
    "碳足迹 CBAM 咨询 中标",
    "ESG评级 提升 咨询 中标",
    "碳管理 平台 建设 中标",
    "绿色工厂 绿色供应链 认证 中标",
    "CCER 碳资产 开发 中标",
    "ESG 数据平台 中标",
]

DAILY_QUERIES = [
    "ESG 招标 公告 最新",
    "可持续发展 招标 今日",
    "双碳 招标 公告 最新",
]


# ---- 金额解析 --------------------------------------------------------------

_AMOUNT_RE = re.compile(r"([0-9][0-9,\.]*)\s*(亿元|万元|元|万)")


def parse_amount(text: str) -> float | None:
    """从文本解析金额，统一换算为「万元」。"""
    m = _AMOUNT_RE.search(text or "")
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    unit = m.group(2)
    if unit == "亿元":
        return val * 10000
    if unit == "元":
        return val / 10000
    return val  # 万元 / 万


def normalize_bid(it: dict) -> dict | None:
    title = (it.get("title") or "").strip()
    if not title:
        return None
    amount = parse_amount(it.get("amount", "") or it.get("snippet", "") or "")
    return {
        "title": title,
        "buyer": (it.get("buyer") or it.get("source") or "未知").strip(),
        "amount": amount,
        "date": (it.get("date") or "").strip(),
        "category": (it.get("category") or "").strip(),
        "url": (it.get("url") or "").strip(),
    }


# ---- 数据获取 --------------------------------------------------------------

def fetch_records(*, demo: bool, daily: bool, years: int = 2) -> list[dict]:
    if demo:
        source = demo_data.DAILY_RECORDS if daily else demo_data.BID_RECORDS
        records = [normalize_bid(b) for b in source]
        return [r for r in records if r]

    queries = DAILY_QUERIES if daily else BID_QUERIES
    raw: list[web_search.SearchResult] = []
    for q in queries:
        raw.extend(web_search.search(q, num=8))

    if not raw:
        return []

    docs = [{"title": r.title, "url": r.url, "snippet": r.snippet, "date": r.date} for r in raw]
    try:
        items = llm_summarize.summarize_documents(
            docs,
            "ESG/可持续发展/双碳 相关中标信息，抽取标题、采购方、中标金额、日期、类别",
            fields=["title", "buyer", "amount", "date", "category", "url"],
        )
    except Exception as exc:
        print(f"[bid] LLM 抽取失败：{exc}")
        return []

    out = []
    for it in items:
        rec = normalize_bid(it)
        if rec:
            out.append(rec)

    # 按时间窗过滤（history：近 N 年）
    if not daily:
        cutoff = date.today() - timedelta(days=365 * years)
        out = [r for r in out if not r["date"] or r["date"] >= cutoff.isoformat()]
    return llm_summarize.dedupe(out)


# ---- 聚合分析 --------------------------------------------------------------

def _half(date_str: str) -> str:
    """把 'YYYY-MM-DD' 归到 'YYYYH1' / 'YYYYH2'，缺省返回 '未知'。"""
    if not date_str or len(date_str) < 7:
        return "未知"
    year, month = date_str[:4], date_str[5:7]
    if not (year.isdigit() and month.isdigit()):
        return "未知"
    return year + ("H1" if month <= "06" else "H2")


def aggregate(records: list[dict]) -> dict:
    by_cat: dict[str, list[float]] = defaultdict(list)
    by_buyer: dict[str, list[float]] = defaultdict(list)
    by_half: dict[str, list[float]] = defaultdict(list)
    amounts = [r["amount"] for r in records if r["amount"] is not None]

    for r in records:
        if r["amount"] is not None:
            by_cat[r["category"] or "未分类"].append(r["amount"])
            by_buyer[r["buyer"] or "未知"].append(r["amount"])
        half = _half(r["date"] or "")
        if half != "未知":
            by_half[half].append(r["amount"] if r["amount"] is not None else 0)

    buckets = {"<20万": 0, "20–50万": 0, "50–100万": 0, "100–300万": 0, ">300万": 0}
    for a in amounts:
        if a < 20:
            buckets["<20万"] += 1
        elif a < 50:
            buckets["20–50万"] += 1
        elif a < 100:
            buckets["50–100万"] += 1
        elif a <= 300:
            buckets["100–300万"] += 1
        else:
            buckets[">300万"] += 1

    def _rows(d: dict[str, list[float]]) -> list[list[str]]:
        items = [(k, len(v), sum(v)) for k, v in d.items()]
        items.sort(key=lambda x: -x[2])
        return [[k, str(n), f"{s:,.1f}"] for k, n, s in items]

    return {
        "total": len(records),
        "total_amount": sum(amounts),
        "avg_amount": (sum(amounts) / len(amounts)) if amounts else 0.0,
        "by_cat": _rows(by_cat),
        "by_buyer": _rows(by_buyer),
        "by_half": sorted(_rows(by_half), key=lambda r: r[0]),
        "buckets": [[k, str(v)] for k, v in buckets.items()],
    }


# ---- 报告 / 推送 -----------------------------------------------------------

def build_history_report(records: list[dict], agg: dict, years: int) -> str:
    md = report_writer.h(1, f"ESG / 可持续发展 / 双碳 中标信息汇总（近 {years} 年）")
    md += report_writer.banner(f"生成时间：{report_writer.stamp()} ｜ 样本数：{agg['total']}")
    md += report_writer.h(2, "总体概览")
    md += report_writer.bullet(
        [
            f"累计收录中标信息 {agg['total']} 条。",
            f"中标金额合计 {agg['total_amount']:,.1f} 万元，单笔均值 {agg['avg_amount']:,.1f} 万元。",
        ]
    )
    md += report_writer.h(2, "热点招标方向（按中标金额排序）")
    md += report_writer.table(["类别", "项目数", "中标金额（万元）"], agg["by_cat"])
    md += report_writer.h(2, "中标金额分布")
    md += report_writer.table(["金额区间", "项目数"], agg["buckets"])
    md += report_writer.h(2, "采购方分布")
    md += report_writer.table(["采购方", "项目数", "中标金额（万元）"], agg["by_buyer"])
    md += report_writer.h(2, "时间分布（半年维度）")
    md += report_writer.table(["时段", "项目数", "中标金额（万元）"], agg["by_half"])
    md += report_writer.h(2, "明细（金额从高到低）")
    ordered = sorted(records, key=lambda r: -(r["amount"] or 0))
    rows = [
        [r["title"][:60], r["date"] or "—", f"{r['amount']:,.1f}" if r["amount"] else "—", r["category"] or "—"]
        for r in ordered[:30]
    ]
    md += report_writer.table(["项目", "日期", "中标金额（万元）", "类别"], rows)
    return md


def build_daily_report(records: list[dict]) -> str:
    md = report_writer.h(1, "ESG 招标 / 中标每日推送")
    md += report_writer.banner(f"推送时间：{report_writer.stamp()} ｜ 新增 {len(records)} 条")
    if not records:
        md += "> 今日暂无新增 ESG 相关招标 / 中标信息。\n"
        return md
    rows = [[r["title"][:60], r["date"] or "—", r["category"] or "—", r["buyer"]] for r in records]
    md += report_writer.table(["项目", "日期", "类别", "采购方"], rows)
    return md


def load_seen(path: str) -> set[str]:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_seen(path: str, seen: set[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def push(records: list[dict]) -> None:
    """推送新增信息到企业微信 / 钉钉机器人（未配置则打印到控制台）。"""
    s = config.get_settings()
    text = "ESG 招标速报\n" + "\n".join(
        f"- {r['title'][:50]}" + (f"（{r['amount']:,.0f}万）" if r["amount"] else "") for r in records
    )
    hooks = [("wecom", s.wecom_webhook), ("dingtalk", s.dingtalk_webhook)]
    sent = False
    for name, hook in hooks:
        if not hook:
            continue
        payload = {"msgtype": "text", "text": {"content": text}} if name == "wecom" else {
            "msgtype": "text", "text": {"content": text}
        }
        try:
            requests.post(hook, json=payload, timeout=10)
            sent = True
        except Exception as exc:
            print(f"[bid] {name} 推送失败：{exc}")
    if not sent:
        print(f"[bid] 未配置推送 webhook，控制台输出如下：\n{text}")


def main() -> int:
    p = argparse.ArgumentParser(description="ESG 投标信息汇总（高代码确定性脚本）")
    p.add_argument("--mode", choices=["history", "daily"], default="history")
    p.add_argument("--years", type=int, default=2)
    p.add_argument("--out", default="output")
    p.add_argument("--demo", action="store_true", help="离线演示：用内置数据")
    p.add_argument("--push", action="store_true", help="daily 模式下推送新增信息")
    args = p.parse_args()

    records = fetch_records(demo=args.demo, daily=(args.mode == "daily"), years=args.years)

    if args.mode == "history":
        agg = aggregate(records)
        report = build_history_report(records, agg, args.years)
        fname = f"ESG中标信息汇总_{date.today().strftime('%Y-%m-%d')}.md"
    else:
        seen_path = os.path.join(args.out, "seen_bids.json")
        seen = load_seen(seen_path)
        new_records = [r for r in records if r["title"] not in seen]
        for r in new_records:
            seen.add(r["title"])
        save_seen(seen_path, seen)
        report = build_daily_report(new_records)
        fname = f"每日招标推送_{date.today().strftime('%Y-%m-%d')}.md"
        if args.push and new_records:
            push(new_records)

    path = report_writer.save(os.path.join(args.out, fname), report)
    print(f"[bid] 报告已生成：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
