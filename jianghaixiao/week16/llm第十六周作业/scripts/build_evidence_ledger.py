#!/usr/bin/env python3
"""Convert claim records into a JSONL evidence ledger.

Input JSON example:
[
  {
    "claim": "LangGraph is suitable for complex workflows",
    "source_id": "S01",
    "quote": "...",
    "published_at": "2026-01-01",
    "confidence": "medium"
  }
]
"""

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_evidence_ledger.py claims.json ledger.jsonl")
    claims = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    lines = []
    for index, item in enumerate(claims, start=1):
        record = {
            "claim_id": item.get("claim_id", f"C{index:02d}"),
            "claim": item.get("claim", ""),
            "source_id": item.get("source_id", ""),
            "quote": item.get("quote", ""),
            "published_at": item.get("published_at", ""),
            "confidence": item.get("confidence", "medium"),
            "conflicts_with": item.get("conflicts_with", []),
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    Path(sys.argv[2]).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()