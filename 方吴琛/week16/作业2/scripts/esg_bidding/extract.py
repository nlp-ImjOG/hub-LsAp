"""招投标字段抽取:从标题/正文用规则 + 可选 LLM 抽取结构化字段。

确定性体现:金额、日期、项目类型这些"必须准确"的字段用正则/规则确定抽取,
只把"项目类型归类"这种带语义的交给 LLM(且给死 taxonomy 让它选,不让它自由命名)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime

from common import summarize_text, llm_json, CONFIG


@dataclass
class BidRecord:
    title: str
    url: str
    bidder: str = ""        # 招标单位
    winner: str = ""        # 中标单位
    amount_wan: float | None = None  # 中标金额(万元)
    date: str = ""          # YYYY-MM-DD
    region: str = ""
    category: str = "其他"
    source_cred: str = "C"
    snippet: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---- 确定性规则抽取 ----

_AMOUNT_PATTERNS = [
    # 1234.5 万元 / 1234 万元
    re.compile(r"中标(?:金额|价格|价)(?:为|是|:)?\s*([0-9]+(?:\.[0-9]+)?)\s*(亿元|万元|元)"),
    re.compile(r"成交(?:金额|价格)(?:为|是|:)?\s*([0-9]+(?:\.[0-9]+)?)\s*(亿元|万元|元)"),
    re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(亿元|万元)\s*(?:中标|成交)"),
    re.compile(r"金额[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*(亿元|万元|元)"),
]
_UNIT_TO_WAN = {"亿元": 10000.0, "万元": 1.0, "元": 0.0001}


def extract_amount(text: str) -> float | None:
    for pat in _AMOUNT_PATTERNS:
        m = pat.search(text)
        if m:
            num = float(m.group(1))
            unit = m.group(2)
            return round(num * _UNIT_TO_WAN[unit], 4)
    return None


_DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})"),
    re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日"),
]


def extract_date(text: str) -> str:
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            y, mo, d = m.groups()
            try:
                return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            except ValueError:
                continue
    return ""


# 招标/中标单位:优先匹配"中标单位:xxx""中标供应商:xxx"等
_BIDDER_PATTERNS = [
    re.compile(r"采购(?:人|单位)[:：]\s*([^\s,，。;；]{2,40})"),
    re.compile(r"招标(?:人|单位|方)[:：]\s*([^\s,，。;；]{2,40})"),
]
_WINNER_PATTERNS = [
    re.compile(r"中标(?:单位|供应商|人)[:：]\s*([^\s,，。;；]{2,40})"),
    re.compile(r"成交(?:供应商|单位)[:：]\s*([^\s,，。;；]{2,40})"),
]


def _first_match(patterns, text: str) -> str:
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return ""


# ---- 语义分类(可选 LLM,给死 taxonomy)----
CATEGORIES = {
    "C1": "碳核查与碳资产",
    "C2": "ESG咨询与披露",
    "C3": "绿色金融咨询",
    "C4": "节能改造与能效",
    "C5": "环境监测与治理",
    "C6": "新能源与储能",
    "C7": "生态修复",
    "C8": "绿色工厂与清洁生产",
    "C9": "可持续供应链",
    "C0": "其他",
}

# 关键词→类别的确定性映射(优先于 LLM)
_KW_TO_CAT = [
    (["碳核查", "碳盘查", "碳足迹", "碳资产", "ccer", "碳监测", "温室气体"], "C1"),
    (["esg咨询", "esg报告", "esg评级", "esg披露", "可持续披露", "csr报告", "社会责任报告"], "C2"),
    (["绿色金融", "绿色债券", "转型金融", "气候投融资", "绿色信贷"], "C3"),
    (["节能", "能效", "合同能源管理", "能源审计", "综合能源"], "C4"),
    (["环境监测", "污染", "土壤修复", "水体", "大气治理", "固废", "危废"], "C5"),
    (["光伏", "风电", "储能", "充电桩", "分布式能源", "氢能"], "C6"),
    (["生态修复", "矿山修复", "湿地", "生物多样性", "生态保护"], "C7"),
    (["绿色工厂", "绿色园区", "清洁生产", "绿色认证", "绿色建材"], "C8"),
    (["可持续供应链", "绿色供应链"], "C9"),
]


def classify(title: str, text: str = "") -> str:
    blob = (title + " " + text).lower()
    for kws, code in _KW_TO_CAT:
        if any(k in blob for k in kws):
            return code
    # LLM 兜底(若有 key):从 taxonomy 选一个,不让自由命名
    if CONFIG.llm_enabled and text:
        schema = '{"category_code": "C0..C9"}'
        out = llm_json(
            "从给定 taxonomy 选最匹配的项目类别 code。",
            f"标题:{title}\n正文摘要:{text[:1500]}",
            schema,
        )
        code = out.get("category_code", "C0") if isinstance(out, dict) else "C0"
        if code in CATEGORIES:
            return code
    return "C0"


def parse_record(title: str, url: str, snippet: str, text: str, cred: str) -> BidRecord:
    blob = f"{title}\n{snippet}\n{text[:3000]}"
    rec = BidRecord(
        title=title.strip(),
        url=url,
        snippet=snippet,
        amount_wan=extract_amount(blob),
        date=extract_date(blob),
        bidder=_first_match(_BIDDER_PATTERNS, blob),
        winner=_first_match(_WINNER_PATTERNS, blob),
        source_cred=cred,
    )
    rec.category = classify(title, text or snippet)
    return rec
