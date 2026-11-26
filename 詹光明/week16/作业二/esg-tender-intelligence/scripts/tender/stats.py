"""历史复盘的确定性统计：不依赖 LLM。"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from .filter import amount_bucket
from .models import Tender

BUCKETS = ("<10万", "10–30万", "30–50万", "50–100万", "100–300万", "300–500万", "500–1000万", ">1000万")


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 2) if values else 0.0


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 2) if values else 0.0


def compute_stats(tenders: list[Tender]) -> dict[str, object]:
    amounts = [t.amount for t in tenders if t.amount is not None]
    total = round(sum(amounts), 2)

    years: dict[int, dict[str, float]] = defaultdict(lambda: {"n": 0, "sum": 0.0, "values": []})
    for tender in tenders:
        year = tender.year or (tender.publish_date.year if tender.publish_date else 0)
        if not year:
            continue
        years[year]["n"] += 1
        if tender.amount is not None:
            years[year]["sum"] += tender.amount
            years[year]["values"].append(tender.amount)

    categories: dict[str, dict[str, float]] = defaultdict(lambda: {"n": 0, "sum": 0.0, "values": []})
    for tender in tenders:
        bucket = categories[tender.category or "其他"]
        bucket["n"] += 1
        if tender.amount is not None:
            bucket["sum"] += tender.amount
            bucket["values"].append(tender.amount)

    buckets = {name: {"n": 0, "sum": 0.0} for name in BUCKETS}
    buckets["未披露"] = {"n": 0, "sum": 0.0}
    for tender in tenders:
        name = amount_bucket(tender.amount)
        buckets[name]["n"] += 1
        if tender.amount is not None:
            buckets[name]["sum"] += tender.amount

    regions = Counter(tender.region or "未披露" for tender in tenders)
    winners = Counter(tender.winner or "未披露" for tender in tenders if tender.winner)

    top_projects = sorted(
        [t for t in tenders if t.amount is not None], key=lambda t: t.amount or 0, reverse=True
    )[:10]

    return {
        "n": len(tenders),
        "amount_disclosed": len(amounts),
        "amount_missing": len(tenders) - len(amounts),
        "total": total,
        "median": _median(amounts),
        "mean": _mean(amounts),
        "min": min(amounts) if amounts else 0.0,
        "max": max(amounts) if amounts else 0.0,
        "years": {
            year: {"n": data["n"], "sum": round(data["sum"], 2), "median": _median(data["values"])}
            for year, data in sorted(years.items())
        },
        "categories": {
            name: {
                "n": data["n"],
                "sum": round(data["sum"], 2),
                "median": _median(data["values"]),
                "share": round(data["sum"] / total * 100, 1) if total else 0.0,
            }
            for name, data in sorted(categories.items(), key=lambda item: item[1]["sum"], reverse=True)
        },
        "buckets": {
            name: {
                "n": data["n"],
                "sum": round(data["sum"], 2),
                "share": round(data["sum"] / total * 100, 1) if total else 0.0,
            }
            for name, data in buckets.items()
        },
        "regions": dict(regions.most_common()),
        "winners": dict(winners.most_common(10)),
        "top_projects": [
            {
                "project": t.project,
                "buyer": t.buyer,
                "amount": t.amount,
                "category": t.category,
                "region": t.region,
            }
            for t in top_projects
        ],
    }
