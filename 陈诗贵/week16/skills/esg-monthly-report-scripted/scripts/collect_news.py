"""ESG 月报数据采集：真实联网搜索 → DeepSeek 抽取 → 确定性过滤校验。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from deepseek_client import chat_json
from web_search import fetch_text, search

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = SKILL_ROOT / "output"

CATEGORIES = {"policy", "rating", "industry", "best_practice", "company", "peer"}
DIMENSIONS = {"E", "S", "G"}

EXTRACT_SYSTEM = """你是严格的 ESG 信息抽取器，只能依据用户给出的搜索素材工作：
1. 不得补充、推测或改写事实；素材中没有的信息一律填 null 或空字符串。
2. date 必须是素材中明确出现的日期（输出 YYYY-MM-DD），找不到就填 null，禁止猜测。
3. category 只能是 policy / rating / industry / best_practice / company / peer 之一。
4. dimension 只能是 E / S / G 之一。
5. summary 用 1-2 句概括素材原文；impact 只写素材可推导的、对目标企业的影响，否则留空。
6. 与 ESG 无关的素材 relevant=false。
只输出 JSON，格式：{"items": [{"index": 1, "relevant": true, "title": "", "date": null, "category": "policy", "dimension": "E", "company": null, "summary": "", "impact": "", "source": ""}]}"""

EDITORIAL_SYSTEM = """你是 ESG 月报编辑。只能使用用户提供的已确认条目，禁止引入任何新事实、新数字或新事件。
输出 JSON：{"summary": ["3-5 条要点"], "advice": {"E": ["建议"], "S": ["建议"], "G": ["建议"]}, "gaps": ["信息缺口"]}
要求：summary 每条一句话并标引用编号 [n]；advice 每条必须对应至少一个条目编号 [n]；信息不足时写入 gaps，不要编造。"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ESG 月报数据采集（真实联网搜索 + DeepSeek 抽取）")
    parser.add_argument("--as-of", dest="as_of", default=None, help="报告截止日 YYYY-MM-DD，默认今天")
    parser.add_argument("--days", type=int, default=30, help="报告周期天数（含截止日），默认 30")
    parser.add_argument("--company", default="中国神华", help="客户公司")
    parser.add_argument("--industry", default="煤炭", help="客户所属行业")
    parser.add_argument("--top-per-query", type=int, default=6, help="每个检索词保留的搜索结果数")
    parser.add_argument("--fetch-top", type=int, default=2, help="每个检索词抓取正文的页面数")
    parser.add_argument("--max-sources", type=int, default=40, help="全局素材上限")
    parser.add_argument("--backend", default="auto", choices=["auto", "360", "bing", "duckduckgo"])
    parser.add_argument(
        "--freshness", default="month", choices=["day", "week", "month", "year", "none"],
        help="搜索引擎时间过滤（默认 month），none 表示不过滤",
    )
    parser.add_argument("--no-editorial", action="store_true", help="跳过摘要与建议生成")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args(argv)


def parse_date(text: str | None) -> dt.date | None:
    if not text:
        return None
    match = re.fullmatch(r"\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s*", text)
    if not match:
        return None
    try:
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def date_candidates(value: dt.date) -> set[str]:
    return {
        value.isoformat(),
        f"{value.year}年{value.month}月{value.day}日",
        f"{value.year}/{value.month}/{value.day}",
        f"{value.year}.{value.month}.{value.day}",
        f"{value.year}-{value.month}-{value.day}",
        f"{value.year}年{value.month}月{value.day}",
    }


def build_queries(as_of: dt.date, company: str, industry: str) -> list[str]:
    year, month = as_of.year, as_of.month
    return [
        f"ESG 政策 {year}年{month}月",
        "ESG 政策 最新 site:gov.cn",
        f"双碳 政策 {year}年{month}月 发布",
        f"ESG 评级 标准 更新 {year}",
        f"{industry} ESG {year}年{month}月",
        f"{industry} ESG 最佳实践 案例 {year}",
        f"{company} ESG {year}",
        f"{company} 可持续发展 报告 {year}",
        f"绿电 交易 碳市场 {year}年{month}月",
        f"CCUS 甲烷 减排 {year}年{month}月",
        f"交易所 可持续发展报告 指引 {year}",
    ]


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def normalize_text(text: str) -> str:
    table = str.maketrans("０１２３４５６７８９．，", "0123456789.,")
    return re.sub(r"[\s，,。.;；:：]", "", text.translate(table))


def same_title(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"[^一-鿿A-Za-z0-9]", "", s)  # noqa: E731
    return bool(norm(a)) and norm(a) == norm(b)


def normalize_record(raw: dict, src: dict, as_of: dt.date, start: dt.date) -> tuple[dict | None, str]:
    """把 LLM 输出与素材合并，返回 (记录, 状态)。状态: ok/out_of_window/date_unknown/irrelevant/invalid。"""
    if not isinstance(raw, dict) or raw.get("relevant") is False:
        return None, "irrelevant"

    title = (raw.get("title") or src["title"]).strip()
    if not title:
        return None, "invalid"

    text = f"{src['title']} {src['snippet']} {src['text']}"
    raw_date = parse_date(raw.get("date"))
    date_value = None
    date_unverified = False
    warnings: list[str] = []
    if raw_date:
        if any(candidate in text for candidate in date_candidates(raw_date)):
            date_value = raw_date
        else:
            date_unverified = True
            warnings.append(f"日期 {raw_date} 未在素材中找到，已忽略")

    category = raw.get("category")
    if category not in CATEGORIES:
        warnings.append(f"非法分类 {category!r}，归入 industry")
        category = "industry"
    dimension = raw.get("dimension")
    if dimension not in DIMENSIONS:
        warnings.append(f"非法维度 {dimension!r}，置空")
        dimension = None

    record = {
        "title": title,
        "date": date_value.isoformat() if date_value else None,
        "category": category,
        "dimension": dimension,
        "company": raw.get("company") or None,
        "summary": (raw.get("summary") or "").strip(),
        "impact": (raw.get("impact") or "").strip(),
        "source": (raw.get("source") or "").strip() or domain_of(src["url"]),
        "url": src["url"],
        "text_source": "page" if src["text"] else "snippet",
        "queries": src["queries"],
        "warnings": warnings,
    }
    if date_unverified:
        return record, "date_unknown"
    if date_value is None:
        return record, "date_unknown"
    if date_value < start or date_value > as_of:
        return record, "out_of_window"
    return record, "ok"


def chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    as_of = parse_date(args.as_of) if args.as_of else dt.date.today()
    if as_of is None:
        raise SystemExit("--as-of 必须是 YYYY-MM-DD")
    start = as_of - dt.timedelta(days=args.days - 1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    queries = build_queries(as_of, args.company, args.industry)
    print(f"[1/4] 检索词 {len(queries)} 条，报告周期 {start} ~ {as_of}")

    # ---- 搜索：按 URL 去重，记录来源查询 ----
    sources: list[dict] = []
    seen_urls: set[str] = set()
    query_stats: dict[str, int] = {}
    for query in queries:
        results = search(
            query,
            limit=args.top_per_query,
            backend=args.backend,
            freshness=None if args.freshness == "none" else args.freshness,
        )
        query_stats[query] = len(results)
        for result in results:
            if result["url"] in seen_urls or len(sources) >= args.max_sources:
                continue
            seen_urls.add(result["url"])
            sources.append({**result, "text": "", "queries": [query]})
        print(f"      搜索：{query} → {len(results)} 条")
    print(f"[2/4] 去重后素材 {len(sources)} 条")

    # ---- 抓正文：每个检索词只抓前 fetch-top 条的新页面 ----
    fetched = 0
    per_query_fetched: dict[str, int] = {}
    for src in sources:
        query = src["queries"][0]
        if per_query_fetched.get(query, 0) >= args.fetch_top:
            continue
        src["text"] = fetch_text(src["url"])
        per_query_fetched[query] = per_query_fetched.get(query, 0) + 1
        fetched += 1 if src["text"] else 0
    if not sources:
        raise SystemExit("搜索未返回任何结果：请检查网络或更换检索词后重试（不会生成空报告）。")
    print(f"[3/4] 抓取正文 {fetched} 篇")

    # ---- DeepSeek 抽取（分批，附完整素材以便校验） ----
    items: list[dict] = []
    out_of_window: list[dict] = []
    date_unknown: list[dict] = []
    warnings: list[str] = []
    irrelevant = 0
    invalid = 0
    batch_size = 6
    for batch in chunks(sources, batch_size):
        payload = [
            {
                "index": src_index,
                "query": src["queries"][0],
                "search_title": src["title"],
                "url": src["url"],
                "snippet": src["snippet"],
                "page_text": src["text"][:2500],
            }
            for src_index, src in enumerate(batch, start=1)
        ]
        user = (
            f"目标公司：{args.company}；所属行业：{args.industry}；报告周期：{start} 至 {as_of}。\n"
            f"素材：{json.dumps(payload, ensure_ascii=False)}"
        )
        data = chat_json(EXTRACT_SYSTEM, user)
        raw_items = data.get("items", []) if isinstance(data, dict) else data
        by_index = {
            item.get("index"): item
            for item in raw_items
            if isinstance(item, dict) and isinstance(item.get("index"), int)
        }
        for position, src in enumerate(batch, start=1):
            raw = by_index.get(position)
            if raw is None and position - 1 < len(raw_items):
                raw = raw_items[position - 1]
            if raw is None:
                invalid += 1
                continue
            record, status = normalize_record(raw, src, as_of, start)
            if status == "irrelevant":
                irrelevant += 1
            elif status == "invalid":
                invalid += 1
            elif status == "ok":
                items.append(record)
            elif status == "out_of_window":
                out_of_window.append(record)
            else:
                date_unknown.append(record)

    # ---- 标题去重（确定性） ----
    unique: list[dict] = []
    duplicates: list[dict] = []
    for record in items:
        duplicate = next((u for u in unique if same_title(u["title"], record["title"])), None)
        if duplicate:
            duplicates.append({**record, "duplicate_of": duplicate["title"]})
        else:
            unique.append(record)
    items = unique
    items.sort(key=lambda r: (r["date"] or "", r["category"]))
    print(
        f"[4/4] 抽取完成：窗口内 {len(items)} 条，窗口外 {len(out_of_window)}，"
        f"日期未知 {len(date_unknown)}，无关 {irrelevant}，无效 {invalid}，重复 {len(duplicates)}"
    )

    # ---- LLM 编辑：摘要 / 建议 / 缺口（只基于已确认条目） ----
    editorial: dict = {"summary": [], "advice": {"E": [], "S": [], "G": []}, "gaps": []}
    if items and not args.no_editorial:
        listing = [
            {
                "index": i,
                "date": r["date"],
                "title": r["title"],
                "category": r["category"],
                "dimension": r["dimension"],
                "summary": r["summary"],
                "impact": r["impact"],
                "source": r["source"],
                "company": r["company"],
            }
            for i, r in enumerate(items, start=1)
        ]
        user = (
            f"目标公司：{args.company}；行业：{args.industry}；周期：{start} 至 {as_of}。\n"
            f"已确认条目：{json.dumps(listing, ensure_ascii=False)}\n"
            f"窗口外条目 {len(out_of_window)} 条、日期未知 {len(date_unknown)} 条，请写入 gaps。"
        )
        data = chat_json(EDITORIAL_SYSTEM, user)
        if isinstance(data, dict):
            editorial.update({key: data.get(key, editorial[key]) for key in editorial})
        # 校验建议中的引用编号是否存在
        max_index = len(items)
        for dimension, advice_list in editorial.get("advice", {}).items():
            if not isinstance(advice_list, list):
                continue
            for advice in advice_list:
                for ref in re.findall(r"\[(\d+)\]", str(advice)):
                    if not 1 <= int(ref) <= max_index:
                        warnings.append(f"建议引用了不存在的条目 [{ref}]：{advice}")

    collected = {
        "meta": {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "as_of": as_of.isoformat(),
            "window_start": start.isoformat(),
            "window_days": args.days,
            "company": args.company,
            "industry": args.industry,
            "queries": query_stats,
            "stats": {
                "sources": len(sources),
                "fetched_pages": fetched,
                "in_window": len(items),
                "out_of_window": len(out_of_window),
                "date_unknown": len(date_unknown),
                "irrelevant": irrelevant,
                "invalid": invalid,
                "duplicates": len(duplicates),
            },
        },
        "items": items,
        "out_of_window": out_of_window,
        "date_unknown": date_unknown,
        "duplicates": duplicates,
        "warnings": warnings,
        "editorial": editorial,
    }
    out_file = out_dir / "collected.json"
    out_file.write_text(json.dumps(collected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"输出：{out_file}")
    print(f"下一步：python scripts/render_report.py --collected \"{out_file}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
