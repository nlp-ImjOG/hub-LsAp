"""ESG 投标信息采集：真实联网搜索 → DeepSeek 字段抽取 → 金额/日期证据校验。"""

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

INDUSTRIES = {
    "碳咨询/碳核查",
    "ESG咨询与报告",
    "绿电与新能源",
    "节能改造",
    "CCUS与甲烷减排",
    "碳交易与CCER",
    "其他",
}
NOTICE_TYPES = {"中标公告", "招标公告", "结果公示", "其他"}

EXTRACT_SYSTEM = """你是严格的招投标信息抽取器，只能依据用户给出的搜索素材工作：
1. 不得编造项目名称、采购人、中标单位、金额或日期；素材没有的信息填 null。
2. amount_raw 必须逐字取自素材（保留单位写法，如 "1.2亿元"、"3500万元"、"980万"、"2,460,000元"），找不到填 null。
3. publish_date 必须是素材中明确出现的日期，输出 YYYY-MM-DD，否则 null。
4. buyer（采购人）与 winner（中标单位）无法从素材确认时填 null，不要推测。
5. industry 只能取：碳咨询/碳核查、ESG咨询与报告、绿电与新能源、节能改造、CCUS与甲烷减排、碳交易与CCER、其他。
6. notice_type 只能取：中标公告、招标公告、结果公示、其他。
7. evidence 原样摘录素材中出现金额或日期的句子，用于人工核对。
8. 与 ESG、可持续发展、双碳无关的素材 relevant=false。
只输出 JSON：{"items": [{"index": 1, "relevant": true, "title": "", "publish_date": null, "buyer": null, "winner": null, "amount_raw": null, "industry": "其他", "region": null, "notice_type": "中标公告", "evidence": ""}]}"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ESG 投标信息采集（真实联网搜索 + DeepSeek 抽取）")
    parser.add_argument("--as-of", dest="as_of", default=None, help="统计截止日 YYYY-MM-DD，默认今天")
    parser.add_argument("--months", type=int, default=24, help="历史窗口月数，仅用于生成检索词与元数据")
    parser.add_argument("--top-per-query", type=int, default=6)
    parser.add_argument("--fetch-top", type=int, default=2)
    parser.add_argument("--max-sources", type=int, default=40)
    parser.add_argument("--backend", default="auto", choices=["auto", "360", "bing", "duckduckgo"])
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


def normalize_text(text: str) -> str:
    table = str.maketrans("０１２３４５６７８９．，", "0123456789.,")
    return re.sub(r"[\s，,。.;；:：、]", "", text.translate(table))


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def build_queries(as_of: dt.date, months: int) -> list[str]:
    start = as_of - dt.timedelta(days=months * 31)
    years = sorted({start.year, as_of.year})
    queries = []
    for year in years:
        queries.extend([f"ESG 中标结果 {year}", f"双碳 中标公告 {year}"])
    queries.extend(
        [
            "碳核查 中标 公告",
            "ESG报告 编制 中标 公告",
            "绿电 采购 中标 公告",
            "CCUS 项目 中标",
            "节能改造 中标 公告",
            "碳资产管理平台 中标",
            f"ESG 招标 {as_of.year}年{as_of.month}月",
            "可持续发展 咨询 中标 公告",
        ]
    )
    return queries


def chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def verify_record(raw: dict, src: dict, as_of: dt.date) -> tuple[dict | None, str]:
    if not isinstance(raw, dict) or raw.get("relevant") is False:
        return None, "irrelevant"

    title = (raw.get("title") or src["title"]).strip()
    if not title:
        return None, "invalid"

    text = normalize_text(f"{src['title']} {src['snippet']} {src['text']}")
    warnings: list[str] = []

    amount_raw = (raw.get("amount_raw") or "").strip() or None
    if amount_raw and normalize_text(amount_raw) not in text:
        warnings.append(f"金额 {amount_raw!r} 未在原文出现，已置空")
        amount_raw = None

    publish_date = parse_date(raw.get("publish_date"))
    date_unverified = False
    if publish_date and not any(c in f"{src['title']} {src['snippet']} {src['text']}" for c in date_candidates(publish_date)):
        date_unverified = True
        warnings.append(f"日期 {publish_date} 未在原文找到")

    industry = raw.get("industry")
    if industry not in INDUSTRIES:
        warnings.append(f"非法方向 {industry!r}，归入其他")
        industry = "其他"
    notice_type = raw.get("notice_type")
    if notice_type not in NOTICE_TYPES:
        notice_type = "其他"

    record = {
        "title": title,
        "publish_date": publish_date.isoformat() if publish_date else None,
        "date_unverified": date_unverified,
        "buyer": (raw.get("buyer") or "").strip() or None,
        "winner": (raw.get("winner") or "").strip() or None,
        "amount_raw": amount_raw,
        "industry": industry,
        "region": (raw.get("region") or "").strip() or None,
        "notice_type": notice_type,
        "evidence": (raw.get("evidence") or "").strip(),
        "source": domain_of(src["url"]),
        "url": src["url"],
        "text_source": "page" if src["text"] else "snippet",
        "queries": src["queries"],
        "warnings": warnings,
    }
    return record, "ok"


def record_key(record: dict) -> tuple[str, str, str]:
    title = re.sub(r"[^一-鿿A-Za-z0-9]", "", record["title"])
    return (record.get("publish_date") or "", title, record.get("buyer") or "")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    as_of = parse_date(args.as_of) if args.as_of else dt.date.today()
    if as_of is None:
        raise SystemExit("--as-of 必须是 YYYY-MM-DD")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    queries = build_queries(as_of, args.months)
    print(f"[1/4] 检索词 {len(queries)} 条，截止日 {as_of}，历史窗口 {args.months} 个月")

    sources: list[dict] = []
    seen_urls: set[str] = set()
    query_stats: dict[str, int] = {}
    for query in queries:
        results = search(query, limit=args.top_per_query, backend=args.backend)
        query_stats[query] = len(results)
        for result in results:
            if result["url"] in seen_urls or len(sources) >= args.max_sources:
                continue
            seen_urls.add(result["url"])
            sources.append({**result, "text": "", "queries": [query]})
        print(f"      搜索：{query} → {len(results)} 条")
    if not sources:
        raise SystemExit("搜索未返回任何结果：请检查网络或更换检索词后重试（不会生成假数据）。")
    print(f"[2/4] 去重后素材 {len(sources)} 条")

    fetched = 0
    per_query_fetched: dict[str, int] = {}
    for src in sources:
        query = src["queries"][0]
        if per_query_fetched.get(query, 0) >= args.fetch_top:
            continue
        src["text"] = fetch_text(src["url"])
        per_query_fetched[query] = per_query_fetched.get(query, 0) + 1
        fetched += 1 if src["text"] else 0
    print(f"[3/4] 抓取正文 {fetched} 篇")

    items: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()
    duplicate_count = 0
    rejected_count = 0
    invalid_count = 0
    warnings: list[str] = []

    for batch in chunks(sources, 6):
        payload = [
            {
                "index": index,
                "query": src["queries"][0],
                "search_title": src["title"],
                "url": src["url"],
                "snippet": src["snippet"],
                "page_text": src["text"][:2500],
            }
            for index, src in enumerate(batch, start=1)
        ]
        data = chat_json(
            EXTRACT_SYSTEM,
            f"统计截止日：{as_of}。素材：{json.dumps(payload, ensure_ascii=False)}",
        )
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
                invalid_count += 1
                continue
            record, status = verify_record(raw, src, as_of)
            if status == "irrelevant":
                rejected_count += 1
                continue
            if status == "invalid" or record is None:
                invalid_count += 1
                continue
            key = record_key(record)
            if key in seen_keys:
                duplicate_count += 1
                continue
            seen_keys.add(key)
            items.append(record)
            for warning in record.get("warnings", []):
                warnings.append(f"{record['title']}：{warning}")

    items.sort(key=lambda r: (r.get("publish_date") or "", r["title"]))
    print(
        f"[4/4] 抽取完成：保留 {len(items)} 条，重复 {duplicate_count}，"
        f"无关 {rejected_count}，无效 {invalid_count}"
    )
    missing_amount = sum(1 for r in items if not r.get("amount_raw"))
    missing_date = sum(1 for r in items if not r.get("publish_date"))
    unverified_date = sum(1 for r in items if r.get("date_unverified"))
    print(f"      金额缺失 {missing_amount} 条，日期缺失 {missing_date} 条，日期未核实 {unverified_date} 条")

    output = {
        "meta": {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "as_of": as_of.isoformat(),
            "window_months": args.months,
            "queries": query_stats,
            "stats": {
                "sources": len(sources),
                "fetched_pages": fetched,
                "kept": len(items),
                "duplicates": duplicate_count,
                "irrelevant": rejected_count,
                "invalid": invalid_count,
                "missing_amount": missing_amount,
                "missing_date": missing_date,
                "date_unverified": unverified_date,
            },
        },
        "items": items,
        "warnings": warnings,
    }
    out_file = out_dir / "bids_raw.json"
    out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"输出：{out_file}")
    print(
        "下一步：python scripts/analyze_bids.py --as-of "
        f"{as_of}　或　python scripts/render_daily.py --date {as_of}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
