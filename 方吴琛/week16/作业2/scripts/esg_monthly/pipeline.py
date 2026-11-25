"""ESG 月报生成流水线(高代码版)。

流程:生成查询 → 检索 → 去重 → 抓取正文 → 总结 → 套模板 → 落盘。
全程记录指标(查询数/结果数/抓取数/耗时),供对比实验使用。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from common import CONFIG, SearchResult, search, fetch_text, summarize_text, dedup, credibility
from .queries import MonthlyParams, all_queries


@dataclass
class PipelineMetrics:
    queries: int = 0
    raw_results: int = 0
    dedup_results: int = 0
    fetched: int = 0
    fetch_failed: int = 0
    elapsed_sec: float = 0.0
    blocks: dict[str, dict] = field(default_factory=dict)


def _gather_block(queries: list[str], metrics: PipelineMetrics) -> tuple[list[SearchResult], list[dict]]:
    """检索+去重+抓取一个板块。返回(去重结果, [{result, text, summary}])。"""
    raw: list[SearchResult] = []
    for q in queries:
        metrics.queries += 1
        raw.extend(search(q))
    metrics.raw_results += len(raw)
    uniq = dedup(raw)
    metrics.dedup_results += len(uniq)

    items: list[dict] = []
    # 每板块最多抓取 6 篇,平衡覆盖度与耗时
    for r in uniq[:6]:
        text = fetch_text(r.url)
        if text:
            metrics.fetched += 1
            items.append({"result": r, "text": text})
        else:
            metrics.fetch_failed += 1
            items.append({"result": r, "text": ""})
    return uniq, items


def run(params: MonthlyParams, out_dir: str | Path = "examples") -> tuple[str, PipelineMetrics]:
    start = time.time()
    metrics = PipelineMetrics()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocks_q = all_queries(params)
    report_parts: list[str] = []
    sources: list[str] = []

    header = (
        f"# {params.client} ESG 月报 · {params.year_month or datetime.now().strftime('%Y-%m')}\n\n"
        f"> 行业:{params.industry} ｜ 对标:{params.benchmark}\n"
        f"> 生成方式:高代码脚本流水线(ddgs 检索 + trafilatura 抽取 + "
        f"{'LLM 总结' if CONFIG.llm_enabled else '抽取式总结'})\n"
        f"> 生成时间:{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n---\n\n"
    )

    block_titles = {
        "板块一 政策/评级/标准": "## 1. ESG 政策、评级、标准动态",
        "板块二 行业动态": "## 2. 行业 ESG 动态与最佳实践",
        "板块三 客户与对标": "## 3. 客户公司 ESG 分析与对标",
    }

    for bname, queries in blocks_q.items():
        uniq, items = _gather_block(queries, metrics)
        b_start = time.time()
        summaries: list[str] = []
        for it in items:
            r: SearchResult = it["result"]
            focus = "ESG 政策/评级/标准" if "政策" in bname else ("行业 ESG 动态" if "行业" in bname else f"{params.client} ESG 影响")
            s = summarize_text(it["text"], focus=focus) if it["text"] else f"(正文抓取失败,仅有摘要片段){r.snippet}"
            summaries.append(f"### {r.title}\n来源可信度:{credibility(r.url)} ｜ [{r.url}]({r.url})\n\n{s}\n")
            sources.append(f"- [{r.title}]({r.url}) — 可信度 {credibility(r.url)}")
        block_md = f"{block_titles[bname]}\n\n" + "\n".join(summaries) + "\n"
        report_parts.append(block_md)
        metrics.blocks[bname] = {
            "queries": len(queries),
            "unique_results": len(uniq),
            "fetched": len([i for i in items if i["text"]]),
            "elapsed_sec": round(time.time() - b_start, 2),
        }

    footer = (
        "## 4. 附录:信息来源\n\n" + "\n".join(sources) + "\n\n---\n\n"
        f"## 流水线指标\n\n"
        f"- 查询数:{metrics.queries}\n- 原始结果:{metrics.raw_results}\n"
        f"- 去重后:{metrics.dedup_results}\n- 成功抓取:{metrics.fetched}\n"
        f"- 抓取失败:{metrics.fetch_failed}\n"
    )
    metrics.elapsed_sec = round(time.time() - start, 2)

    md = header + "\n".join(report_parts) + footer
    fname = out_dir / f"ESG月报_{params.client}_{params.year_month or datetime.now().strftime('%Y-%m')}.md"
    fname.write_text(md, "utf-8")
    return str(fname), metrics
