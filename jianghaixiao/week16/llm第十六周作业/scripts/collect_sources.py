#!/usr/bin/env python3
"""Normalize and deduplicate search-result candidates.

Input: JSON array of objects with title, url, snippet, published_at, source_type.
Output: normalized JSON array with source_id and canonical_url.
This is a written assignment helper; it does not perform network access itself.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def canonicalize(url: str) -> str:
    parts = urlsplit(url.strip())
    path = re.sub(r"/+$", "", parts.path) or "/"
    query = "" if parts.query in {"utm_source", "utm_medium"} else parts.query
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def normalize(item: dict, index: int) -> dict:
    url = canonicalize(item.get("url", ""))
    return {
        "source_id": f"S{index:02d}",
        "title": item.get("title", "").strip(),
        "url": url,
        "canonical_url": url,
        "domain": urlsplit(url).netloc,
        "snippet": item.get("snippet", "").strip(),
        "published_at": item.get("published_at", ""),
        "source_type": item.get("source_type", "unknown"),
    }


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: collect_sources.py input.json output.json")
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    seen = set()
    result = []
    for item in raw:
        normalized = normalize(item, len(result) + 1)
        if not normalized["url"] or normalized["url"] in seen:
            continue
        seen.add(normalized["url"])
        result.append(normalized)
    Path(sys.argv[2]).write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()