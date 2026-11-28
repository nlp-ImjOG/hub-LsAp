"""端到端 demo:用合成数据注入 search/fetch,跑通两条流水线生成示例报告。

说明:本机网络无法访问 DuckDuckGo(被墙),ddgs 默认后端不可用。
为演示"脚本流水线端到端产出报告",此处用 monkeypatch 注入合成
SearchResult 与正文,验证 检索→去重→抓取→总结→套模板→落盘 的完整链路。
生产环境把 search/fetch 换成真实后端(Tavily 或自建 Bing/Baidu 抓取)即可。

跑法:.venv/bin/python scripts/demo_gen.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import esg_monthly.pipeline as mp
import esg_bidding.pipeline as bp
from common import SearchResult
from esg_monthly.queries import MonthlyParams

# --- 合成搜索结果 ---
MOCK_RESULTS = {
    "ESG 政策 2026-10": [
        SearchResult("生态环境部发布2026年碳市场扩围方案", "https://www.gov.cn/zhengce/202610.htm",
                     "生态环境部10月发布全国碳市场扩围方案,纳入水泥、钢铁、电解铝行业。"),
        SearchResult("证监会更新上市公司可持续发展报告指引", "https://www.csrc.gov.cn/pub/esg2026.htm",
                     "证监会10月修订可持续发展报告指引,强化范围三披露要求。"),
    ],
    "ISSB IFRS S1 S2 更新": [
        SearchResult("ISSB发布范围三排放计量实务指南", "https://www.ifrs.org/issb/range3.htm",
                     "ISSB发布范围三排放计量实务指南,提升可比性。"),
    ],
    "煤炭 ESG 2026-10": [
        SearchResult("煤炭行业ESG转型白皮书发布", "https://www.caixin.com/coal-esg.htm",
                     "中国煤炭工业协会发布煤炭行业ESG转型白皮书,提出公正转型路径。"),
    ],
    '"陕西煤业" ESG 2026-10': [
        SearchResult("陕西煤业发布三季度ESG进展", "https://www.cninfo.com.cn/sxcoal-esg.htm",
                     "陕西煤业披露三季度绿电占比提升至12%,矿区生态修复投入增加。"),
    ],
    '"中国神华" ESG': [
        SearchResult("中国神华MSCI ESG评级升至BBB", "https://www.msci.com/shenhua.htm",
                     "中国神华MSCI ESG评级升至BBB,系煤炭行业最高。"),
        SearchResult("中国神华2026可持续发展报告要点", "https://www.shenhua.com/esg2026.htm",
                     "中国神华发布2026可持续发展报告,设定2030碳达峰、矿区生态修复全覆盖。"),
    ],
}
DEFAULT = [
    SearchResult("ESG相关动态示例", "https://www.gov.cn/demo.htm", "ESG示例摘要内容。"),
]

MOCK_PAGES = {
    "https://www.gov.cn/zhengce/202610.htm": "生态环境部2026年10月发布全国碳排放权交易市场扩围方案。方案将水泥、钢铁、电解铝三个高排放行业纳入全国碳市场,预计覆盖排放量增加约30亿吨。对煤炭行业而言,下游钢铁需求受碳成本传导,短期承压,长期利好低碳转型领先企业。",
    "https://www.csrc.gov.cn/pub/esg2026.htm": "证监会2026年10月修订《上市公司可持续发展报告指引》,强化范围三温室气体排放披露,要求重点排污单位2027年起强制披露,其他公司鼓励披露。对煤炭上市公司披露合规压力上升。",
    "https://www.ifrs.org/issb/range3.htm": "ISSB发布范围三排放计量实务指南,统一价值链排放计算口径,提升跨企业可比性。煤炭企业范围三(下游燃煤)占排放主体,指南落地后将显著影响披露质量。",
    "https://www.caixin.com/coal-esg.htm": "中国煤炭工业协会发布《煤炭行业ESG转型白皮书》,提出公正转型、矿区生态修复、瓦斯综合利用、关停矿井人员安置四大路径。建议煤炭企业设定科学碳目标并披露公正转型计划。",
    "https://www.cninfo.com.cn/sxcoal-esg.htm": "陕西煤业2026年三季度ESG进展:绿电占比提升至12%,新增光伏装机200MW;矿区生态修复投入1.2亿元;范围一碳排放强度同比下降3%。董事会ESG委员会第二季度成立。仍缺范围三披露与科学碳目标。",
    "https://www.msci.com/shenhua.htm": "中国神华MSCI ESG评级升至BBB,为全球煤炭行业最高。评级提升得益于治理架构完善、碳目标清晰与矿区生态修复领先。",
    "https://www.shenhua.com/esg2026.htm": "中国神华2026可持续发展报告:设定2030年碳达峰、2060碳中和目标;范围三披露完整并经第三方鉴证;矿区生态修复覆盖率100%;建成全球首个亿吨级绿色矿区;员工工伤率行业最低。",
}


def fake_search(query, max_results=None, use_cache=True):
    return list(MOCK_RESULTS.get(query, DEFAULT))


def fake_fetch(url, use_cache=True):
    return MOCK_PAGES.get(url, "ESG相关示例正文,含政策、行业与公司动态要点。")


def main():
    # 注入
    mp.search = fake_search
    mp.fetch_text = fake_fetch
    bp.search = fake_search
    bp.fetch_text = fake_fetch

    out = Path(__file__).resolve().parent.parent / "examples"
    out.mkdir(parents=True, exist_ok=True)

    p = MonthlyParams(client="陕西煤业", industry="煤炭", year_month="2026-10", benchmark="中国神华")
    path, metrics = mp.run(p, out)
    print("[月报] 生成:", path)
    print("  指标:", metrics.__dict__)

    # bidding aggregate 也注入(数据少,仅演示链路)
    path2, metrics2, stats2 = bp.aggregate(out, max_queries=2)
    print("[汇总] 生成:", path2)
    print("  指标:", metrics2.__dict__)


if __name__ == "__main__":
    main()
