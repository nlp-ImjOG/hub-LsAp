"""招标项目清洗：金额解析、去重、分类、窗口、优先级。"""

from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import AmountType, Source, Tender, TenderStatus

CATEGORIES = (
    "ESG报告/信息披露",
    "ESG咨询/管理提升/评级",
    "碳盘查/碳核算/碳足迹",
    "碳资产/碳交易/CCER",
    "双碳规划/零碳园区/碳预算",
    "碳管理/ESG数字化平台",
    "ESG评价/工程ESG",
    "绿色金融/转型金融",
    "ESG培训/能力建设",
    "其他",
)

STRATEGIC_BUYERS = (
    "国家能源集团", "国家电网", "南方电网", "中国银行", "中国神华", "中煤",
    "陕煤", "兖矿", "华能", "大唐", "华电", "国家电投", "中石油", "中石化",
    "中海油", "中国铁塔", "中国中车", "宁波舟山港", "华夏理财", "岚图",
    "中国重汽", "粤海", "浙江省经济信息中心",
)

_COMPANY_SUFFIX = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团|公司)$")
_NON_SERVICE = ("设备采购", "EPC", "工程总包", "施工", "土建", "安装", "监理")
_SERVICE_HINTS = ("咨询", "报告", "核算", "盘查", "足迹", "平台", "评价", "规划", "培训", "采购")


def parse_amount(value: object) -> float | None:
    """把 '137.49万元' / '1.5亿元' / '500,000元' / 200 统一成万元。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value).replace(",", "").replace("，", "").strip()
    if not text or text in {"未披露", "-", "—", "无"}:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    number = float(match.group(1))
    if "亿" in text:
        return round(number * 10000, 2)
    if "万" in text:
        return round(number, 2)
    if "元" in text:
        return round(number / 10000, 2)
    return round(number, 2)


def normalize_text(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").lower())


def normalize_url(url: str) -> str:
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return (url or "").strip()
    host = parts.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parts.path) or "/"
    kept = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() in {"id", "articleid", "guid", "p", "newsid"}]
    return urlunsplit((parts.scheme or "https", host, path, urlencode(kept), ""))


def dedupe_sources(sources: list[Source]) -> list[Source]:
    kept: list[Source] = []
    seen: set[str] = set()
    for source in sources:
        key = normalize_url(source.url) if source.url else normalize_text(source.title)
        if key and key in seen:
            continue
        seen.add(key)
        kept.append(source)
    return kept


def assign_sids(sources: list[Source]) -> list[Source]:
    for index, source in enumerate(sources, start=1):
        source.sid = f"S{index}"
    return sources


def normalize_company(name: str) -> str:
    return _COMPANY_SUFFIX.sub("", normalize_text(name))


def normalize_project(name: str) -> str:
    text = re.sub(r"^【[^】]*】", "", name or "")
    text = re.sub(r"[-_—|].{0,20}$", "", text)
    return normalize_text(text)


def is_duplicate(a: Tender, b: Tender) -> bool:
    if normalize_project(a.project) == normalize_project(b.project) and normalize_company(a.buyer) == normalize_company(b.buyer):
        return True
    if not (a.project and b.project) or len(a.project) < 8 or len(b.project) < 8:
        return False
    return SequenceMatcher(None, normalize_project(a.project), normalize_project(b.project)).ratio() >= 0.92


def dedupe_tenders(tenders: list[Tender]) -> list[Tender]:
    kept: list[Tender] = []
    for tender in tenders:
        if any(is_duplicate(tender, existing) for existing in kept):
            continue
        kept.append(tender)
    return kept


def classify_tender(text: str) -> str:
    text = text or ""
    if any(word in text for word in ("碳管理平台", "能碳平台", "碳账户", "ESG平台", "数字化平台", "管理系统")):
        return "碳管理/ESG数字化平台"
    if any(word in text for word in ("碳足迹", "碳标签", "碳核算", "碳盘查", "碳核查", "因子库")):
        return "碳盘查/碳核算/碳足迹"
    if any(word in text for word in ("碳资产", "CCER", "碳交易")):
        return "碳资产/碳交易/CCER"
    if any(word in text for word in ("零碳园区", "碳达峰", "碳中和", "碳排放预算", "双控", "路径研究", "规划")):
        return "双碳规划/零碳园区/碳预算"
    if any(word in text for word in ("ESG报告", "社会责任报告", "可持续发展报告", "CSR", "报告编制", "报告咨询")):
        return "ESG报告/信息披露"
    if any(word in text for word in ("ESG评价", "工程ESG", "绿色园区评价")):
        return "ESG评价/工程ESG"
    if any(word in text for word in ("绿色金融", "转型金融", "绿色债券", "绿色信贷")):
        return "绿色金融/转型金融"
    if any(word in text for word in ("ESG培训", "能力建设", "培训")):
        return "ESG培训/能力建设"
    if any(word in text for word in ("ESG咨询", "ESG管理", "ESG战略", "评级提升", "ESG体系", "ESG鉴证")):
        return "ESG咨询/管理提升/评级"
    return "其他"


def status_from_text(text: str) -> TenderStatus:
    text = text or ""
    if any(word in text for word in ("终止", "流标", "废标")):
        return TenderStatus.terminated
    if "合同" in text:
        return TenderStatus.contract
    if "候选人" in text:
        return TenderStatus.candidate
    if any(word in text for word in ("中标", "成交", "中选")):
        return TenderStatus.awarded
    if any(word in text for word in ("招标", "采购", "询比", "磋商", "谈判", "询价")):
        return TenderStatus.tender
    return TenderStatus.unknown


def amount_type_from_status(status: TenderStatus) -> AmountType:
    return {
        TenderStatus.awarded: AmountType.award,
        TenderStatus.candidate: AmountType.candidate,
        TenderStatus.contract: AmountType.contract,
        TenderStatus.tender: AmountType.budget,
    }.get(status, AmountType.unknown)


def is_service_tender(text: str) -> bool:
    text = text or ""
    if any(word in text for word in ("ESG", "碳", "可持续", "双碳")):
        return True
    if any(word in text for word in _NON_SERVICE) and not any(word in text for word in _SERVICE_HINTS):
        return False
    return True


def amount_bucket(amount: float | None) -> str:
    if amount is None:
        return "未披露"
    if amount < 10:
        return "<10万"
    if amount < 30:
        return "10–30万"
    if amount < 50:
        return "30–50万"
    if amount < 100:
        return "50–100万"
    if amount < 300:
        return "100–300万"
    if amount < 500:
        return "300–500万"
    if amount < 1000:
        return "500–1000万"
    return ">1000万"


def priority(tender: Tender, today: date) -> str:
    amount = tender.award if tender.award is not None else tender.budget
    if tender.deadline and 0 <= (tender.deadline - today).days <= 7:
        return "P0"
    if (amount is not None and amount >= 100) or any(buyer in tender.buyer for buyer in STRATEGIC_BUYERS):
        return "P1"
    return "P2"


def in_window(day: date | None, start: date, end: date) -> bool:
    return day is not None and start <= day <= end


def extract_amounts(text: str) -> tuple[float | None, float | None, float | None]:
    """从正文里粗略找预算/最高限价/中标金额，供 LLM 失败时兜底。"""
    text = text or ""
    budget = ceiling = award = None
    for label, pattern in (
        ("budget", r"(?:预算|采购预算)[^\d]{0,10}([\d.,]+\s*(?:亿|万)?元?)"),
        ("ceiling", r"(?:最高限价|控制价|限价)[^\d]{0,10}([\d.,]+\s*(?:亿|万)?元?)"),
        ("award", r"(?:中标|成交|中选)[^\d]{0,10}([\d.,]+\s*(?:亿|万)?元?)"),
    ):
        match = re.search(pattern, text)
        if match:
            parsed = parse_amount(match.group(1))
            if label == "budget":
                budget = parsed
            elif label == "ceiling":
                ceiling = parsed
            else:
                award = parsed
    return budget, ceiling, award
