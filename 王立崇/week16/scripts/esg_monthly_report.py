"""案例1 —— ESG 月报编排脚本（高代码实现：搜索 → 抓取 → 筛选 → 结构化摘要 → 成稿）。

用法：
  # 离线演示（无网络 / 无 Key，用内置演示数据跑通全流程）
  python esg_monthly_report.py --demo --out ../作业1/案例1-ESG月报/output

  # 真实联网（需配置搜索后端 + LLM Key）
  python esg_monthly_report.py --company 中国神华 --days 30 --out ../作业1/案例1-ESG月报/output
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta

try:
    from . import config, web_search, web_fetch, llm_summarize, report_writer, demo_data
except ImportError:  # 直接 `python esg_monthly_report.py` 运行时
    import config  # type: ignore
    import web_search  # type: ignore
    import web_fetch  # type: ignore
    import llm_summarize  # type: ignore
    import report_writer  # type: ignore
    import demo_data  # type: ignore

DEFAULTS = {
    "company": "中国神华",
    "industry": "煤炭 / 煤电一体化能源",
    "benchmarks": ["兖矿能源", "陕西煤业", "中煤能源", "国家能源集团"],
}


def build_queries(company: str, industry: str, benchmarks: list[str], days: int) -> dict[str, list[str]]:
    window = f"近{days}天" if days else "最新"
    return {
        "政策标准": [
            f"ESG 政策 标准 最新 {window}",
            f"可持续发展报告 披露 指引 交易所 {window}",
            f"碳市场 双碳 政策 {window}",
            f"ESG 评级 标准 ISSB 最新 {window}",
        ],
        "行业动态": [
            f"{industry} ESG 双碳 新闻 {window}",
            f"{industry} 最佳实践 绿色转型 智能矿山 {window}",
        ],
        "客户公司": [
            f"{company} ESG 可持续发展 {window}",
            f"{company} 双碳 新能源 CCUS 绿色矿山 {window}",
            f"{company} ESG 评级 MSCI 华证 万得 {window}",
        ],
        "对标企业": [
            f"{b} ESG 双碳 行动 {window}" for b in benchmarks
        ],
    }


def _docs_from_results(results: list[web_search.SearchResult]) -> list[dict[str, str]]:
    docs = []
    for r in results:
        docs.append({"title": r.title, "url": r.url, "snippet": r.snippet, "date": r.date})
    return docs


def _rule_summarize(items) -> list[dict[str, str]]:
    """离线兜底：不做 LLM 摘要，直接以标题+摘要作为条目。接受 SearchResult 或 dict。"""
    out = []
    for r in items:
        if isinstance(r, dict):
            out.append(
                {
                    "title": r.get("title", ""),
                    "source": r.get("source", ""),
                    "date": r.get("date", "") or "",
                    "summary": r.get("snippet", "") or "(无摘要)",
                    "esg_relevance": r.get("esg_relevance", ""),
                    "suggestion": r.get("suggestion", ""),
                }
            )
        else:  # SearchResult
            out.append(
                {
                    "title": r.title,
                    "source": r.source,
                    "date": r.date or "",
                    "summary": r.snippet or "(无摘要)",
                    "esg_relevance": "",
                    "suggestion": "",
                }
            )
    return out


def collect_section(
    queries: list[str],
    instruction: str,
    *,
    demo: bool = False,
    demo_results: list[dict[str, str]] | None = None,
    per_query: int = 5,
    fetch_body: bool = True,
) -> list[dict[str, str]]:
    """执行某个章节的检索与摘要。demo 模式直接使用内置演示数据，不联网。"""
    if demo:
        return _rule_summarize(demo_results or [])

    raw: list[web_search.SearchResult] = []
    for q in queries:
        raw.extend(web_search.search(q, num=per_query))
    if not raw:
        return []

    # 抓取正文，提升摘要质量（失败则仅用 snippet）
    docs = _docs_from_results(raw)
    for d in docs[:6]:
        try:
            d["text"] = web_fetch.fetch(d["url"], max_chars=2500)
        except Exception:
            pass

    try:
        items = llm_summarize.summarize_documents(docs, instruction)
        items = llm_summarize.dedupe(items)
        return [it for it in items if it.get("title")]
    except Exception as exc:  # LLM 不可用 / 解析失败 → 兜底
        print(f"[esg] LLM 摘要失败，退回规则模式：{exc}")
        return _rule_summarize(raw)


def render_section(title: str, items: list[dict[str, str]]) -> str:
    md = report_writer.h(2, title)
    if not items:
        md += "> 未检索到相关条目。\n"
        return md
    rows: list[list[str]] = []
    for it in items:
        rows.append(
            [
                it.get("title", ""),
                it.get("date", "") or "—",
                (it.get("summary", "") or "")[:120],
                (it.get("esg_relevance", "") or "")[:80],
                (it.get("suggestion", "") or "")[:80],
            ]
        )
    md += report_writer.table(
        ["动态 / 政策", "日期", "要点", "ESG 关联", "对客户建议"], rows
    )
    return md + "\n"


def build_report(
    company: str, industry: str, benchmarks: list[str], days: int, *, demo: bool
) -> str:
    queries = build_queries(company, industry, benchmarks, days)
    end = date.today()
    start = end - timedelta(days=days)

    sections: dict[str, list[dict[str, str]]] = {}
    for name, qs in queries.items():
        print(f"[esg] 检索章节：{name}")
        demo_results = demo_data.MONTHLY_SEARCH_RESULTS.get(name) if demo else None
        sections[name] = collect_section(
            qs, f"{company} {industry} {name}", demo=demo, demo_results=demo_results
        )

    md = report_writer.h(1, f"{company} ESG 月报（{end.strftime('%Y-%m')}）")
    md += report_writer.banner(
        f"统计区间：{start.isoformat()} ~ {end.isoformat()} ｜ 生成时间：{report_writer.stamp()}"
    )
    if demo:
        md += report_writer.banner(
            "⚠ 演示稿：检索结果来自内置演示数据，非实时联网；运行真实模式可自动刷新。"
        )

    total = sum(len(v) for v in sections.values())
    md += report_writer.h(2, "执行摘要")
    md += report_writer.bullet(
        [
            f"本期共聚合 {total} 条与 ESG/双碳 相关动态，覆盖政策标准、行业、公司与对标企业四类。",
            f"客户：{company}（{industry}），对标：{'、'.join(benchmarks)}。",
            "建议优先关注：强制可持续披露要求的落地节点、全国碳市场扩容带来的碳成本与披露义务、以及行业智能化/绿色化转型带来的评级与融资机会。",
        ]
    )

    md += render_section("一、ESG 政策 / 标准 / 评价动态", sections["政策标准"])
    md += render_section("二、行业新闻与最佳实践", sections["行业动态"])
    md += render_section("三、客户公司动态：ESG 影响与建议", sections["客户公司"])
    md += render_section("四、对标企业 ESG 关键行动", sections["对标企业"])

    md += report_writer.h(2, "五、风险提示与下一步行动建议")
    md += report_writer.bullet(
        [
            "披露合规：核对公司是否在交易所强制披露名单内，确保报告按期、按指引披露并鉴证。",
            "碳成本：跟踪全国碳市场扩容与碳价走势，评估对煤电资产盈利与排放强度的影响。",
            "转型风险：投资者与评级机构对煤炭资产的 ESG 折价，建议加大 CCUS、新能源、绿色矿山等可量化披露。",
            "对标追赶：对标企业的 ESG 评级与新能源占比变化，需按月跟踪并形成行动清单。",
        ]
    )
    return md


def main() -> int:
    p = argparse.ArgumentParser(description="ESG 月报生成（高代码确定性脚本）")
    p.add_argument("--company", default=DEFAULTS["company"])
    p.add_argument("--industry", default=DEFAULTS["industry"])
    p.add_argument("--benchmarks", default=",".join(DEFAULTS["benchmarks"]))
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--out", default="output")
    p.add_argument("--demo", action="store_true", help="离线演示：用内置数据，不联网、不调 LLM")
    args = p.parse_args()

    benchmarks = [b.strip() for b in args.benchmarks.split(",") if b.strip()]
    report = build_report(args.company, args.industry, benchmarks, args.days, demo=args.demo)

    fname = f"{args.company}ESG月报_{date.today().strftime('%Y-%m')}.md"
    path = os.path.join(args.out, fname)
    saved = report_writer.save(path, report)
    print(f"[esg] 报告已生成：{saved}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
