"""DeepSeek Search API 适配器。

接口地址来自作业 README：https://api.deepseek.com/v1/tools/search
请求字段与响应字段以 DeepSeek 官方文档为准；本文件对常见响应形状做了兼容映射，
真实字段差异只需要改 ``normalize_results``。

密钥从环境变量 ``DEEPSEEK_API_KEY`` 读取；缺失时不发请求，退出码 2。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

API_URL = "https://api.deepseek.com/v1/tools/search"


def build_payload(
    query: str,
    start: str | None = None,
    end: str | None = None,
    sites: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query, "max_results": limit}
    if start:
        payload["start_date"] = start
    if end:
        payload["end_date"] = end
    if sites:
        payload["site"] = sites
    return payload


def _first(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_results(
    payload: Any,
    query: str,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    raw: Any = []
    if isinstance(payload, dict):
        raw = payload.get("results") or payload.get("data") or payload.get("items") or []
    if isinstance(raw, dict):
        raw = raw.get("results") or raw.get("items") or []
    if not isinstance(raw, list):
        raw = []

    results = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": _first(item, ("title", "name")) or "",
                "url": _first(item, ("url", "link", "source_url")) or "",
                "snippet": _first(item, ("snippet", "content", "description", "summary"))
                or "",
                "published_at": _first(
                    item, ("published_at", "date", "publish_date", "pubDate")
                ),
            }
        )

    return {"query": query, "start": start, "end": end, "results": results}


def search(
    query: str,
    api_key: str,
    start: str | None = None,
    end: str | None = None,
    sites: list[str] | None = None,
    limit: int = 20,
    timeout: int = 30,
) -> dict[str, Any]:
    response = requests.post(
        API_URL,
        json=build_payload(query, start, end, sites, limit),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return normalize_results(response.json(), query, start, end)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="调用 DeepSeek Search API")
    parser.add_argument("--query", required=True, help="检索关键词")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--site", action="append", default=None, help="限定站点，可重复")
    parser.add_argument("--limit", type=int, default=20, help="返回条数上限")
    parser.add_argument("--output", default=None, help="结果 JSON 输出路径；缺省打印到 stdout")
    args = parser.parse_args(argv)

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print(
            "错误：未设置 DEEPSEEK_API_KEY，无法调用 DeepSeek Search API；"
            "请先配置密钥，不要用模型记忆代替检索。",
            file=sys.stderr,
        )
        return 2

    try:
        result = search(
            query=args.query,
            api_key=api_key,
            start=args.start,
            end=args.end,
            sites=args.site,
            limit=args.limit,
        )
    except requests.RequestException as exc:
        print(f"错误：DeepSeek Search 请求失败：{exc}", file=sys.stderr)
        return 3

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        try:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"错误：无法写入 {args.output}: {exc}", file=sys.stderr)
            return 2
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
