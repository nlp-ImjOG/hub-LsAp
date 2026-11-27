#!/usr/bin/env python3
"""Plan searches, optionally call Brave Search, and collect public HTML/text evidence."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

TOPICS = {
    "ESG披露与管理": ["ESG", "可持续发展报告"],
    "碳盘查与核查": ["碳盘查", "碳核查"],
    "产品碳足迹": ["碳足迹", "生命周期评价"],
    "双碳规划与转型": ["双碳", "零碳园区"],
    "碳资产与市场": ["碳资产", "CCER"],
    "绿色金融与供应链": ["绿色金融", "绿色供应链"],
    "能碳数字化": ["碳管理平台", "ESG数据系统"],
    "相关技术工程设备": ["碳排放监测设备", "低碳改造"],
}
MAX_BYTES = 4 * 1024 * 1024


def stamp():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iso_date(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("日期须为 YYYY-MM-DD")
    return parsed


def canonical_url(url):
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("仅支持无内嵌凭据的 HTTP(S) 公告链接")
    # Preserve all query parameters: some procurement platforms use signed URLs.
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def plan_searches(start, end, mode, buyer="", sites=()):
    first, last = iso_date(start), iso_date(end)
    if first > last:
        raise ValueError("开始日期不能晚于结束日期")
    periods = []
    cursor = first
    while cursor <= last:
        month = ((cursor.month - 1) // 3 + 1) * 3 + 1
        next_quarter = date(cursor.year + (month > 12), 1 if month > 12 else month, 1)
        stop = min(last, next_quarter - timedelta(days=1)) if mode == "history" else last
        periods.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    stages = ["中标", "成交"] if mode == "history" else ["采购公告", "招标公告", "更正 延期 终止", "采购意向"]
    queries = []
    for start_date, end_date in periods:
        for topic, keywords in TOPICS.items():
            for i, keyword in enumerate(keywords):
                for stage in (stages[i % 2:i % 2 + 1] if mode == "history" else stages):
                    for site in (sites or [""]):
                        if site and not re.fullmatch(r"[A-Za-z0-9.-]+", site):
                            raise ValueError("--site 仅填写域名")
                        query = " ".join(x for x in [buyer, keyword, stage, f"site:{site}" if site else ""] if x)
                        item = {"topic": topic, "query": query, "start": str(start_date), "end": str(end_date)}
                        item["query_id"] = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:16]
                        queries.append(item)
    return {"mode": mode, "start": start, "end": end, "queries": queries,
            "note": "起始检索矩阵，须按原文筛选日期，并继续同义词、地区、采购人及公告阶段补搜；不是已执行日志。"}


def request_bytes(url, headers=None):
    request = Request(url, headers={"User-Agent": "ESG-Bidding-Research/1.0", **(headers or {})})
    with urlopen(request, timeout=25) as response:
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("页面超过4MiB，转用附件/浏览工具")
        return data, response.headers, response.geturl()


def search(plan, api_key, start_index=0, limit=8, pages=1):
    if not api_key:
        raise ValueError("未配置 BRAVE_SEARCH_API_KEY；请用内置联网工具执行 plan 中的查询，再按参考文档保存结果。")
    if not (1 <= pages <= 10 and limit > 0 and start_index >= 0):
        raise ValueError("pages须为1–10，limit须为正整数，start-index不可为负")
    queries = plan["queries"]
    selected = queries[start_index:start_index + limit]
    if not selected:
        raise ValueError("当前批次没有查询；检查 start-index 和查询计划")
    results, log, seen = [], [], {}
    stop_batch = False
    for item in selected:
        for page in range(pages):
            if log:
                time.sleep(1.1)
            params = {"q": item["query"], "count": 20, "offset": page, "text_decorations": "false",
                      "freshness": item["start"] + "to" + item["end"]}
            entry = {**item, "page": page, "attempted_at": stamp(), "provider": "brave"}
            try:
                data, _, _ = request_bytes("https://api.search.brave.com/res/v1/web/search?" + urlencode(params),
                                            {"Accept": "application/json", "X-Subscription-Token": api_key})
                body = json.loads(data)
                if body.get("type") != "search":
                    raise ValueError("搜索服务返回非search响应")
                hits = body.get("web", {}).get("results", [])
                for hit in hits:
                    url = canonical_url(hit["url"])
                    if url in seen:
                        if item["query_id"] not in seen[url]["query_ids"]:
                            seen[url]["query_ids"].append(item["query_id"])
                        continue
                    record = {"title": unescape(hit.get("title", "")), "url": url,
                              "snippet": unescape(hit.get("description", "")),
                              "query_ids": [item["query_id"]], "verification": "unverified"}
                    seen[url] = record
                    results.append(record)
                more = bool(body.get("query", {}).get("more_results_available", False))
                entry.update(status="ok", hits=len(hits), more_results_available=more,
                             page_cap_reached=more and page == pages - 1)
                log.append(entry)
                if not more:
                    break
            except (HTTPError, URLError, ValueError, KeyError, TypeError, OSError) as error:
                # Do not log response bodies or headers: they may contain credentials.
                code = getattr(error, "code", None)
                entry.update(status="error", error=type(error).__name__, http_status=code)
                log.append(entry)
                stop_batch = code in {401, 403, 429}
                break
        if stop_batch:
            break
    attempted = {x["query_id"] for x in log}
    return {"provider": "brave", "results": results, "search_log": log,
            "planned_queries": len(queries), "attempted_queries": len(attempted),
            "remaining_query_ids": [x["query_id"] for x in queries if x["query_id"] not in attempted],
            "partial": any(x["status"] == "error" or x.get("page_cap_reached") for x in log)
                       or len(attempted) < len(queries)}


class PageText(HTMLParser):
    """Readable blocks, not a semantic article extractor; evidence still needs review."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden += 1
        if not self.hidden and tag in {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "td", "th"}:
            self.parts.append("\n" if tag not in {"td", "th"} else " | ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"p", "div", "tr", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def text(self):
        return "\n".join(line for line in (re.sub(r"[\t \r]+", " ", x).strip() for x in "".join(self.parts).splitlines()) if line)


def fetch_one(item, output_dir):
    url = canonical_url(item["url"])
    result = {"url": url, "title": item.get("title", ""), "fetched_at": stamp(), "verification": "unverified"}
    try:
        body, headers, final_url = request_bytes(url)
        result["final_url"] = final_url
        content_type = headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml", "text/plain"} or body.startswith(b"%PDF"):
            result.update(status="needs_document_reader", content_type=content_type)
            return result
        charset = headers.get_content_charset()
        if not charset:
            match = re.search(br'charset\s*=\s*["\x27]?([\w-]+)', body[:4096], re.I)
            charset = match.group(1).decode("ascii") if match else "utf-8"
        try:
            decoded = body.decode(charset)
        except (UnicodeDecodeError, LookupError):
            decoded = body.decode("gb18030")
        if content_type == "text/plain":
            content = decoded
        else:
            parser = PageText()
            parser.feed(decoded)
            content = parser.text()
        basename = hashlib.sha256(url.encode()).hexdigest()[:20] + ".txt"
        target = Path(output_dir) / basename
        target.parent.mkdir(parents=True, exist_ok=True)
        numbered = "\n".join(f"L{i}: {line}" for i, line in enumerate(content.splitlines(), 1))
        target.write_text(numbered, encoding="utf-8")
        result.update(status="extracted_needs_review", text_path=str(target.resolve()),
                      characters=len(content), content_sha256=hashlib.sha256(body).hexdigest(),
                      reader_warning="可能含导航、验证码或登录提示；提取成功不等于已核验正文。")
    except (HTTPError, URLError, ValueError, OSError) as error:
        result.update(status="error", error=type(error).__name__, http_status=getattr(error, "code", None))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--start", required=True)
    plan.add_argument("--end", required=True)
    plan.add_argument("--mode", choices=["history", "daily"], default="history")
    plan.add_argument("--buyer", default="")
    plan.add_argument("--site", action="append", default=[])
    plan.add_argument("--output", required=True)
    search_parser = commands.add_parser("search")
    search_parser.add_argument("plan")
    search_parser.add_argument("--start-index", type=int, default=0)
    search_parser.add_argument("--limit", type=int, default=8)
    search_parser.add_argument("--pages", type=int, default=1)
    search_parser.add_argument("--output", required=True)
    fetch_parser = commands.add_parser("fetch")
    fetch_parser.add_argument("results", help='JSON object with a "results" array of {url,title}')
    fetch_parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = plan_searches(args.start, args.end, args.mode, args.buyer, args.site)
            save_json(args.output, result)
            print(f"已生成 {len(result['queries'])} 条计划查询；尚未联网执行。")
        elif args.command == "search":
            result = search(read_json(args.plan), os.environ.get("BRAVE_SEARCH_API_KEY"), args.start_index, args.limit, args.pages)
            save_json(args.output, result)
            print(f"取得 {len(result['results'])} 个线索；partial={result['partial']}。")
            if any(x["status"] == "error" for x in result["search_log"]):
                return 2
        else:
            candidates = read_json(args.results)["results"]
            seen, records = set(), []
            for item in candidates:
                url = canonical_url(item["url"])
                if url in seen:
                    continue
                seen.add(url)
                if records:
                    time.sleep(0.3)
                records.append(fetch_one(item, args.output_dir))
            save_json(Path(args.output_dir) / "sources.json", records)
            print(f"已处理 {len(records)} 个链接；请核对 sources.json 的逐项状态。")
            if any(x["status"] != "extracted_needs_review" for x in records):
                return 2
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
