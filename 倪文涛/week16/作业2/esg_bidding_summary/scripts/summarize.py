#!/usr/bin/env python3
"""Validate curated facts, compute award statistics, and produce evidence-linked fact cards."""
import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

ENUMS = {
    "status": {"intent", "open", "candidate", "awarded", "cancelled", "failed", "unknown"},
    "verification": {"primary", "secondary", "unverified"},
    "scope": {"core", "extended", "excluded"},
    "amount_type": {"total", "unit_price", "rate", "ceiling", "undisclosed", "mixed"},
    "tax_basis": {"inclusive", "exclusive", "unspecified"},
}
STATUS_LABELS = {"intent": "采购意向", "open": "采购公告（是否仍开放须核对截止时间）", "candidate": "候选人公示",
                 "awarded": "最终成交", "cancelled": "已取消", "failed": "流标", "unknown": "阶段待核验"}
BANDS = [("低于10万元", 0, 100000), ("10–30万元", 100000, 300000), ("30–50万元", 300000, 500000),
         ("50–100万元", 500000, 1000000), ("100–300万元", 1000000, 3000000),
         ("300–1000万元", 3000000, 10000000), ("1000万元及以上", 10000000, None)]


def iso_date(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("日期须为 YYYY-MM-DD")
    return parsed


def amount(row):
    value = row.get("award_amount_yuan")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("award_amount_yuan 须为十进制字符串或 null")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("无法解析成交金额") from error
    if not number.is_finite() or number < 0 or number > Decimal("1e18"):
        raise ValueError("成交金额须为非负有限数，超过10^18元请核验单位")
    if number != number.quantize(Decimal("0.01")):
        raise ValueError("人民币总价超过分精度，请核验是否误填单价")
    return number


def validate(rows):
    if not isinstance(rows, list):
        raise ValueError("records.json 须为数组")
    seen = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"第{i}项须为对象")
        for key in ("record_id", "project_key", "title", "buyer", "category", "province", "industry"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"第{i}项缺少非空文本字段 {key}")
        if row["record_id"] in seen:
            raise ValueError(f"重复包件ID {row['record_id']}，请先合并快照")
        seen.add(row["record_id"])
        for key, values in ENUMS.items():
            if not isinstance(row.get(key), str) or row[key] not in values:
                raise ValueError(f"第{i}项 {key} 无效")
        suppliers = row.get("suppliers")
        if not isinstance(suppliers, list) or any(not isinstance(x, str) or not x.strip() for x in suppliers):
            raise ValueError(f"第{i}项 suppliers 须为名称数组，未知填 []")
        if len(set(suppliers)) != len(suppliers):
            raise ValueError(f"第{i}项联合体成员重复")
        if not re.fullmatch(r"[A-Z]{3}", row.get("currency", "")):
            raise ValueError(f"第{i}项 currency 须为三位大写币种代码")
        if "award_amount_yuan" not in row:
            raise ValueError(f"第{i}项缺少 award_amount_yuan，未知填 null")
        value = amount(row)
        if value is not None and (row["currency"] != "CNY" or row["amount_type"] != "total" or row["status"] != "awarded"):
            raise ValueError(f"第{i}项非人民币最终成交总价不得填写 award_amount_yuan")
        if row["amount_type"] == "total" and row["currency"] == "CNY" and value is None:
            raise ValueError(f"第{i}项总价缺失；未知总价应使用 undisclosed")
        if row.get("award_date") is not None:
            iso_date(row["award_date"])
        if row["status"] == "awarded" and row.get("award_date") is None:
            raise ValueError(f"第{i}项最终成交缺少公告日期")
        if row["verification"] == "primary":
            if not re.match(r"^https?://[^/\s]+", row.get("source_url", "")) or not row.get("evidence"):
                raise ValueError(f"第{i}项原文核验记录缺少有效链接或证据")


def fmt(value):
    return None if value is None else str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def pct(numerator, denominator):
    return fmt(Decimal(numerator) * 100 / Decimal(denominator)) if denominator else None


def comparable(row):
    return row["currency"] == "CNY" and row["amount_type"] == "total" and amount(row) is not None


def quantile(values, p):
    position = Decimal(len(values) - 1) * Decimal(p)
    index = int(position)
    return values[index] + (values[min(index + 1, len(values) - 1)] - values[index]) * (position - index)


def metrics(rows):
    values = sorted(amount(row) for row in rows if comparable(row))
    total = sum(values, Decimal(0))
    result = {"lots": len(rows), "projects": len({x["project_key"] for x in rows}),
              "amount_lots": len(values), "amount_coverage_pct": pct(len(values), len(rows)),
              "total_yuan": fmt(total) if values else None,
              "mean_yuan": fmt(total / len(values)) if values else None,
              "min_yuan": fmt(values[0]) if values else None, "max_yuan": fmt(values[-1]) if values else None,
              "small_sample": len(values) < 5,
              "amount_exclusions": dict(Counter("non_CNY" if x["currency"] != "CNY" else x["amount_type"] for x in rows if not comparable(x)))}
    for label, p in [("p25_yuan", "0.25"), ("median_yuan", "0.5"), ("p75_yuan", "0.75")]:
        result[label] = fmt(quantile(values, p)) if values else None
    return result


def groups(rows, key):
    bins = defaultdict(list)
    for row in rows:
        bins[key(row)].append(row)
    return {name: metrics(items) for name, items in sorted(bins.items())}


def build_summary(rows, start, end):
    validate(rows)
    first, last = iso_date(start), iso_date(end)
    if first > last:
        raise ValueError("开始日期不能晚于结束日期")
    included, excluded = [], []
    for row in rows:
        reason = None
        if row["status"] != "awarded":
            reason = "非最终成交"
        elif row["verification"] != "primary":
            reason = "未核验一手原文"
        elif row["scope"] == "excluded":
            reason = "范围外"
        elif not first <= iso_date(row["award_date"]) <= last:
            reason = "窗口外"
        if reason:
            excluded.append({"record_id": row["record_id"], "reason": reason})
        else:
            included.append(row)
    stats = {"start": start, "end": end, "input_lots": len(rows), "included_lots": len(included),
             "excluded": excluded, "scopes": {},
             "note": "金额单位为人民币元，按公告原税口径；仅为输入样本，非全市场。未观察月份不自动补零。"}
    for scope in ("core", "extended"):
        selected = [x for x in included if x["scope"] == scope]
        data = metrics(selected)
        amounts = [amount(x) for x in selected if comparable(x)]
        total = sum(amounts, Decimal(0))
        data["bands"] = []
        for label, low, high in BANDS:
            values = [x for x in amounts if x >= low and (high is None or x < high)]
            subtotal = sum(values, Decimal(0))
            data["bands"].append({"label": label, "lots": len(values), "total_yuan": fmt(subtotal),
                                  "lot_share_pct": pct(len(values), len(amounts)), "amount_share_pct": pct(subtotal, total)})
        for field in ("category", "province", "industry", "buyer", "tax_basis"):
            data[field] = groups(selected, lambda x, k=field: x[k])
        data["month"] = groups(selected, lambda x: x["award_date"][:7])
        data["quarter"] = groups(selected, lambda x: f"{x['award_date'][:4]}-Q{(int(x['award_date'][5:7])-1)//3+1}")
        data["supplier_group"] = groups(selected, lambda x: " + ".join(sorted(x["suppliers"])) or "未披露")
        data["record_ids"] = [x["record_id"] for x in selected]
        stats["scopes"][scope] = data
    cards = []
    for row in rows:
        value = fmt(amount(row))
        cards.append({"record_id": row["record_id"], "source_url": row.get("source_url"),
                      "verification": row["verification"], "evidence": row.get("evidence"),
                      "summary": f"{row['buyer']}｜{row['title']}｜{STATUS_LABELS[row['status']]}｜"
                                 f"最终成交金额：{value + '元' if value is not None else '未公开可比人民币总价'}｜"
                                 f"税口径：{row['tax_basis']}｜供应商：{'、'.join(row['suppliers']) or '未披露/未确定'}"})
    return {"schema_version": 1, "stats": stats, "fact_cards": cards, "records": rows,
            "review_note": "事实摘要仅重排已输入字段；程序未自动判断原文真实性、相关性或阶段。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        rows = json.loads(Path(args.records).read_text(encoding="utf-8"))
        result = build_summary(rows, args.start, args.end)
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"生成 {len(result['fact_cards'])} 张事实卡；有效历史成交 {result['stats']['included_lots']} 包。")
    except (ValueError, TypeError, OSError, InvalidOperation) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
