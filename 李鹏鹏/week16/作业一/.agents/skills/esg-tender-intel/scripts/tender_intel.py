#!/usr/bin/env python
"""ESG / 可持续发展 / 双碳 招投标情报引擎。

一个 CLI 覆盖全流程：collect(抓取) -> ingest(入库) -> analyze(统计) -> report(报告) -> push(每日推送)。

示例（用 py312 虚拟环境，在 skill 目录内运行）：
    python scripts/tender_intel.py collect --kw 碳核查 --pages 2 --print-only
    python scripts/tender_intel.py ingest ../../data/case2/seeds/*.json
    python scripts/tender_intel.py analyze --since 2024-11-24 --assets ../../reports/assets
    python scripts/tender_intel.py report  --since 2024-11-24 --out ../../reports/ESG招标情报.md
    python scripts/tender_intel.py push    --days 1 --out ../../reports/每日推送.md
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = SKILL_DIR / "data" / "tenders.db"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

# ---------------------------------------------------------------- 分类与地域规则

# 顺序即优先级：越靠前越具体，先命中先归属
CATEGORY_RULES: list[tuple[str, str]] = [
    ("碳足迹", r"碳足迹|LCA|生命周期评价|产品碳"),
    ("碳核查/核算", r"核查|核算|盘查|温室气体清单|MRV|碳计量|碳监测"),
    ("碳资产/碳交易", r"碳资产|碳交易|CCER|配额|碳信用|碳普惠|碳汇|碳抵消|碳金融"),
    ("转型金融/绿色金融", r"绿色债券|转型金融|绿色信贷|ESG债券|可持续挂钩|绿色基金|绿色保险|转型债"),
    ("双碳战略/规划", r"双碳|碳达峰|碳中和|近零碳|零碳|低碳转型|减排路径|气候战略|达峰行动"),
    ("ESG评级/数据", r"评级|指数|数据服务|数据库|信息系统|平台建设|管理系统|数字化|AI|智能体|鉴证|审验|保证"),
    ("ESG报告/披露", r"ESG.{0,6}报告|可持续发展报告|社会责任报告|环境、社会|环境社会|信息披露|披露合规|报告编制|报告设计|双层重要性|双重重要性"),
    ("ESG咨询/顾问", r"ESG|环境、社会及管治|顾问|咨询|尽调|尽职调查|管理体系|培训"),
    ("绿色供应链/贸易", r"供应链|绿电|绿证|绿色采购|绿色物流|循环经济|包装|CBAM|碳关税"),
    ("环境合规/生态", r"环评|环境影响|排污|生态|生物多样性|环保验收|清洁生产|EHS|环保管家"),
]

PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏",
    "新疆", "香港", "澳门", "台湾",
]

# 地级市/计划单列市 -> 省级（标题里常常只写城市名）
CITY_TO_PROVINCE = {
    "东莞": "广东", "深圳": "广东", "广州": "广东", "佛山": "广东", "珠海": "广东",
    "中山": "广东", "惠州": "广东", "江门": "广东", "汕头": "广东",
    "苏州": "江苏", "南京": "江苏", "无锡": "江苏", "常州": "江苏", "南通": "江苏",
    "徐州": "江苏", "扬州": "江苏", "盐城": "江苏",
    "杭州": "浙江", "宁波": "浙江", "温州": "浙江", "嘉兴": "浙江", "绍兴": "浙江",
    "金华": "浙江", "台州": "浙江", "湖州": "浙江",
    "青岛": "山东", "济南": "山东", "烟台": "山东", "潍坊": "山东", "威海": "山东",
    "临沂": "山东", "淄博": "山东",
    "成都": "四川", "宜宾": "四川", "绵阳": "四川", "徳阳": "四川",
    "九江": "江西", "南昌": "江西", "赣州": "江西", "上饶": "江西",
    "大连": "辽宁", "沈阳": "辽宁", "鞍山": "辽宁",
    "厦门": "福建", "福州": "福建", "泉州": "福建",
    "武汉": "湖北", "宜昌": "湖北", "襄阳": "湖北",
    "长沙": "湖南", "株洲": "湖南", "湘潭": "湖南",
    "合肥": "安徽", "芜湖": "安徽", "马鞍山": "安徽",
    "郑州": "河南", "洛阳": "河南", "新乡": "河南",
    "西安": "陕西", "榆林": "陕西", "咸阳": "陕西",
    "太原": "山西", "大同": "山西", "宁德": "福建", "包头": "内蒙古", "鄂尔多斯": "内蒙古",
    "大庆": "黑龙江", "哈尔滨": "黑龙江", "长春": "吉林", "石家庄": "河北", "唐山": "河北",
    "南宁": "广西", "柳州": "广西", "海口": "海南", "三亚": "海南", "兰州": "甘肃",
    "银川": "宁夏", "西宁": "青海", "乌鲁木齐": "新疆", "拉萨": "西藏", "贵阳": "贵州",
    "遵义": "贵州", "昆明": "云南", "呼和浩特": "内蒙古", "雄安": "河北",
}

# 采购人类型：用于"谁在花钱买 ESG 服务"的结构性判断
BUYER_TYPE_RULES: list[tuple[str, str]] = [
    ("金融/证券", r"银行|证券|保险|基金|信托|期货|资管|农商行|信用社|投资控股|金融"),
    ("央企/国企集团", r"集团|股份|控股|能源|电力|煤炭|石油|化工|钢铁|有色|建材|港口|矿业|铁路|电网|大唐|华能|国家能源|中广核|中核|三峡|华电|国投|中煤|宝武|鞍钢|五矿|招商局|中远|中交建|中铁|中冶"),
    ("上市公司", r"股份有限公司|有限公司"),
    ("政府/事业单位", r"人民政府|发改委|发展改革|生态环境局|厅|局$|委员会|中心|研究院|大学|学院|医院|监管|交易中心|开发区|园区|管委会"),
    ("城投/平台公司", r"城投|城建|交通投资|水务|燃气|供热|公用事业|环保集团|环境集团|产业发展|国有资本"),
]

COLS = ["uid", "title", "buyer", "winner", "amount_wan", "publish_date", "category",
        "kind", "region", "buyer_type", "source", "url", "evidence", "raw",
        "first_seen", "last_seen", "pushed"]

# 列顺序固定，全部走占位符”，避免任何字符串拼接进 SQL



def classify(title: str) -> str:
    for name, pat in CATEGORY_RULES:
        if re.search(pat, title, re.I):
            return name
    return "其他"


def province_of(text: str) -> str:
    for p in PROVINCES:
        if p in text:
            return p
    for city, prov in CITY_TO_PROVINCE.items():
        if city in text:
            return prov
    return "全国/未标注"


def kind_of(title: str) -> str:
    """区分采购/招标阶段与已成交阶段：分析“中标情况”必须分开。"""
    if re.search(r"中标|成交|结果公告|结果公示|候选人|定标|中选", title):
        return "中标/成交"
    if re.search(r"招标|采购公告|公开采购|比选|磋商|询价|邀请|资格预审|谈判", title):
        return "招标/采购"
    return "其他"


# 历史尝试：从标题尾部猜中标人（已停用）。实测会把采购人误判为中标人，
# 因此 winner 只接受人工核验的输入，宁可缺失也不猜。
ORG_TAIL = re.compile(r"[—\-–－>＞]+\s*([\u4e00-\u9fa5A-Za-z0-9（）()·\s]{4,40}"
                      r"(?:有限公司|股份公司|有限责任公司|集团|研究院|研究所|中心|大学|事务所|"
                      r"学院|银行|\.com))")


def buyer_type_of(buyer: str, title: str) -> str:
    blob = f"{buyer} {title}"
    for name, pat in BUYER_TYPE_RULES:
        if re.search(pat, blob, re.I):
            return name
    return "其他企业"


# ---------------------------------------------------------------- 金额解析

AMOUNT_PATTERNS = [
    (r"(?:￥|¥|RMB\s*:?)\s*([\d,]+(?:\.\d+)?)\s*亿", 10000.0),
    (r"(?:￥|¥|RMB\s*:?)\s*([\d,]+(?:\.\d+)?)\s*万", 1.0),
    (r"([\d,]+(?:\.\d+)?)\s*亿(?:元)?", 10000.0),
    (r"([\d,]+(?:\.\d+)?)\s*万(?:元)?", 1.0),
]


def parse_amount(text: str) -> float | None:
    """把 '￥14.38万元' / '129.9万' / '1.2亿元' 统一折算成万元。"""
    if not text:
        return None
    for pat, mult in AMOUNT_PATTERNS:
        m = re.search(pat, text)
        if m:
            try:
                return round(float(m.group(1).replace(",", "")) * mult, 4)
            except ValueError:
                continue
    # 纯元：报价 534000.00 元
    m = re.search(r"([\d,]{4,}(?:\.\d+)?)\s*元", text)
    if m:
        try:
            return round(float(m.group(1).replace(",", "")) / 10000, 4)
        except ValueError:
            return None
    return None


DATE_PATTERNS = [
    r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})",
    r"(20\d{2})[-/年](\d{1,2})月?",
]


def parse_date(text: str) -> str | None:
    for pat in DATE_PATTERNS:
        m = re.search(pat, text or "")
        if m:
            try:
                g = [int(x) for x in m.groups()]
                d = date(g[0], g[1], g[2] if len(g) > 2 else 1)
                if d > date.today() or d.year < 2015:
                    continue
                return d.isoformat()
            except ValueError:
                continue
    return None


def make_uid(title: str, url: str) -> str:
    return hashlib.sha256(f"{title.strip()}|{url}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------- 存储

def connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE IF NOT EXISTS tenders (
        uid TEXT PRIMARY KEY, title TEXT, buyer TEXT, winner TEXT, amount_wan TEXT,
        publish_date TEXT, category TEXT, kind TEXT, region TEXT, buyer_type TEXT,
        source TEXT, url TEXT, evidence TEXT, raw TEXT, first_seen TEXT, last_seen TEXT,
        pushed TEXT DEFAULT '0')""")
    return con


def normalize(rec: dict) -> dict:
    """补全派生字段：分类、地域、采购人类型、金额、日期。"""
    title = (rec.get("title") or "").strip()
    evidence = rec.get("evidence") or ""
    blob = f"{title} {evidence} {rec.get('buyer') or ''} {rec.get('winner') or ''}"
    out = dict(rec)
    out["title"] = title
    out["category"] = rec.get("category") or classify(title)
    out["kind"] = rec.get("kind") or kind_of(title)
    out["winner"] = rec.get("winner") or ""
    out["region"] = rec.get("region") or province_of(blob)
    out["buyer_type"] = rec.get("buyer_type") or buyer_type_of(rec.get("buyer") or "", title)
    if rec.get("amount_wan") in (None, "", 0):
        # 只从标题取金额：正文里的亿元级数字多为市场统计，不是合同金额
        out["amount_wan"] = parse_amount(title) or ""
    elif isinstance(rec["amount_wan"], (int, float)):
        out["amount_wan"] = rec["amount_wan"]
    if not rec.get("publish_date"):
        out["publish_date"] = parse_date(evidence) or parse_date(title) or ""
    out["uid"] = rec.get("uid") or make_uid(title, rec.get("url") or rec.get("source") or "")
    return out


def upsert(con: sqlite3.Connection, records: list[dict]) -> tuple[int, int]:
    now = datetime.now().isoformat(timespec="seconds")
    new = dup = 0
    for r in records:
        if not r.get("title"):
            continue
        r = normalize(r)
        row = {c: (str(r.get(c)) if r.get(c) is not None else "") for c in COLS[:-1]}
        if con.execute("SELECT 1 FROM tenders WHERE uid=?", (row["uid"],)).fetchone():
            con.execute("UPDATE tenders SET last_seen=? WHERE uid=?", (now, row["uid"]))
            dup += 1
            continue
        row["first_seen"] = now
        row["last_seen"] = now
        con.execute("INSERT INTO tenders (uid,title,buyer,winner,amount_wan,publish_date,category,kind,region,buyer_type,source,url,evidence,raw,first_seen,last_seen,pushed) VALUES (:uid,:title,:buyer,:winner,:amount_wan,:publish_date,:category,:kind,:region,:buyer_type,:source,:url,:evidence,:raw,:first_seen,:last_seen,:pushed)", {**row, "pushed": "0"})
        new += 1
    con.commit()
    return new, dup


# ---------------------------------------------------------------- 采集器

def http_get(url: str, timeout: int = 25, retries: int = 2) -> str | None:
    for i in range(retries + 1):
        try:
            try:
                r = requests.get(url, headers={"User-Agent": UA,
                                               "Accept-Language": "zh-CN,zh;q=0.9"},
                                 timeout=timeout)
            except requests.exceptions.SSLError as exc:
                # 证书链不完整的政务站直接放弃，不降级验证
                print(f"    ! TLS 握手失败，跳过：{str(exc)[:60]}", file=sys.stderr)
                return None
            if r.status_code == 200 and len(r.content) > 500:
                if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                    r.encoding = r.apparent_encoding
                return r.text
        except Exception as exc:  # noqa: BLE001 - 单源失败不应中断采集
            if i == retries:
                print(f"    ! {type(exc).__name__}: {str(exc)[:80]}", file=sys.stderr)
        time.sleep(1.2 * (i + 1))
    return None


TAG_RE = re.compile(r"<[^>]+>")
ENTITY_RE = re.compile(r"&#x?[0-9a-fA-F]+;")
PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")

# 单笔合同金额的合理上限（万元）：超过此值说明抽到的是市场统计数据而非合同金额
AMOUNT_CAP_WAN = 100_000.0


def strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html)).strip()


def clean_title(raw: str) -> str:
    """文库列表页的锚文本混了图标字体、浏览/下载计数和一个“下载文档”按钮。"""
    import html as htmllib

    text = htmllib.unescape(raw)
    text = ENTITY_RE.sub("", text)
    text = PRIVATE_USE_RE.sub("", text)  # 图标字体解码后的私用区字符
    text = re.split(r"下载文档|次下载|浏览|会员免费下载|会员卡券|会员专享", text)[0]
    text = re.sub(r"\s+", " ", text).strip(" ·•-—")
    # 尾部形如「会员卡券销售 589 509 」的计数残渣
    text = re.sub(r"\s+\d+(?:\s+\d+)*\s*$", "", text)
    return text[:160].strip()


def collect_203060(keyword: str, pages: int = 2, detail: bool = False) -> list[dict]:
    """双碳文库列表页：标题自带金额与项目名（如「【中标】碳核查98.9万-…」），适合做种子库。"""
    out: list[dict] = []
    for page in range(1, pages + 1):
        url = ("https://www.203060.com/plugin.php?ac=list&cate=0-0-0&id=keke_doc"
               f"&keyword={urllib.parse.quote(keyword)}&o=3&page={page}")
        html = http_get(url)
        if not html:
            break
        for m in re.finditer(r'<a href="(doc-view-\d+\.html)"[^>]*class="doc-mod[^"]*"[^>]*>(.*?)</a>',
                             html, re.S):
            href, inner = m.group(1), m.group(2)
            title = clean_title(strip_tags(inner))
            if len(title) < 8:
                continue
            rec = {
                "title": title,
                "url": f"https://www.203060.com/{href}",
                "source": "203060双碳文库",
                "evidence": title,
                "publish_date": "",
            }
            if detail:
                body, date = fetch_203060_detail(rec["url"])
                rec["publish_date"] = date or ""
                rec["evidence"] = f"{title} {body}"[:600]
            out.append(rec)
        time.sleep(1.0)
    return out


def fetch_203060_detail(url: str) -> tuple[str, str]:
    """详情页取发布日期与正文摘要（正文往往含采购人、中标人、金额）。"""
    html = http_get(url)
    if not html:
        return "", ""
    text = ENTITY_RE.sub("", strip_tags(html))
    pub = ""
    m = re.search(r"(?:发布时间|更新日期|时间)[:：]?\s*(20\d{2}[-/年]\d{1,2}[-/月]\d{1,2})", text)
    if m:
        pub = parse_date(m.group(1)) or ""
    if not pub:
        pub = parse_date(text[:2000]) or ""
    # 详情页偶尔抽到“截止日/下一年度”等异常年份，只保留不晚于今天的日期
    if pub and pub > date.today().isoformat():
        pub = ""
    return text[:900], pub


def collect_greenbid() -> list[dict]:
    """全国招投标领域绿色公共服务平台：公示类记录，企业名打码、无金额，用于监测"是否出现新项目"。"""
    html = http_get("http://greenbid.cn/")
    if not html:
        return []
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)[:60]:
        text = strip_tags(row)
        if len(text) < 15 or "项目编号" in text:
            continue
        out.append({
            "title": text[:160],
            "url": "http://greenbid.cn/",
            "source": "全国招投标绿色公共服务平台",
            "evidence": text[:400],
            "publish_date": parse_date(text) or "",
        })
    return out


SOURCES = {"203060": collect_203060, "greenbid": collect_greenbid}


# ---------------------------------------------------------------- 统计

DOC_NOISE = re.compile(r"白皮书|蓝皮书|年报$|趋势报告|研究报告|分析报告|智库|洞察|观察|案例集?|名单|目录|职位|手册|指南$|汇编|解读|政策汇总|题库|培训")


def is_tender(title: str) -> bool:
    """排除文库里的报告/白皮书/名单类文档，只留真正的招采公告。"""
    if kind_of(title) != "其他":
        return True
    return not DOC_NOISE.search(title)


def load(con: sqlite3.Connection, since: str | None, until: str | None) -> list[dict]:
    con.row_factory = sqlite3.Row
    cur = con.execute("SELECT * FROM tenders WHERE (:s IS NULL OR publish_date >= :s) AND (:u IS NULL OR publish_date <= :u)", {"s": since or None, "u": until or None})
    rows = [dict(r) for r in cur]
    return [r for r in rows if is_tender(r.get("title") or "")]


def money(rec: dict) -> float | None:
    try:
        v = float(rec.get("amount_wan") or 0)
        return v if 0 < v <= AMOUNT_CAP_WAN else None
    except (TypeError, ValueError):
        return None


def analyze(rows: list[dict]) -> dict:
    import statistics as st

    amounts = [money(r) for r in rows]
    got = [a for a in amounts if a]
    def agg(key: str) -> list[dict]:
        buckets: dict[str, dict] = {}
        for r in rows:
            k = (r.get(key) or "未标注").strip() or "未标注"
            b = buckets.setdefault(k, {"name": k, "n": 0, "amount": 0.0, "with_amount": 0})
            b["n"] += 1
            a = money(r)
            if a:
                b["amount"] += a
                b["with_amount"] += 1
        return sorted(buckets.values(), key=lambda x: (-x["amount"], -x["n"]))

    months: dict[str, dict] = {}
    for r in rows:
        d = (r.get("publish_date") or "")[:7]
        if not re.match(r"20\d{2}-\d{2}", d):
            continue
        b = months.setdefault(d, {"month": d, "n": 0, "amount": 0.0})
        b["n"] += 1
        a = money(r)
        if a:
            b["amount"] += a

    sizes = [("≤10万", 0, 10), ("10-30万", 10, 30), ("30-50万", 30, 50),
             ("50-100万", 50, 100), ("100-300万", 100, 300), ("300-1000万", 300, 1000),
             ("≥1000万", 1000, 1e9)]
    dist = [{"name": n, "n": sum(1 for a in got if lo < a <= hi)} for n, lo, hi in sizes]

    # 中标阶段单独统计：分析"中标情况"只能看已成交的公告，否则会用预算价高估
    award = [r for r in rows if r.get("kind") == "中标/成交"]
    a_got = [money(r) for r in award]
    a_got = [a for a in a_got if a]

    return {
        "n_total": len(rows),
        "n_award": len(award),
        "n_award_amount": len(a_got),
        "amount_award_sum": round(sum(a_got), 2),
        "amount_award_mean": round(st.mean(a_got), 2) if a_got else 0,
        "amount_award_median": round(st.median(a_got), 2) if a_got else 0,
        "n_with_amount": len(got),
        "amount_coverage": round(len(got) / len(rows) * 100, 1) if rows else 0.0,
        "amount_sum": round(sum(got), 2),
        "amount_mean": round(st.mean(got), 2) if got else 0,
        "amount_median": round(st.median(got), 2) if got else 0,
        "amount_p25": round(st.quantiles(got, n=4)[0], 2) if len(got) > 3 else 0,
        "amount_p75": round(st.quantiles(got, n=4)[2], 2) if len(got) > 3 else 0,
        "amount_max": round(max(got), 2) if got else 0,
        "by_category": agg("category"),
        "by_region": agg("region"),
        "by_buyer_type": agg("buyer_type"),
        "by_buyer": agg("buyer")[:15],
        "by_winner": agg("winner")[:15],
        "by_month": [months[k] for k in sorted(months)],
        "by_source": agg("source"),
        "size_dist": dist,
    }


# ---------------------------------------------------------------- 图表

def charts(stats: dict, assets: Path) -> dict[str, Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for name in ("Microsoft YaHei", "SimHei", "msyh.ttc", "SimSun"):
        try:
            font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [name]
            break
        except Exception as exc:  # noqa: BLE001 - 字体探测失败就退回默认字体
            print(f"    · 字体 {name} 不可用（{type(exc).__name__}），试下一个", file=sys.stderr)
            continue
    plt.rcParams["axes.unicode_minus"] = False
    assets.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    ink, accent = "#1f2937", "#0e7490"

    mon = stats["by_month"]
    if len(mon) > 1:
        fig, ax = plt.subplots(figsize=(10, 3.6), dpi=150)
        xs = [m["month"] for m in mon]
        ax.bar(xs, [m["n"] for m in mon], color="#bae6fd", label="公告数")
        ax.set_ylabel("公告数（条）")
        ax2 = ax.twinx()
        ax2.plot(xs, [m["amount"] for m in mon], color=accent, marker="o", lw=2, label="中标金额")
        ax2.set_ylabel("中标金额（万元）")
        ax.set_title("月度招标/中标数量与金额", color=ink, fontsize=12)
        ax.tick_params(axis="x", rotation=45, labelsize=7)
        fig.tight_layout()
        p = assets / "t_month.png"
        fig.savefig(p)
        plt.close(fig)
        out["month"] = p

    cat = stats["by_category"][:10][::-1]
    if cat:
        fig, ax = plt.subplots(figsize=(7.5, 3.6), dpi=150)
        ax.barh([c["name"] for c in cat], [c["n"] for c in cat], color=accent)
        for i, c in enumerate(cat):
            ax.text(c["n"], i, f" {c['n']}条/{c['amount']:.0f}万", va="center", fontsize=7)
        ax.set_title("细分赛道：公告数与金额", color=ink, fontsize=12)
        fig.tight_layout()
        p = assets / "t_category.png"
        fig.savefig(p)
        plt.close(fig)
        out["category"] = p

    dist = [d for d in stats["size_dist"] if d["n"]]
    if dist:
        fig, ax = plt.subplots(figsize=(7, 3.2), dpi=150)
        ax.bar([d["name"] for d in dist], [d["n"] for d in dist], color="#f59e0b")
        ax.set_title("中标金额区间分布（有金额项目）", color=ink, fontsize=12)
        ax.tick_params(axis="x", labelsize=8)
        fig.tight_layout()
        p = assets / "t_size.png"
        fig.savefig(p)
        plt.close(fig)
        out["size"] = p

    reg = [r for r in stats["by_region"] if r["name"] not in ("全国/未标注",)][:10][::-1]
    if reg:
        fig, ax = plt.subplots(figsize=(7, 3.4), dpi=150)
        ax.barh([r["name"] for r in reg], [r["n"] for r in reg], color="#0f766e")
        ax.set_title("区域分布（Top10，按条数）", color=ink, fontsize=12)
        fig.tight_layout()
        p = assets / "t_region.png"
        fig.savefig(p)
        plt.close(fig)
        out["region"] = p
    return out


# ---------------------------------------------------------------- 报告渲染

def md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    return "\n".join(out)


def build_report(rows: list[dict], stats: dict, meta: dict, imgs: dict[str, Path],
                 img_prefix: str = "") -> str:
    s = stats
    L: list[str] = []
    L.append(f"# {meta['title']}\n")
    L.append(f"> 统计口径：{meta['since']} 至 {meta['until']}｜样本 {s['n_total']} 条"
             f"（其中中标/成交 {s['n_award']} 条，有明确金额 {s['n_with_amount']} 条，"
             f"覆盖率 {s['amount_coverage']}%）"
             f"｜生成时间 {datetime.now():%Y-%m-%d %H:%M}\n")

    L.append("## 一、核心结论（TL;DR）\n")
    for line in meta.get("tldr", []):
        L.append(f"- {line}")
    L.append("")

    L.append("## 二、市场规模与节奏\n")
    L.append(md_table(["指标", "全样本", "仅中标/成交阶段"], [
        ["公告数", f"{s['n_total']} 条", f"{s['n_award']} 条"],
        ["披露金额项目数", f"{s['n_with_amount']} 条（{s['amount_coverage']}%）",
         f"{s['n_award_amount']} 条"],
        ["金额合计", f"{s['amount_sum']:,.1f} 万元", f"{s['amount_award_sum']:,.1f} 万元"],
        ["单项目均值", f"{s['amount_mean']:,.1f} 万元", f"{s['amount_award_mean']:,.1f} 万元"],
        ["单项目中位数", f"{s['amount_median']:,.1f} 万元", f"{s['amount_award_median']:,.1f} 万元"],
        ["P25 / P75", f"{s['amount_p25']:,.1f} / {s['amount_p75']:,.1f} 万元", "—"],
        ["单项目最高", f"{s['amount_max']:,.1f} 万元", "—"],
    ]))
    L.append("")
    if "month" in imgs:
        L.append(f"![月度节奏]({img_prefix}{imgs['month'].name})\n")
    L.append(meta.get("market_reading", "\n"))
    L.append("")

    L.append("## 三、热点赛道分布\n")
    L.append(md_table(["赛道", "公告数", "金额合计(万元)", "单项目均值(万元)"], [
        [c["name"], c["n"], f"{c['amount']:,.1f}",
         f"{c['amount']/c['with_amount']:,.1f}" if c["with_amount"] else "-"]
        for c in s["by_category"]]))
    L.append("")
    if "category" in imgs:
        L.append(f"![赛道]({img_prefix}{imgs['category'].name})\n")
    L.append(meta.get("category_reading", "\n"))
    L.append("")

    L.append("## 四、金额分布与价格带\n")
    if "size" in imgs:
        L.append(f"![金额区间]({img_prefix}{imgs['size'].name})\n")
    L.append(md_table(["金额区间", "项目数"], [[d["name"], d["n"]] for d in s["size_dist"]]))
    L.append("")
    L.append(meta.get("price_reading", "\n"))
    L.append("")

    L.append("## 五、谁在买：采购人结构\n")
    L.append(md_table(["采购人类型", "公告数", "金额合计(万元)"], [
        [b["name"], b["n"], f"{b['amount']:,.1f}"] for b in s["by_buyer_type"]]))
    L.append("")
    if s["by_buyer"]:
        L.append(md_table(["采购人（Top15）", "公告数", "金额合计(万元)"], [
            [b["name"], b["n"], f"{b['amount']:,.1f}"] for b in s["by_buyer"] if b["name"] != "未标注"]))
    L.append("")
    L.append(meta.get("buyer_reading", "\n"))
    L.append("")

    L.append("## 六、谁在赢：中标供应商格局\n")
    real_winners = [b for b in s["by_winner"]
                    if b["name"] not in ("未标注",) and not b["name"].startswith("未公开")]
    if real_winners:
        L.append(md_table(["中标人（可识别）", "中标数", "金额合计(万元)"], [
            [b["name"], b["n"], f"{b['amount']:,.1f}"] for b in real_winners]))
    L.append("")
    L.append(meta.get("winner_reading", "\n"))
    L.append("")

    L.append("## 七、区域分布\n")
    if "region" in imgs:
        L.append(f"![区域]({img_prefix}{imgs['region'].name})\n")
    L.append(md_table(["地区", "公告数", "金额合计(万元)"], [
        [b["name"], b["n"], f"{b['amount']:,.1f}"] for b in s["by_region"]]))
    L.append("")
    L.append(meta.get("region_reading", "\n"))
    L.append("")

    L.append("## 八、明细清单（可溯源）\n")
    L.append(md_table(["日期", "项目", "采购人", "中标人", "金额(万元)", "赛道", "地区"], [
        [r.get("publish_date") or "-", (r.get("title") or "")[:58], (r.get("buyer") or "-")[:20],
         (r.get("winner") or "-")[:20],
         f"{money(r):,.2f}" if money(r) else "未披露",
         r.get("category") or "-", r.get("region") or "-"]
        for r in sorted(rows, key=lambda x: (x.get("publish_date") or ""), reverse=True)]))
    L.append("")

    L.append("## 九、机会判断与行动建议\n")
    L.append(meta.get("actions", "\n"))
    L.append("")

    L.append("## 十、数据来源与口径说明\n")
    L.append(md_table(["来源", "记录数", "说明"], [
        [b["name"], b["n"], meta.get("source_note", {}).get(b["name"], "公开招标/中标公告")]
        for b in s["by_source"]]))
    L.append("")
    L.append(meta.get("caveat", ""))
    L.append("")
    return "\n".join(L)


CSS = """
:root{--ink:#0f172a;--sub:#475569;--line:#e2e8f0;--accent:#0e7490;--bg:#fff}
*{box-sizing:border-box}
body{margin:0;background:#f1f5f9;color:var(--ink);
 font:15px/1.75 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.page{max-width:1000px;margin:0 auto;background:var(--bg);padding:56px 64px;
 box-shadow:0 1px 3px rgba(15,23,42,.09)}
h1{font-size:27px;line-height:1.35;margin:0 0 10px;letter-spacing:-.3px}
h2{font-size:19px;margin:38px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--line)}
h3{font-size:16px;margin:22px 0 8px}
blockquote{margin:0 0 22px;padding:12px 16px;background:#f8fafc;border-left:3px solid var(--accent);
 color:var(--sub);font-size:13px;border-radius:0 6px 6px 0}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:13px}
th{background:#f8fafc;text-align:left;font-weight:600;color:#334155}
th,td{border:1px solid var(--line);padding:7px 10px;vertical-align:top}
tbody tr:nth-child(even){background:#fcfdff}
img{max-width:100%;border:1px solid var(--line);border-radius:8px;margin:10px 0}
code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12.5px}
ul{padding-left:22px}li{margin:5px 0}
a{color:var(--accent);text-decoration:none}
"""


def to_html(md: str, title: str, out: Path, img_dir: Path) -> None:
    """极简 markdown -> html，够用即可（标题/表格/图片/列表/引用/粗体）。"""
    import base64
    import html as htmllib

    lines, i = md.split("\n"), 0
    body: list[str] = []
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            head = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            body.append("<table><thead><tr>" + "".join(f"<th>{htmllib.escape(c)}</th>" for c in head)
                        + "</tr></thead><tbody>"
                        + "".join("<tr>" + "".join(f"<td>{htmllib.escape(c)}</td>" for c in r) + "</tr>"
                                  for r in rows) + "</tbody></table>")
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", ln)
        if m:
            body.append(f"<h{len(m.group(1))}>{htmllib.escape(m.group(2))}</h{len(m.group(1))}>")
            i += 1
            continue
        m = re.match(r"^!\[(.*?)\]\((.+?)\)\s*$", ln)
        if m:
            p = (out.parent / m.group(2)) if not os.path.isabs(m.group(2)) else Path(m.group(2))
            if not p.exists():
                p = img_dir / Path(m.group(2)).name
            if p.exists():
                b64 = base64.b64encode(p.read_bytes()).decode()
                body.append(f'<figure><img alt="{htmllib.escape(m.group(1))}" '
                            f'src="data:image/png;base64,{b64}"></figure>')
            i += 1
            continue
        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip("> "))
                i += 1
            body.append(f"<blockquote>{htmllib.escape(' '.join(buf))}</blockquote>")
            continue
        if re.match(r"^[-*]\s+", ln):
            buf = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i]):
                buf.append(lines[i][2:])
                i += 1
            body.append("<ul>" + "".join(f"<li>{inline(x, htmllib)}</li>" for x in buf) + "</ul>")
            continue
        if not ln.strip():
            i += 1
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,4}\s|!\[|\||>|[-*]\s)", lines[i]):
            buf.append(lines[i])
            i += 1
        body.append(f"<p>{inline(' '.join(buf), htmllib)}</p>")

    out.write_text(
        f"<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{htmllib.escape(title)}</title><style>{CSS}</style></head>"
        f"<body><div class=\"page\">{''.join(body)}</div></body></html>", encoding="utf-8")


def inline(text: str, htmllib) -> str:
    text = htmllib.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


# ---------------------------------------------------------------- push

def build_push(rows: list[dict], meta: dict) -> str:
    L = [f"# {meta['title']}\n",
         f"> {meta['date']}｜新增 {len(rows)} 条｜来源：{meta.get('sources', '多源聚合')}\n"]
    if not rows:
        L.append("今日无新增 ESG / 双碳相关招采公告。\n")
        return "\n".join(L)
    hot = [r for r in rows if (money(r) or 0) >= 50]
    if hot:
        L.append("## 优先关注（预估/中标金额 ≥ 50 万）\n")
        for r in hot:
            L.append(f"- **{r['title']}**")
            L.append(f"  - 金额 {money(r):,.2f} 万元｜{r.get('category')}｜{r.get('region')}"
                     f"｜{r.get('publish_date')}\n")
    L.append("## 全部新增\n")
    L.append(md_table(["日期", "项目", "赛道", "地区", "金额(万元)", "链接"], [
        [r.get("publish_date") or "-", (r.get("title") or "")[:60], r.get("category") or "-",
         r.get("region") or "-", f"{money(r):,.2f}" if money(r) else "-",
         f"[原文]({r.get('url')})" if r.get("url") else "-"] for r in rows]))
    L.append("")
    L.append(meta.get("note", ""))
    return "\n".join(L)


# ---------------------------------------------------------------- CLI

def cmd_collect(a) -> None:
    fn = SOURCES[a.source]
    kws = a.kw or ["ESG", "碳核查", "碳足迹", "双碳", "可持续发展报告"]
    all_recs: list[dict] = []
    for kw in kws:
        if a.source == "203060":
            recs = fn(kw, a.pages, a.detail)
        else:
            recs = fn()
        print(f"  {a.source} · {kw}: {len(recs)} 条", file=sys.stderr)
        all_recs.extend(recs)
    if a.print_only:
        print(json.dumps(all_recs, ensure_ascii=False, indent=1))
        return
    con = connect(Path(a.db))
    new, dup = upsert(con, all_recs)
    print(f"入库完成：新增 {new} 条，已存在 {dup} 条 → {a.db}")


def cmd_ingest(a) -> None:
    recs: list[dict] = []
    for pattern in a.files:
        for f in glob.glob(pattern):
            text = Path(f).read_text(encoding="utf-8")
            data = None
            if f.endswith(".json"):
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as exc:
                    print(f"  ! 跳过 {f}：JSON 解析失败（{exc}）", file=sys.stderr)
                    continue
            if data is None:
                import csv
                data = list(csv.DictReader(text.splitlines()))
            if isinstance(data, dict):
                data = data.get("records", data.get("items", []))
            for r in data:
                r["source"] = r.get("source") or Path(f).stem
            recs.extend(data)
            print(f"  读取 {f}: {len(data)} 条", file=sys.stderr)
    con = connect(Path(a.db))
    new, dup = upsert(con, recs)
    print(f"入库完成：新增 {new} 条，重复 {dup} 条 → {a.db}")


def cmd_analyze(a) -> None:
    con = connect(Path(a.db))
    rows = load(con, a.since, a.until)
    stats = analyze(rows)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.assets:
        imgs = charts(stats, Path(a.assets))
        print("图表：" + ", ".join(p.name for p in imgs.values()))
    print(json.dumps({k: v for k, v in stats.items()
                      if not isinstance(v, list)}, ensure_ascii=False, indent=1))


def cmd_report(a) -> None:
    con = connect(Path(a.db))
    rows = load(con, a.since, a.until)
    stats = analyze(rows)
    assets = Path(a.assets)
    imgs = charts(stats, assets)
    try:
        meta = json.loads(Path(a.meta).read_text(encoding="utf-8")) if a.meta else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"--meta 读取失败：{exc}") from exc
    meta.setdefault("title", "ESG 招投标情报分析报告")
    meta.setdefault("since", a.since or "-")
    meta.setdefault("until", a.until or date.today().isoformat())
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # md 里的图片路径要相对于 md 所在目录，单独打开 md 时图也能显示
    try:
        prefix = os.path.relpath(assets, out.parent).replace("\\", "/") + "/"
    except ValueError:
        prefix = ""
    md = build_report(rows, stats, meta, imgs, prefix)
    out.write_text(md, encoding="utf-8")
    if a.html:
        to_html(md, meta["title"], Path(a.html), assets)
        print(f"HTML → {a.html}")
    print(f"Markdown → {out}（{len(rows)} 条样本）")


def cmd_push(a) -> None:
    con = connect(Path(a.db))
    since = (date.today() - timedelta(days=a.days)).isoformat()
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM tenders WHERE pushed='0'")]
    rows = [r for r in rows
            if (r.get("publish_date") or "") >= since and is_tender(r.get("title") or "")]
    rows.sort(key=lambda r: (r.get("publish_date") or ""), reverse=True)
    meta = {"title": f"ESG/双碳 招标日报 · {date.today():%Y-%m-%d}", "date": f"自 {since} 起",
            "note": "\n> 推送口径：仅推送库中未推送过的记录，重复运行不会重复打扰。\n"}
    md = build_push(rows, meta)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    for r in rows:
        con.execute("UPDATE tenders SET pushed='1' WHERE uid=?", (r["uid"],))
    con.commit()
    print(f"推送摘要 → {out}（{len(rows)} 条，已标记 pushed=1）")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ESG 招投标情报引擎")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="在线抓取公开聚合站点")
    c.add_argument("--source", default="203060", choices=list(SOURCES))
    c.add_argument("--kw", nargs="*", help="关键词，可多个")
    c.add_argument("--pages", type=int, default=2)
    c.add_argument("--detail", action="store_true", help="额外抓详情页补日期/正文")
    c.add_argument("--print-only", action="store_true")
    c.set_defaults(func=cmd_collect)

    g = sub.add_parser("ingest", help="把采集好的 JSON/CSV 入库去重")
    g.add_argument("files", nargs="+")
    g.set_defaults(func=cmd_ingest)

    an = sub.add_parser("analyze", help="统计并出图")
    an.add_argument("--since")
    an.add_argument("--until")
    an.add_argument("--assets")
    an.add_argument("--json-out")
    an.set_defaults(func=cmd_analyze)

    r = sub.add_parser("report", help="生成分析报告 md/html")
    r.add_argument("--since")
    r.add_argument("--until")
    r.add_argument("--assets", default=str(SKILL_DIR / "reports" / "assets"))
    r.add_argument("--meta", help="解读文案 JSON（TL;DR/结论/建议）")
    r.add_argument("--out", required=True)
    r.add_argument("--html")
    r.set_defaults(func=cmd_report)

    p = sub.add_parser("push", help="每日新增推送摘要")
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_push)

    a = ap.parse_args(argv)
    a.func(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
