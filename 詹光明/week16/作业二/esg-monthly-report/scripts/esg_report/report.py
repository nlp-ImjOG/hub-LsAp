"""报告质量校验与落盘。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import Category, ReportData, RunResult
from .writer import render

REQUIRED_HEADINGS = (
    "## 一页纸速览",
    "## 一、ESG 政策、评级与标准动态",
    "## 二、行业动态与最佳实践",
    "## 三、公司动态与对标分析",
    "## 附录 A 信息来源清单",
)


class QualityError(RuntimeError):
    """硬性质量校验失败：报告不能交付。"""


def _safe_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", name.strip())
    return cleaned or "客户"


def validate(report: ReportData, markdown: str) -> list[str]:
    """返回警告；硬错误直接抛 QualityError。"""
    errors: list[str] = []
    warnings: list[str] = []

    if not report.items:
        errors.append("报告没有任何条目")
    if not report.summary:
        errors.append("报告没有一页纸速览")

    source_ids = {source.sid for source in report.sources}
    for index, item in enumerate(report.items, start=1):
        if not item.source_ids:
            errors.append(f"条目 {index}「{item.title}」没有来源")
        for sid in item.source_ids:
            if sid not in source_ids:
                errors.append(f"条目 {index}「{item.title}」引用了不存在的来源 {sid}")
        if not (item.fact.strip() and item.impact.strip() and item.recommendation.strip()):
            warnings.append(f"条目 {index}「{item.title}」的事实/影响/建议不完整")

    for heading in REQUIRED_HEADINGS:
        if heading not in markdown:
            errors.append(f"缺少必需章节：{heading}")

    summary_chars = len("".join(report.summary))
    if summary_chars > 300:
        warnings.append(f"一页纸速览 {summary_chars} 字，超过 300 字上限")
    if not any(item.category == Category.policy for item in report.items):
        warnings.append("政策/评级板块没有条目")
    if not any(item.category == Category.industry for item in report.items):
        warnings.append("行业板块没有条目")
    if not any(item.category == Category.company for item in report.items):
        warnings.append("公司板块没有条目")
    if not any(item.category == Category.benchmark for item in report.items):
        warnings.append("对标板块没有条目")

    unverified = [source.sid for source in report.sources if source.date_status.value != "verified"]
    if unverified:
        warnings.append(f"以下来源日期不在报告期内或未核实：{', '.join(unverified)}")
    snippet_only = [source.sid for source in report.sources if source.fetch_status != "page"]
    if snippet_only:
        warnings.append(f"以下来源未抓到正文，使用搜索摘要：{', '.join(snippet_only)}")

    if errors:
        raise QualityError("；".join(errors))

    for warning in warnings:
        if warning not in report.gaps:
            report.gaps.append(warning)
    return warnings


def write_report(
    report: ReportData,
    markdown: str,
    out_dir: Path,
    *,
    run_meta: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> RunResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"ESG月报_{_safe_name(report.client)}_{report.period_start:%Y-%m}"
    markdown_path = out_dir / f"{stem}.md"
    sources_path = out_dir / f"{stem}_sources.json"
    run_path = out_dir / f"{stem}_run.json"

    markdown_path.write_text(markdown, encoding="utf-8")
    sources_path.write_text(
        json.dumps([s.model_dump(mode="json") for s in report.sources], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta = {
        "client": report.client,
        "industry": report.industry,
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "generated_at": report.generated_at.isoformat(),
        "offline": report.offline,
        "source_count": len(report.sources),
        "item_count": len(report.items),
        "warnings": warnings or [],
        "queries": report.query_log,
        **(run_meta or {}),
    }
    run_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return RunResult(
        report=report,
        markdown_path=str(markdown_path),
        sources_path=str(sources_path),
        run_path=str(run_path),
        warnings=warnings or [],
    )


def build_and_write(
    report: ReportData,
    out_dir: Path,
    *,
    run_meta: dict[str, Any] | None = None,
) -> RunResult:
    markdown = render(report)
    warnings = validate(report, markdown)
    # validate 会把质量提示写进 report.gaps，重新渲染一次让附录 B 带上这些提示。
    markdown = render(report)
    return write_report(report, markdown, out_dir, run_meta=run_meta, warnings=warnings)
