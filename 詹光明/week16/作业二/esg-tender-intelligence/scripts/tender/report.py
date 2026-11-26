"""质量门禁与落盘。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import DailyReport, ReviewReport, RunResult
from .writer import render_daily, render_review

REVIEW_HEADINGS = (
    "## 一页纸速览",
    "## 二、样本与方法",
    "## 三、市场总览",
    "## 四、热点招标分析",
    "## 五、投标策略建议",
    "## 附录 A 样本明细",
)
DAILY_HEADINGS = (
    "## 推送摘要",
    "## 一、今日必看",
    "## 二、新增招标",
    "## 三、中标/候选人",
    "## 四、截止提醒",
    "## 五、台账更新",
)


class QualityError(RuntimeError):
    pass


def _source_ok(tender) -> bool:
    return bool(tender.source_url or tender.source_id)


def validate_review(report: ReviewReport, markdown: str, stats: dict[str, object]) -> list[str]:
    errors: list[str] = []
    warnings: list[str] = []
    if not report.tenders:
        errors.append("复盘没有任何项目")
    if not stats.get("n"):
        errors.append("统计样本为空")
    for index, tender in enumerate(report.tenders, start=1):
        if not tender.project:
            errors.append(f"第 {index} 条缺少项目名称")
        if not _source_ok(tender):
            errors.append(f"第 {index} 条「{tender.project}」缺少来源")
        if tender.amount is None:
            warnings.append(f"第 {index} 条「{tender.project}」未披露金额")
        if not tender.winner:
            warnings.append(f"第 {index} 条「{tender.project}」未披露中标方")
        if tender.amount_type.value == "候选人报价":
            warnings.append(f"第 {index} 条「{tender.project}」为候选人报价，非最终中标")
    for heading in REVIEW_HEADINGS:
        if heading not in markdown:
            errors.append(f"缺少必需章节：{heading}")
    if errors:
        raise QualityError("；".join(errors))
    report.gaps.extend(w for w in warnings if w not in report.gaps)
    return warnings


def validate_daily(report: DailyReport, markdown: str) -> list[str]:
    errors: list[str] = []
    warnings: list[str] = []
    for index, tender in enumerate(report.tenders, start=1):
        if not tender.project:
            errors.append(f"第 {index} 条缺少项目名称")
        if not _source_ok(tender):
            errors.append(f"第 {index} 条「{tender.project}」缺少来源")
        if tender.status.value == "候选人" and tender.amount_type.value == "中标/成交":
            warnings.append(f"第 {index} 条「{tender.project}」是候选人，但金额类型写成了中标")
        if tender.publish_date and tender.deadline and tender.deadline < tender.publish_date:
            warnings.append(f"第 {index} 条「{tender.project}」截止日早于公告日")
        if tender.deadline is None:
            warnings.append(f"第 {index} 条「{tender.project}」未披露截止日期")
    for heading in DAILY_HEADINGS:
        if heading not in markdown:
            errors.append(f"缺少必需章节：{heading}")
    if errors:
        raise QualityError("；".join(errors))
    report.gaps.extend(w for w in warnings if w not in report.gaps)
    return warnings


def write_review(
    report: ReviewReport,
    stats: dict[str, object],
    top_by_category: dict[str, list],
    out_dir: Path,
) -> RunResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = render_review(report, stats, top_by_category)
    warnings = validate_review(report, markdown, stats)
    markdown = render_review(report, stats, top_by_category)
    stem = f"ESG投标市场复盘_{report.period_start:%Y-%m}至{report.period_end:%Y-%m}"
    path = out_dir / f"{stem}.md"
    path.write_text(markdown, encoding="utf-8")
    sources_path = out_dir / f"{stem}_sources.json"
    sources_path.write_text(
        json.dumps([s.model_dump(mode="json") for s in report.sources], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    run_path = out_dir / f"{stem}_run.json"
    run_path.write_text(
        json.dumps(
            {
                "mode": "review",
                "offline": report.offline,
                "sample_n": stats.get("n"),
                "amount_disclosed": stats.get("amount_disclosed"),
                "total": stats.get("total"),
                "warnings": warnings,
                "queries": report.query_log,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return RunResult(markdown_path=str(path), run_path=str(run_path), warnings=warnings)


def write_daily(
    report: DailyReport,
    *,
    added: int,
    updated: int,
    ledger_count: int,
    sources: list,
    out_dir: Path,
) -> RunResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = render_daily(report, added=added, updated=updated, ledger_count=ledger_count, sources=sources)
    warnings = validate_daily(report, markdown)
    markdown = render_daily(report, added=added, updated=updated, ledger_count=ledger_count, sources=sources)
    path = out_dir / f"ESG招标日报_{report.report_date.isoformat()}.md"
    path.write_text(markdown, encoding="utf-8")
    run_path = out_dir / f"ESG招标日报_{report.report_date.isoformat()}_run.json"
    run_path.write_text(
        json.dumps(
            {
                "mode": "daily",
                "offline": report.offline,
                "new": len(report.tenders),
                "added": added,
                "updated": updated,
                "ledger_count": ledger_count,
                "warnings": warnings,
                "queries": report.query_log,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return RunResult(
        markdown_path=str(path),
        ledger_path=report.ledger_path,
        run_path=str(run_path),
        warnings=warnings,
    )
