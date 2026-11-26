"""ESG 月报确定性渲染：固定模板 + 完整性检查，不调用 LLM。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = SKILL_ROOT / "output"

CATEGORY_LABELS = {
    "policy": "监管政策",
    "rating": "评级与标准",
    "industry": "行业动态",
    "best_practice": "最佳实践",
    "company": "公司动态",
    "peer": "对标企业",
}
DIMENSION_LABELS = {"E": "环境", "S": "社会", "G": "治理"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ESG 月报确定性渲染")
    parser.add_argument("--collected", default=str(DEFAULT_OUT_DIR / "collected.json"))
    parser.add_argument("--out", default=None, help="输出文件，默认 output/ESG月报_<as_of>.md")
    return parser.parse_args(argv)


def cell(text: str | None) -> str:
    return (text or "").replace("|", "／").replace("\n", " ").strip()


def render_item(record: dict, with_impact: bool = True) -> str:
    dimension = f" `{record['dimension']}`" if record.get("dimension") else ""
    lines = [f"- **{record.get('date') or '日期待核实'}｜{record['title']}**{dimension}"]
    if record.get("summary"):
        lines.append(f"  - 事实：{record['summary']}")
    if with_impact and record.get("impact"):
        lines.append(f"  - 影响：{record['impact']}")
    if record.get("url"):
        lines.append(f"  - 来源：{record.get('source') or '未注明'}（[{record['url']}]({record['url']})）")
    else:
        lines.append(f"  - 来源：{record.get('source') or '未注明'}")
    return "\n".join(lines)


def render_section(title: str, records: list[dict], empty_note: str) -> str:
    body = "\n\n".join(render_item(r) for r in records) if records else f"本期未采集到{empty_note}。"
    return f"## {title}\n\n{body}"


def build_report(collected: dict, out_path: Path) -> tuple[str, list[tuple[bool, str]]]:
    meta = collected["meta"]
    items = collected.get("items", [])
    editorial = collected.get("editorial") or {}
    company = meta.get("company", "客户公司")
    start, end = meta["window_start"], meta["as_of"]
    month_label = f"{int(end[5:7])}月" if len(end) >= 7 else ""
    title = f"{company} ESG 月报（{end[:4]}年{month_label}）"

    groups: dict[str, list[dict]] = {key: [] for key in CATEGORY_LABELS}
    for record in items:
        groups.setdefault(record.get("category", "industry"), []).append(record)

    summary = editorial.get("summary") or []
    if not isinstance(summary, list):
        summary = [str(summary)]
    if not summary:
        summary = [
            f"本期共采集窗口内公开信息 {len(items)} 条：政策与标准 {len(groups['policy']) + len(groups['rating'])} 条，"
            f"行业与最佳实践 {len(groups['industry']) + len(groups['best_practice'])} 条，"
            f"公司动态 {len(groups['company'])} 条，对标企业 {len(groups['peer'])} 条。"
        ]

    parts: list[str] = []
    parts.append(f"# {title}\n")
    parts.append(
        f"> 报告周期：{start} — {end}　|　生成日期：{dt.date.today().isoformat()}　|　"
        f"数据来源：公开互联网检索（360 / Bing / DuckDuckGo）　|　信息性质：公开信息汇总，不构成投资建议\n"
    )

    parts.append("## 一、本期摘要\n")
    parts.append("\n".join(f"- {line}" for line in summary))

    policy_block = "\n\n".join(
        f"### 2.{i} {CATEGORY_LABELS[key]}\n\n"
        + ("\n\n".join(render_item(r) for r in groups[key]) if groups[key] else f"本期未采集到{CATEGORY_LABELS[key]}。")
        for i, key in enumerate(("policy", "rating"), start=1)
    )
    parts.append(f"## 二、ESG 政策与标准动态\n\n{policy_block}")

    industry_block = "\n\n".join(
        f"### 3.{i} {CATEGORY_LABELS[key]}\n\n"
        + ("\n\n".join(render_item(r) for r in groups[key]) if groups[key] else f"本期未采集到{CATEGORY_LABELS[key]}。")
        for i, key in enumerate(("industry", "best_practice"), start=1)
    )
    parts.append(f"## 三、行业新闻与最佳实践\n\n{industry_block}")

    parts.append(render_section("四、客户公司动态与 ESG 影响", groups["company"], "公司相关动态"))

    peer_rows = [
        f"| {cell(r.get('company') or '未注明')} | {cell(r['title'])} | {cell(r.get('date') or '待核实')} | "
        f"{cell(r.get('impact') or r.get('summary'))} | {cell(r.get('source'))} |"
        for r in groups["peer"]
    ]
    peer_body = (
        "| 对标企业 | 关键行动 | 日期 | 对客户的启示 | 来源 |\n|---|---|---|---|---|\n" + "\n".join(peer_rows)
        if peer_rows
        else "本期未采集到对标企业关键行动。"
    )
    parts.append(f"## 五、对标企业 ESG 关键行动\n\n{peer_body}")

    advice = editorial.get("advice") or {}
    if not isinstance(advice, dict):
        advice = {}
    advice_blocks = []
    for dimension in ("E", "S", "G"):
        lines = advice.get(dimension) or []
        content = "\n".join(f"- {line}" for line in lines) if lines else "本期无相关建议。"
        advice_blocks.append(f"### 6.{'ESG'.index(dimension) + 1} {DIMENSION_LABELS[dimension]}（{dimension}）\n\n{content}")
    parts.append("## 六、ESG 建议\n\n" + "\n\n".join(advice_blocks))

    gaps_value = editorial.get("gaps") or []
    if not isinstance(gaps_value, list):
        gaps_value = [str(gaps_value)]
    gaps = [f"- {gap}" for gap in gaps_value]
    for record in collected.get("date_unknown", []):
        gaps.append(f"- 日期待核实：{record['title']}（{record.get('url') or '无链接'}）")
    for warning in collected.get("warnings", []):
        gaps.append(f"- 数据校验提示：{warning}")
    if not gaps:
        gaps = ["- 本期未发现明显信息缺口。"]
    parts.append("## 七、风险与信息缺口\n\n" + "\n".join(gaps))

    appendix_rows = [
        f"| {i} | {cell(r.get('date') or '待核实')} | {cell(r['title'])} | "
        f"{CATEGORY_LABELS.get(r.get('category'), '其他')} | {r.get('dimension') or '-'} | {cell(r.get('source'))} |"
        for i, r in enumerate(items, start=1)
    ]
    appendix = (
        "| # | 日期 | 标题 | 分类 | 维度 | 来源 |\n|---|---|---|---|---|---|\n" + "\n".join(appendix_rows)
        if appendix_rows
        else "| # | 日期 | 标题 | 分类 | 维度 | 来源 |\n|---|---|---|---|---|---|\n| - | - | 本期无入选项 | - | - | - |"
    )
    parts.append(f"## 附录：信息清单\n\n{appendix}")
    parts.append(
        f"\n---\n\n数据口径：检索结果 {meta['stats']['sources']} 条，正文抓取 {meta['stats']['fetched_pages']} 篇，"
        f"窗口外 {meta['stats']['out_of_window']} 条，日期未知 {meta['stats']['date_unknown']} 条，"
        f"去重 {meta['stats']['duplicates']} 条，无关 {meta['stats']['irrelevant']} 条。"
    )

    checks: list[tuple[bool, str]] = [
        (len(items) > 0, f"窗口内条目数 = {len(items)}"),
        (all(r.get("date") for r in items), "所有入选项均有可核实日期"),
        (all(r.get("source") for r in items), "所有入选项均有来源"),
        (all(r.get("title") for r in items), "所有入选项均有标题"),
        (len(appendix_rows) == len(items), f"附录条目数（{len(appendix_rows)}）与正文一致（{len(items)}）"),
        (bool(groups["policy"]) or bool(groups["rating"]), "政策与标准章节非空"),
        (bool(groups["industry"]) or bool(groups["best_practice"]), "行业章节非空"),
    ]
    markdown = "\n\n".join(parts) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    return markdown, checks


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    collected_path = Path(args.collected)
    if not collected_path.is_file():
        raise SystemExit(f"找不到采集结果：{collected_path}，请先运行 collect_news.py")
    collected = json.loads(collected_path.read_text(encoding="utf-8"))
    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"ESG月报_{collected['meta']['as_of']}.md"

    _, checks = build_report(collected, out_path)
    print(f"报告已生成：{out_path}")
    print("质量检查：")
    for ok, label in checks:
        print(f"  [{'✓' if ok else '✗'}] {label}")
    failed = [label for ok, label in checks if not ok]
    if failed:
        print(f"注意：{len(failed)} 项检查未通过，报告已保留，请人工复核。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
