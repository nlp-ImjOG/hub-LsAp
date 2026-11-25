"""为 ESG 月报三大板块生成查询词矩阵。

确定性体现:把"该搜什么"固化成模板函数,保证覆盖度稳定、可审计、可复现,
而不是每次靠 LLM 临时想查询词(容易漏板块、漏国际动态)。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MonthlyParams:
    client: str          # 客户公司
    industry: str        # 所属行业
    benchmark: str = "中国神华"
    year_month: str = ""  # 如 2026-10;空则不加时间词
    focus: str = ""


def _t(p: MonthlyParams) -> str:
    return f" {p.year_month}" if p.year_month else ""


def block1_policy(p: MonthlyParams) -> list[str]:
    """板块一:ESG 政策、评级、标准动态。"""
    ym = _t(p)
    return [
        f"ESG 政策{ym}",
        f"证监会 ESG 披露{ym}",
        f"沪深交易所 可持续发展报告指引{ym}",
        f"生态环境部{ym} 碳",
        f"发改委 双碳{ym}",
        f"ISSB IFRS S1 S2 更新",
        f"GRI 标准 更新",
        f"MSCI ESG 评级方法 更新",
        f"商道融绿 ESG 评级",
        f"中国企业可持续披露准则{ym}",
        f"EU CSRD{ym}",
        f"COP 可持续{ym}",
    ]


def block2_industry(p: MonthlyParams) -> list[str]:
    """板块二:行业 ESG 新闻与最佳实践。"""
    ym = _t(p)
    ind = p.industry
    return [
        f"{ind} ESG{ym}",
        f"{ind} 可持续发展{ym}",
        f"{ind} 碳中和 进展{ym}",
        f"{ind} ESG 最佳实践",
        f"{ind} 绿色转型 案例",
        f"{ind} 可持续发展报告",
        f"中国{ind}工业协会 ESG",
    ]


def block3_client(p: MonthlyParams) -> list[str]:
    """板块三:客户公司动态 + 对标。"""
    ym = _t(p)
    c = p.client
    b = p.benchmark
    qs = [
        f'"{c}" ESG{ym}',
        f'"{c}" 可持续发展{ym}',
        f'"{c}" 公告{ym}',
        f'"{c}" 碳',
        f'"{c}" 治理',
        f'"{c}" 可持续发展报告',
        # 对标企业
        f'"{b}" ESG',
        f'"{b}" 可持续发展报告',
        f'"{b}" 碳中和',
        f'"{b}" MSCI ESG',
    ]
    if p.focus:
        qs.append(f'"{c}" {p.focus}')
    return qs


def all_queries(p: MonthlyParams) -> dict[str, list[str]]:
    return {
        "板块一 政策/评级/标准": block1_policy(p),
        "板块二 行业动态": block2_industry(p),
        "板块三 客户与对标": block3_client(p),
    }
