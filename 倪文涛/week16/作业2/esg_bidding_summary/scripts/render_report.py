#!/usr/bin/env python3
"""Render reviewed summaries into reusable historical or daily Markdown templates."""
import argparse
import html
import json
import re
from pathlib import Path
from string import Template
from urllib.parse import quote, urlsplit

from summarize import build_summary, STATUS_LABELS

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def text(value):
    if value is None or value == "":
        return "未披露"
    value = html.escape(str(value), quote=False).replace("\n", " ").replace("\r", " ")
    return re.sub(r"([\\`*_{}\[\]()|#!])", r"\\\1", value)


def link(url, label="原文"):
    if not url:
        return "未提供原文"
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("报告链接必须为无内嵌凭据的 HTTP(S) URL")
    return f"[{text(label)}]({quote(url, safe=':/?&=%#@+;,~.-_')})"


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
                     + ["| " + " | ".join(row) + " |" for row in rows])


def supplied_points(items, records):
    if not items:
        return "尚未补充经核验的分析结论；需根据本报告明细完成研判。"
    output = []
    for item in items:
        if not isinstance(item, dict) or not item.get("text") or not item.get("record_ids"):
            raise ValueError("分析/建议须包含 text 与非空 record_ids")
        sources = []
        for record_id in item["record_ids"]:
            if record_id not in records or records[record_id]["verification"] != "primary":
                raise ValueError(f"分析引用未找到或未核验的记录：{record_id}")
            sources.append(link(records[record_id].get("source_url"), record_id))
        output.append("- " + text(item["text"]) + "（依据：" + "、".join(sources) + "）")
    return "\n".join(output)


def history_tables(stats):
    sections = []
    for scope, title in [("core", "核心服务"), ("extended", "延伸技术、工程和设备")]:
        data = stats["scopes"][scope]
        overview = table(["有效包数", "独立项目数", "可比金额包数", "金额可用率%", "总额（元）", "均值（元）", "中位数（元）", "P25（元）", "P75（元）"],
                         [[text(data[k]) for k in ("lots", "projects", "amount_lots", "amount_coverage_pct", "total_yuan", "mean_yuan", "median_yuan", "p25_yuan", "p75_yuan")]])
        sections.extend([f"### {title}", overview,
                         "金额按公告原税口径汇总；不足5个可比金额时仅作小样本观察。",
                         table(["金额档", "包数", "包数占比%", "金额（元）", "金额占比%"],
                               [[text(b[k]) for k in ("label", "lots", "lot_share_pct", "total_yuan", "amount_share_pct")] for b in data["bands"]])])
        for key, label in [("category", "主题"), ("industry", "行业"), ("province", "地区"), ("buyer", "采购人"),
                           ("supplier_group", "供应商或联合体整体"), ("tax_basis", "税口径"), ("month", "月份"), ("quarter", "季度")]:
            sections.append(f"#### {label}分布")
            grouped = data[key]
            if not grouped:
                sections.append("无有效样本。")
                continue
            entries = sorted(grouped.items()) if key in {"month", "quarter"} else sorted(grouped.items(), key=lambda pair: (-pair[1]["lots"], pair[0]))
            sections.append(table([label, "包数", "可比金额包数", "总额（元）", "中位数（元）", "P25（元）", "P75（元）"],
                                  [[text(name)] + [text(values[k]) for k in ("lots", "amount_lots", "total_yuan", "median_yuan", "p25_yuan", "p75_yuan")]
                                   for name, values in entries]))
        if data["amount_exclusions"]:
            sections.append("未进入金额分布：" + text(json.dumps(data["amount_exclusions"], ensure_ascii=False)))
    return "\n\n".join(sections)


def render(bundle, meta, mode):
    # Recompute, so hand-edited totals cannot silently diverge from the supplied facts.
    bundle = build_summary(bundle["records"], bundle["stats"]["start"], bundle["stats"]["end"])
    rows, stats = bundle["records"], bundle["stats"]
    records = {r["record_id"]: r for r in rows}
    values = {
        "title": text(meta.get("title") or ("ESG公开中标样本分析" if mode == "history" else "ESG招标商机日报")),
        "period": f"{stats['start']} 至 {stats['end']}",
        "as_of": text(meta.get("as_of", "未提供检索截止时刻")),
        "coverage": text(meta.get("coverage", "未提供检索覆盖说明；本文件仅为数据整理草稿。")),
        "limitations": text(meta.get("limitations", "公开信息样本不代表全部市场；覆盖、来源和业务判断仍需复核。")),
        "insights": supplied_points(meta.get("insights", []), records),
        "recommendations": supplied_points(meta.get("recommendations", []), records),
        "input_lots": str(len(rows)),
        "included_lots": str(stats["included_lots"]),
    }
    if mode == "history":
        values["statistics"] = history_tables(stats)
        included_ids = {rid for s in stats["scopes"].values() for rid in s["record_ids"]}
        values["details"] = table(["ID/项目", "采购人", "最终供应商", "公告日期", "成交额（元）", "口径", "来源"],
                                  [[text(r["record_id"]) + " / " + text(r["title"]), text(r["buyer"]),
                                    text("、".join(r["suppliers"])), text(r.get("award_date")), text(r.get("award_amount_yuan")),
                                    text(f"{r['scope']} / {r['amount_type']} / {r['tax_basis']}"), link(r.get("source_url"))]
                                   for r in rows if r["record_id"] in included_ids])
        values["exclusions"] = table(["ID", "未纳入成交统计的原因", "来源"],
                                     [[text(x["record_id"]), text(x["reason"]), link(records[x["record_id"]].get("source_url"))] for x in stats["excluded"]])
    else:
        values["run_status"] = text(meta.get("run_status", "覆盖状态待核验"))
        values["daily_table"] = table(["事件/优先级", "项目/采购人", "预算或限价（元）", "报名截止", "文件获取截止", "投标截止", "行动状态", "来源"],
                                     [[text(r.get("event_kind", "待分类")) + " / " + text(r.get("priority", "待评估")),
                                       text(r["title"]) + " / " + text(r["buyer"]),
                                       "预算：" + text(r.get("budget_yuan")) + "；限价：" + text(r.get("ceiling_yuan")),
                                       text(r.get("registration_deadline")), text(r.get("document_deadline")), text(r.get("bid_deadline")),
                                       text(r.get("action_status", "待核验，不能据此判断仍可报名")), link(r.get("source_url"))]
                                      for r in rows if r["scope"] != "excluded"])
        values["daily_notes"] = "\n\n".join(
            f"### {text(r['title'])}\n\n"
            f"- 公告阶段：{text(STATUS_LABELS[r['status']])}；核验状态：{text(r['verification'])}\n"
            f"- 资格/业绩：{text(r.get('qualification'))}\n"
            f"- 交付内容：{text(r.get('deliverables'))}\n"
            f"- 变更及影响：{text(r.get('change_summary'))}\n"
            f"- 下一步：{text(r.get('next_action', '核对原公告及最新更正，资质匹配待核验'))}\n"
            f"- 来源：{link(r.get('source_url'))}" for r in rows if r["scope"] != "excluded") or "本批无项目记录；是否无新增取决于上述实际覆盖状态。"
    template = Template((ASSETS / (mode + "_report.md")).read_text(encoding="utf-8"))
    return template.substitute(values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    parser.add_argument("--mode", choices=["history", "daily"], default="history")
    parser.add_argument("--meta", help="Optional reviewed coverage, limitations, insights and recommendations")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        meta = json.loads(Path(args.meta).read_text(encoding="utf-8")) if args.meta else {}
        report = render(bundle, meta, args.mode)
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report, encoding="utf-8")
        print("已生成报告草稿：" + str(target))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
