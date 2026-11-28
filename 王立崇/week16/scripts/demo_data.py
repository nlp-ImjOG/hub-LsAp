"""离线演示数据：在无网络 / 无 API Key 时替换「搜索」与「LLM 摘要」，用于跑通全流程。

注意：这些条目是**演示样例**，时间与金额为说明性示例；真实运行时由 web_search 联网获取。
"""
from __future__ import annotations

# 案例1：ESG 月报 —— 按报告章节组织的检索结果（title/url/snippet）
MONTHLY_SEARCH_RESULTS: dict[str, list[dict[str, str]]] = {
    "政策标准": [
        {
            "title": "沪深北交易所《上市公司可持续发展报告指引》",
            "url": "https://www.sse.com.cn/",
            "snippet": "上交所、深交所、北交所发布可持续发展报告指引，上证180、科创50、深证100、创业板指样本及境内外同时上市公司为首批强制披露主体，需按规定编制并披露可持续发展报告。",
        },
        {
            "title": "财政部等九部门《企业可持续披露准则——基本准则（试行）》",
            "url": "https://www.mof.gov.cn/",
            "snippet": "构建中国企业可持续披露准则体系，基本准则对标 ISSB 的 IFRS S1/S2，明确披露框架、重要性原则与四要素，为后续具体准则奠定基础。",
        },
        {
            "title": "全国碳市场扩容：钢铁、水泥、铝冶炼行业纳入碳排放权交易",
            "url": "https://www.mee.gov.cn/",
            "snippet": "全国碳市场由发电行业扩容至钢铁、水泥、铝冶炼三大高耗能行业，管控排放量进一步提升，碳价信号向更多行业传导。",
        },
    ],
    "行业动态": [
        {
            "title": "煤炭行业绿色矿山与智能化建设持续推进",
            "url": "https://www.coalchina.org.cn/",
            "snippet": "煤矿智能化工作面数量持续增长，5G+工业互联网在矿井应用普及，绿色矿山入选数量增加，行业向安全高效绿色转型。",
        },
        {
            "title": "煤电'三改联动'：节能降碳、灵活性、供热改造加速",
            "url": "https://www.ndrc.gov.cn/",
            "snippet": "煤电行业推进节能降碳改造、灵活性改造与供热改造'三改联动'，提升新能源消纳能力，降低度电煤耗与碳排放。",
        },
        {
            "title": "煤矿瓦斯（煤层气）抽采利用与甲烷减排",
            "url": "https://www.nea.gov.cn/",
            "snippet": "瓦斯抽采利用与甲烷排放控制成为煤炭行业减排重点，抽采量、利用率提升，减少直接排放与矿难风险。",
        },
    ],
    "客户公司": [
        {
            "title": "中国神华发布年度可持续发展（ESG）报告",
            "url": "https://www.shenhuachina.com/",
            "snippet": "中国神华连续多年披露 ESG/可持续发展报告，系统披露碳排放、绿色矿山、智能化、安全环保与公司治理等议题及量化数据。",
        },
        {
            "title": "中国神华锦界 CCUS 示范项目稳定运行",
            "url": "https://www.shenhuachina.com/",
            "snippet": "15万吨/年燃煤电厂二氧化碳捕集与封存（CCUS）示范项目持续运行，为煤电低碳改造提供技术验证与经验积累。",
        },
        {
            "title": "中国神华采煤沉陷区光伏项目建设推进",
            "url": "https://www.shenhuachina.com/",
            "snippet": "在采煤沉陷区布局集中式光伏，推动'光伏+生态修复'，拓展新能源业务，优化电源结构与碳排放强度。",
        },
    ],
    "对标企业": [
        {
            "title": "兖矿能源推进绿色矿山与新能源转型",
            "url": "https://www.yankuang.com/",
            "snippet": "兖矿能源加快智能化开采与新能源布局，强化 ESG 治理与披露，提升评级与市场认可度。",
        },
        {
            "title": "陕西煤业提升 ESG 评级并优化资本结构",
            "url": "https://www.shxcoal.com/",
            "snippet": "陕西煤业通过分红、治理优化与绿色转型，入选多个 ESG 指数，机构关注度提升。",
        },
        {
            "title": "中煤能源发布双碳行动方案并加大 CCUS 投入",
            "url": "https://www.chinacoal.com/",
            "snippet": "中煤能源明确碳达峰路径，布局 CCUS 与新能源，完善碳管理体系。",
        },
    ],
}

# 案例2：ESG / 可持续发展 / 双碳 相关中标记录（演示样例）
BID_RECORDS: list[dict[str, str]] = [
    {"title": "某省属能源集团2025年度可持续发展（ESG）报告编制咨询服务项目", "buyer": "省属能源集团", "amount": "48", "unit": "万元", "date": "2025-06-12", "category": "ESG报告编制"},
    {"title": "某央企集团碳达峰碳中和行动方案编制与碳管理体系建设", "buyer": "中央企业", "amount": "180", "unit": "万元", "date": "2025-03-20", "category": "双碳方案"},
    {"title": "某上市公司ESG评级提升与治理咨询项目", "buyer": "上市公司", "amount": "65", "unit": "万元", "date": "2024-11-08", "category": "ESG评级咨询"},
    {"title": "某制造业企业产品碳足迹核算与CBAM应对咨询", "buyer": "制造企业", "amount": "32", "unit": "万元", "date": "2025-05-30", "category": "碳足迹"},
    {"title": "某地市重点排放单位碳排放核查（碳盘查）服务", "buyer": "地方政府", "amount": "15", "unit": "万元", "date": "2024-09-14", "category": "碳核查"},
    {"title": "某银行绿色金融与ESG数据平台建设项目", "buyer": "银行", "amount": "260", "unit": "万元", "date": "2025-07-02", "category": "ESG数据平台"},
    {"title": "某电力集团CCER项目开发与碳资产管理服务", "buyer": "电力集团", "amount": "95", "unit": "万元", "date": "2025-04-18", "category": "碳资产开发"},
    {"title": "某开发区绿色工厂与绿色供应链创建辅导", "buyer": "开发区管委会", "amount": "28", "unit": "万元", "date": "2024-12-05", "category": "绿色认证"},
    {"title": "某央企双碳人才培训与碳管理能力建设", "buyer": "中央企业", "amount": "12", "unit": "万元", "date": "2025-02-11", "category": "双碳培训"},
    {"title": "某市气候投融资与ESG信息披露平台咨询", "buyer": "地方政府", "amount": "120", "unit": "万元", "date": "2025-08-22", "category": "气候投融资"},
]

# 案例2：每日推送的当日新增样例（演示稿，实际由联网检索 + seen_bids.json 去重产生）
DAILY_RECORDS: list[dict[str, str]] = [
    {"title": "某上市公司2026年度可持续发展报告编制与鉴证服务", "buyer": "上市公司", "amount": "56", "unit": "万元", "date": "2026-11-27", "category": "ESG报告编制"},
    {"title": "某园区企业碳排放核查与碳管理数字化建设", "buyer": "开发区管委会", "amount": "30", "unit": "万元", "date": "2026-11-27", "category": "碳核查"},
]
