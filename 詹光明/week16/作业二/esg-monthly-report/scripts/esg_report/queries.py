"""检索词生成：政策 / 行业 / 公司 / 对标四类，中英双语。"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Category

MONTH_EN = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

INDUSTRY_TERMS: dict[str, list[str]] = {
    "煤炭": ["煤炭", "煤矿", "煤电", "煤化工", "CCUS", "甲烷"],
    "能源": ["能源", "电力", "新能源", "电网", "储能"],
    "制造": ["制造", "钢铁", "化工", "汽车", "供应链"],
    "金融": ["银行", "证券", "保险", "绿色金融", "转型金融"],
}

PEERS: dict[str, list[str]] = {
    "煤炭": ["陕西煤业", "中煤能源", "兖矿能源", "晋控煤业", "平煤股份"],
    "能源": ["国家能源集团", "国家电网", "南方电网", "华能", "国家电投"],
    "制造": ["宝钢股份", "海螺水泥", "万华化学", "比亚迪", "宁德时代"],
    "金融": ["工商银行", "中国银行", "招商银行", "中信证券", "中国平安"],
}

DEFAULT_TERMS = ["ESG", "碳中和", "绿色转型", "供应链"]


@dataclass(frozen=True)
class Query:
    text: str
    category: Category
    lang: str = "zh"


def month_label(year: int, month: int) -> str:
    return f"{year}年{month}月"


def month_en(year: int, month: int) -> str:
    return f"{MONTH_EN[month]} {year}"


def _industry_terms(industry: str) -> list[str]:
    return INDUSTRY_TERMS.get(industry, [industry, *DEFAULT_TERMS])


def _peers(industry: str) -> list[str]:
    return PEERS.get(industry, ["行业龙头"])


def build_queries(client: str, industry: str, year: int, month: int) -> list[Query]:
    """生成去重后的检索词列表。"""
    zh = month_label(year, month)
    en = month_en(year, month)
    terms = _industry_terms(industry)
    peers = _peers(industry)

    raw: list[Query] = [
        # 政策 / 标准 / 评级
        Query(f"ESG 政策 {zh}", Category.policy),
        Query(f"可持续披露 准则 {zh}", Category.policy),
        Query(f"碳排放权交易 政策 {zh}", Category.policy),
        Query(f"{industry} 双碳 政策 {zh}", Category.policy),
        Query(f"ISSB {en}", Category.policy, "en"),
        Query(f"CBAM {en}", Category.policy, "en"),
        Query(f"MSCI ESG rating {en}", Category.policy, "en"),
        # 行业
        Query(f"{industry} ESG {zh}", Category.industry),
        Query(f"{industry} 碳中和 {zh}", Category.industry),
        Query(f"{terms[0]} 绿色转型 {zh}", Category.industry),
        Query(f"{terms[-2]} 减排 {zh}", Category.industry),
        Query(f"{industry} ESG {en}", Category.industry, "en"),
        # 公司
        Query(f"{client} 公告 {zh}", Category.company),
        Query(f"{client} ESG {zh}", Category.company),
        Query(f"{client} 碳排放 {zh}", Category.company),
        Query(f"{client} 安全生产 {zh}", Category.company),
        Query(f'"{client}" ESG {en}', Category.company, "en"),
        # 对标
        *[Query(f"{peer} ESG {year}", Category.benchmark) for peer in peers[:3]],
        Query(f"Glencore climate {year}", Category.benchmark, "en"),
        Query(f"BHP climate {year}", Category.benchmark, "en"),
    ]

    seen: set[str] = set()
    unique: list[Query] = []
    for query in raw:
        key = query.text.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(query)
    return unique
