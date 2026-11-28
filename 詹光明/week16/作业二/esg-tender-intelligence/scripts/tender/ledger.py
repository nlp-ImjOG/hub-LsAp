"""Markdown 台账：读取、去重合并、写回。"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .filter import normalize_company, normalize_project, parse_amount, priority
from .models import AmountType, Tender, TenderStatus
from .search import parse_date

HEADER = (
    "| 项目编号 | 项目名称 | 采购人 | 地区 | 分类 | 预算(万元) | 中标(万元) | 中标方 | "
    "公告日 | 截止日 | 状态 | 优先级 | 来源 | 首次发现 | 最后更新 | 备注 |"
)
SEPARATOR = "|---|---|---|---|---|---:|---:|---|---|---|---|---|---|---|---|---|"


def _fmt_amount(value: float | None) -> str:
    if value is None:
        return "未披露"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def load_ledger(path: Path) -> list[Tender]:
    if not path.is_file():
        return []
    tenders: list[Tender] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "项目编号" in line or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 16:
            continue
        (
            tid, project, buyer, region, category, budget, award, winner,
            publish, deadline, status, prio, source, first_seen, last_seen, notes,
        ) = cells[:16]
        status_value = next((s for s in TenderStatus if s.value == status), TenderStatus.unknown)
        amount_type = {
            TenderStatus.awarded: AmountType.award,
            TenderStatus.candidate: AmountType.candidate,
            TenderStatus.contract: AmountType.contract,
            TenderStatus.tender: AmountType.budget,
        }.get(status_value, AmountType.unknown)
        tenders.append(
            Tender(
                tid=tid,
                project=project,
                buyer=buyer,
                region=region,
                category=category,
                status=status_value,
                publish_date=parse_date(publish),
                deadline=parse_date(deadline),
                budget=parse_amount(budget),
                award=parse_amount(award),
                amount_type=amount_type,
                winner="" if winner in {"未披露", "待核实"} else winner,
                source_id=source if source.startswith("S") else "",
                source_url="" if source.startswith("S") else source,
                priority=prio,
                notes=notes,
                first_seen=parse_date(first_seen),
                last_seen=parse_date(last_seen),
            )
        )
    return tenders


def save_ledger(path: Path, tenders: list[Tender]) -> None:
    lines = [
        "# ESG 招标跟踪台账",
        "",
        "> 说明：本台账是 Markdown 数据文件，不是脚本。每次日报先读表去重，再追加或更新；不删除历史。",
        "",
        HEADER,
        SEPARATOR,
    ]
    for tender in tenders:
        lines.append(
            "| "
            + " | ".join(
                [
                    tender.tid or "未编号",
                    tender.project,
                    tender.buyer or "未披露",
                    tender.region or "未披露",
                    tender.category or "其他",
                    _fmt_amount(tender.budget),
                    _fmt_amount(tender.award),
                    tender.winner or "未披露",
                    tender.publish_date.isoformat() if tender.publish_date else "未披露",
                    tender.deadline.isoformat() if tender.deadline else "未披露",
                    tender.status.value,
                    tender.priority,
                    tender.source_id or tender.source_url or "未披露",
                    tender.first_seen.isoformat() if tender.first_seen else "",
                    tender.last_seen.isoformat() if tender.last_seen else "",
                    (tender.notes or "").replace("|", "/"),
                ]
            )
            + " |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_ledger(
    existing: list[Tender], new_tenders: list[Tender], today: date
) -> tuple[list[Tender], int, int]:
    """按“项目名称 + 采购人”合并；返回 (merged, added, updated)。"""
    merged = list(existing)
    index = {
        (normalize_project(t.project), normalize_company(t.buyer)): t
        for t in merged
    }
    added = updated = 0
    for tender in new_tenders:
        key = (normalize_project(tender.project), normalize_company(tender.buyer))
        current = index.get(key)
        status = tender.status
        if status == TenderStatus.tender and tender.deadline and tender.deadline < today:
            status = TenderStatus.expired
        if current is None:
            tender.tid = tender.tid if tender.tid.startswith("P") else f"P{today:%Y%m%d}-{len(merged) + 1:02d}"
            tender.status = status
            tender.first_seen = tender.first_seen or today
            tender.last_seen = today
            merged.append(tender)
            index[key] = tender
            added += 1
            continue
        current.status = status
        current.priority = priority(current, today)
        current.deadline = tender.deadline or current.deadline
        current.amount_type = tender.amount_type
        current.award = tender.award if tender.award is not None else current.award
        current.winner = tender.winner or current.winner
        current.notes = tender.notes or current.notes
        current.last_seen = today
        updated += 1
    return merged, added, updated
