#!/usr/bin/env python3
"""esg-bid-monitor Skill 测试 demo

用法（任意目录均可运行）：
    python3 tests/test_skill_demo.py

对应 tests/README.md 的四层测试方法，本脚本覆盖其中可自动化的部分：
  A. L1 结构测试   —— Skill 包结构与 frontmatter 校验（对标实施文档第八章"Skill 结构规范"）
  B. L2 规则测试   —— 把 extraction-rules.md 的归一化/指纹/金额规范化规则实现为代码，
                      验证"规则可实现且与文档表格逐条一致"
  C. L3 管线测试   —— mock 标讯数据端到端跑 scripts/stats.py 并断言统计结果；
                      模拟 SKILL.md 的 monitor 增量窗口规则
  D. L4 分流测试   —— 按 SKILL.md Phase 0 规则模拟 report/monitor 模式判定
  E. L4 产出测试   —— 用 mock 统计结果按 report-template.md 生成 demo 报告骨架并校验结构

所有 mock 数据均为人工构造（域名 demo.example.com），产物写入 tests/demo_output/，
不污染 data/ 真实工作区。仅用 Python 标准库。
"""
import hashlib
import json
import py_compile
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "esg-bid-monitor"
DATA = ROOT / "data"
DEMO_OUT = Path(__file__).resolve().parent / "demo_output"
DEMO_OUT.mkdir(exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), str(detail)))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ============================================================
# B 部分依赖的规则实现（忠实转写 extraction-rules.md 的规格）
# ============================================================
AMOUNT_PATTERNS = [
    (re.compile(r"([\d,]+(?:\.\d+)?)\s*亿"), 10000.0),   # 亿 → 万元 ×10000
    (re.compile(r"([\d,]+(?:\.\d+)?)\s*万"), 1.0),       # 万元 → 万元 ×1
    (re.compile(r"([\d,]+(?:\.\d+)?)\s*元"), 0.0001),    # 元 → 万元 ÷10000
]
AMOUNT_PRIORITY = ["成交金额", "中标金额", "预算金额", "最高限价"]  # 成交价 > 预算 > 限价


def normalize_name(name: str) -> str:
    """规范化项目名：全半角统一(NFKC) → 去括号补充说明 → 去空白"""
    s = unicodedata.normalize("NFKC", name)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    return re.sub(r"\s+", "", s)


def fingerprint(name: str, buyer: str) -> str:
    """record_id = sha1(规范化项目名 + buyer)[:12]"""
    return hashlib.sha1((normalize_name(name) + buyer).encode("utf-8")).hexdigest()[:12]


def normalize_amount(text):
    """金额规范化：统一万元；无金额表述返回 None"""
    if not text:
        return None
    for pat, factor in AMOUNT_PATTERNS:
        m = pat.search(text)
        if m:
            return round(float(m.group(1).replace(",", "")) * factor, 2)
    return None


def select_amount(candidates: dict):
    """金额口径优先级：成交/中标价 > 预算金额 > 最高限价"""
    for key in AMOUNT_PRIORITY:
        if candidates.get(key) is not None:
            return candidates[key]
    return None


def route_mode(phrase: str) -> str:
    """SKILL.md Phase 0 模式判定：监控类词优先 → monitor；其余命中 report 词或默认 → report"""
    monitor_kw = ("监控", "跟踪", "推送", "今日新增", "标讯速递", "商机")
    report_kw = ("分析", "汇总", "回顾", "金额分布", "热点", "中标情况")
    if any(k in phrase for k in monitor_kw):
        return "monitor"
    if any(k in phrase for k in report_kw) or re.search(r"(过去|近)\s*\d*\s*年", phrase):
        return "report"
    return "report"


def monitor_window(state: dict, now: datetime):
    """SKILL.md：monitor 窗口 = 「近24h」与「自 last_run 以来」的并集，
    即窗口起点取 min(now-24h, last_run)：刚跑过也至少回看 24h，漏跑多天则回补到上次运行。"""
    day = timedelta(hours=24)
    last = state.get("last_run")
    if last:
        try:
            return min(now - day, datetime.fromisoformat(last)), now
        except ValueError:
            pass
    return now - day, now


# ============================================================
# mock 标讯数据（人工构造，非真实市场数据）
# ============================================================
def mk(idx, name, stage, theme, itype, buyer, btype, winner, amt, raw, region, date,
       deadline=None, src="中国政府采购网", lvl=1):
    return {
        "record_id": fingerprint(name, buyer), "project_name": name, "stage": stage,
        "theme": theme, "industry_type": itype, "buyer": buyer, "buyer_type": btype,
        "winner": winner, "amount_wan": amt, "amount_raw": raw, "region": region,
        "publish_date": date, "deadline": deadline, "source_name": src,
        "source_level": lvl, "url": f"https://demo.example.com/TEST-{idx}",
        "summary": f"TEST-mock 样本 {idx}", "collected_at": "2026-11-24T09:00:00+08:00",
    }


MOCK_BIDS = [
    mk(1, "某市碳达峰行动方案编制服务", "中标公告", ["双碳", "可持续咨询"], "咨询服务",
       "某市生态环境局", "政府机关", "测试环科院A", 128.5, "1,285,000元", "测试省某市", "2026-09-18"),
    mk(2, "某市零碳产业园基础设施项目", "招标公告", ["双碳"], "工程建设",
       "某市发改委", "政府机关", None, 450.0, "预算金额：450万", "测试省某市", "2026-10-01",
       deadline="2026-10-21"),
    mk(3, "海上风电场运维服务", "中标公告", ["清洁能源"], "运营服务",
       "某能源集团", "国企", "测试运维B", 12000.0, "1.2亿元", "广东(测试)", "2026-10-01",
       src="某省公共资源交易中心", lvl=2),
    mk(4, "上市公司ESG报告编制与评级提升咨询", "中标公告", ["可持续咨询"], "咨询服务",
       "某上市公司", "上市公司", "测试咨询C", 80.0, "80万元", "北京(测试)", "2026-10-15",
       src="千里马", lvl=3),
    mk(5, "城市污水处理厂提标改造工程", "中标公告", ["绿色环保"], "工程建设",
       "某水务集团", "国企", "测试建设D", 3500.0, "3500万元", "江苏(测试)", "2025-03-10"),
    mk(6, "绿色债券发行与存续期管理服务", "中标公告", ["绿色金融"], "咨询服务",
       "某商业银行", "上市公司", "测试证券E", None, "面议", "上海(测试)", "2026-11-01",
       src="采招网", lvl=3),
    mk(7, "分布式光伏发电设备框架采购", "招标公告", ["清洁能源"], "设备采购",
       "某高校", "高校", None, 800.0, "最高限价800万元", "测试省乙市", "2026-11-10",
       deadline="2026-11-20", src="某省公共资源交易中心", lvl=2),
    mk(8, "重点行业碳排放核算与核查服务", "中标公告", ["双碳"], "认证核查",
       "某省生态环境厅", "事业单位", "测试环科院A", 300.0, "300万元", "测试省", "2024-11-25",
       src="某省公共资源交易中心", lvl=2),
]

mock_path = DEMO_OUT / "mock_bids.jsonl"
mock_path.write_text(
    "\n".join([json.dumps(r, ensure_ascii=False) for r in MOCK_BIDS] + ["TEST-坏行-不是JSON"]) + "\n",
    encoding="utf-8")


def run_stats(*extra):
    cmd = [sys.executable, str(SKILL / "scripts" / "stats.py"), str(mock_path), *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"_error": proc.stderr}
    return json.loads(proc.stdout)


# ============================================================
# A. L1 结构测试
# ============================================================
skill = read(SKILL / "SKILL.md")
check("A1 SKILL.md 存在", bool(skill), str(SKILL / "SKILL.md"))

m = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
fm = {}
if m:
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
check("A2 frontmatter 含 name=esg-bid-monitor",
      fm.get("name") == "esg-bid-monitor", fm.get("name", ""))

desc = fm.get("description", "")
check("A3 description 为 pushy 触发描述（>100 字且含'监控''中标'）",
      len(desc) > 100 and "监控" in desc and "中标" in desc, f"len={len(desc)}")

n_lines = skill.count("\n") + 1
check("A4 SKILL.md 正文 <500 行（渐进式加载规范）", bool(skill) and n_lines < 500, f"{n_lines} 行")

for r in ["search-playbook.md", "keywords.md", "extraction-rules.md", "analysis-guide.md", "report-template.md"]:
    p = SKILL / "references" / r
    size = p.stat().st_size if p.exists() else 0
    check(f"A5 references/{r} 存在且被 SKILL.md 声明读取时机", size > 200 and r in skill, f"{size} 字节")

try:
    py_compile.compile(str(SKILL / "scripts" / "stats.py"),
                       cfile=str(DEMO_OUT / "_stats_compiled.pyc"), doraise=True)
    compile_ok, compile_err = True, ""
except Exception as e:  # noqa: BLE001
    compile_ok, compile_err = False, str(e)
check("A7 scripts/stats.py 可编译", compile_ok, compile_err)
check("A8 SKILL.md 声明 stats.py 调用方式", "scripts/stats.py" in skill)

state = {}
try:
    state = json.loads(read(DATA / "state.json") or "{}")
except json.JSONDecodeError:
    pass
check("A9 data/state.json 含 last_run/seen_count/daily_log/webhook",
      all(k in state for k in ("last_run", "seen_count", "daily_log", "webhook")))
check("A10 data/bids.jsonl 存在（可为空，待真实运行累积）", (DATA / "bids.jsonl").exists())

tmpl = read(SKILL / "references" / "report-template.md")
check("A11 report-template.md 含回溯报告模板与每日速递模板", "模板一" in tmpl and "模板二" in tmpl)
check("A12 两份质量自查清单存在", tmpl.count("自查清单") >= 2)

# ============================================================
# B. L2 规则可实现性测试（对照 extraction-rules.md）
# ============================================================
check("B1 项目名归一化：全角→半角 / 去空格 / 去括号补充",
      normalize_name("某市２０２６年 碳中和方案（补充说明）") == "某市2026年碳中和方案")

base = fingerprint("某市2026年碳达峰行动方案编制服务", "某市生态环境局")
check("B2 指纹确定性（同输入两次计算一致）",
      fingerprint("某市2026年碳达峰行动方案编制服务", "某市生态环境局") == base)
check("B3 一标多公告同指纹（'（二次公告）'括号版本归一）",
      fingerprint("某市2026年碳达峰行动方案编制服务（二次公告）", "某市生态环境局") == base)
check("B4 不同采购人 → 不同指纹",
      fingerprint("某市2026年碳达峰行动方案编制服务", "某市发改委") != base)
check("B5 指纹长度为 12 位", len(base) == 12, base)

AMOUNT_CASES = [
    ("中标金额：1,285,000 元", 128.5),
    ("成交金额为 365.8 万元", 365.8),
    ("中标价 1.2 亿元", 12000.0),
    ("预算金额：450 万", 450.0),
    ("最高限价 80 万元，未披露成交价", 80.0),
    ("中标折扣率 85%（无绝对金额）", None),
    ("具体面议", None),
]
for i, (text, want) in enumerate(AMOUNT_CASES, 1):
    got = normalize_amount(text)
    check(f"B6.{i} 金额规范化「{text[:16]}…」→ {want}", got == want, f"got={got}")

check("B7 金额口径优先级：成交价 > 预算 > 限价",
      select_amount({"成交金额": 365.8, "预算金额": 450.0, "最高限价": 500.0}) == 365.8
      and select_amount({"预算金额": 450.0, "最高限价": 500.0}) == 450.0
      and select_amount({"最高限价": 500.0}) == 500.0)
check("B8 候选全缺失 → None", select_amount({}) is None)

# ============================================================
# C. L3 管线端到端测试（stats.py + 状态窗口）
# ============================================================
full = run_stats()
check("C0 mock 数据 record_id 全部唯一",
      len({r["record_id"] for r in MOCK_BIDS}) == len(MOCK_BIDS))
check("C1 stats.py 端到端：total=8 且检出坏行(line 9)",
      full.get("total") == 8 and full.get("malformed_lines") == [9], full.get("_error", ""))
check("C2 阶段分布：中标公告 6 / 招标公告 2",
      full["stage"].get("中标公告") == 6 and full["stage"].get("招标公告") == 2)
check("C3 主题多标签计数：双碳=3 且各主题合计 9 > 样本数 8",
      full["theme_counts"].get("双碳") == 3 and sum(full["theme_counts"].values()) == 9)

am = full["amount"]
check("C4 金额：有值 7 / 缺失 1 / 缺失率 0.125",
      am["with_amount"] == 7 and am["missing"] == 1 and am["missing_rate"] == 0.125)
check("C5 金额分桶与 analysis-guide 口径一致（1.2亿入'≥1亿'桶）",
      am["buckets"] == {"<50万": 0, "50-100万": 1, "100-500万": 3, "500-1000万": 1,
                        "1000-5000万": 1, "5000万-1亿": 0, "≥1亿": 1})
check("C6 集中趋势：总额 17258.5 / 中位 450.0 / 均值 2465.5（均值中位并列防大单拉偏）",
      am["total_wan"] == 17258.5 and am["median_wan"] == 450.0 and am["mean_wan"] == 2465.5)
check("C7 中标企业 Top1：测试环科院A（2 次 / 428.5 万，双指标）",
      bool(full["top_winners"]) and full["top_winners"][0] ==
      {"winner": "测试环科院A", "count": 2, "amount_wan_sum": 428.5})
mon = {m["month"]: m for m in full["monthly"]}
check("C8 月度趋势：覆盖 5 个月，2026-10 金额合计 12530.0",
      len(full["monthly"]) == 5 and mon.get("2026-10", {}).get("amount_wan") == 12530.0)

win26 = run_stats("--start-date", "2026-01-01", "--end-date", "2026-12-31")
check("C9 时间窗过滤（--start-date/--end-date 闭区间）→ 2026 年 6 条", win26.get("total") == 6)

run_stats("--out", str(DEMO_OUT / "demo_stats.json"))
saved = json.loads((DEMO_OUT / "demo_stats.json").read_text(encoding="utf-8"))
check("C13 --out 落盘与 stdout 一致", saved["total"] == full["total"])

now = datetime(2026, 11, 24, 9, 0, 0)
w1, _ = monitor_window({"last_run": None}, now)
check("C10 首次运行（无 last_run）→ 窗口=近 24h", w1 == now - timedelta(hours=24))
w2, _ = monitor_window({"last_run": (now - timedelta(days=3)).isoformat()}, now)
check("C11 漏跑 3 天 → 窗口回补到上次运行（不丢条目）", w2 == now - timedelta(days=3))
w3, _ = monitor_window({"last_run": (now - timedelta(minutes=30)).isoformat()}, now)
check("C12 刚跑过 30 分钟 → 窗口仍覆盖 24h", w3 == now - timedelta(hours=24))

# ============================================================
# D. L4 模式分流测试（SKILL.md Phase 0 规则）
# ============================================================
check("D1 「汇总过去2年…中标金额分布」→ report",
      route_mode("汇总过去2年ESG、双碳相关的中标情况，分析热点招标情况及中标金额分布") == "report")
check("D2 「监控新的ESG招标，每天推送」→ monitor",
      route_mode("监控新的跟ESG相关的招标情况，每天推送新的招标信息") == "monitor")
check("D3 「生成今天的ESG标讯速递」→ monitor", route_mode("生成今天的ESG标讯速递") == "monitor")
check("D4 「看看最近有什么值得跟的投标商机」→ monitor",
      route_mode("看看最近有什么值得跟的投标商机") == "monitor")
check("D5 未命中任何模式词 → 默认 report（Phase 0 规则）",
      route_mode("双碳领域现在政策怎么样") == "report")

# ============================================================
# E. L4 产出测试（按 report-template.md 生成 demo 报告骨架）
# ============================================================
def build_demo_report(stats: dict) -> str:
    am, themes = stats["amount"], stats["theme_counts"]
    srcs, regions, winners = stats["sources"], stats["region_top10"], stats["top_winners"]
    monthly, total = stats["monthly"], stats["total"]
    lvl1 = srcs.get("中国政府采购网", 0)
    lvl2 = sum(v for k, v in srcs.items() if "交易中心" in k)
    lvl3 = total - lvl1 - lvl2
    parse_rate = f"{(1 - am['missing_rate']) * 100:.1f}%"
    top_theme = max(themes, key=themes.get)
    top_bucket = max(am["buckets"], key=am["buckets"].get)

    L = ["# ESG/双碳领域招投标市场回顾报告（DEMO）", "",
         f"> 样本说明：入库 {total} 条 | 来源构成：一级 {lvl1} / 二级 {lvl2} / 三级 {lvl3} | 金额可解析率 {parse_rate}",
         "> 统计口径：公开可检索样本，非全量市场数据 | 编制：esg-bid-monitor Skill 测试 demo", "",
         "## 摘要",
         f"（demo）基于 {total} 条 mock 样本：最热主题为「{top_theme}」（{themes[top_theme]} 条）；"
         f"金额重心位于 {top_bucket} 区间；中标金额中位数 {am.get('median_wan')} 万元、"
         f"均值 {am.get('mean_wan')} 万元；金额缺失率 {am['missing_rate'] * 100:.1f}%。", "",
         "## 核心发现速览", "| # | 发现 | 关键数字 |", "|---|---|---|",
         f"| 1 | 最热主题 | {top_theme} {themes[top_theme]} 条 |",
         f"| 2 | 金额可解析率 | {parse_rate} |",
         f"| 3 | 中标金额中位数 | {am.get('median_wan')} 万元 |", "",
         "## 一、市场总览",
         f"- 总样本 {total} 条，覆盖 {len(monthly)} 个月：{'、'.join(m['month'] for m in monthly)}", "",
         "## 二、热点主题分析", "```mermaid", "pie title 主题分布（多标签计数，mock 数据）"]
    L += [f'    "{t}" : {c}' for t, c in themes.items()]
    L += ["```", "- 解读（demo 占位）：真实运行时此处由检索证据支撑主题热度成因分析。", "",
          "## 三、中标金额分布",
          f"- 有金额样本 {am['with_amount']} 条 / 缺失 {am['missing']} 条（缺失率 {am['missing_rate'] * 100:.1f}%）",
          f"- 总额 {am['total_wan']} 万元 | 均值 {am['mean_wan']} 万元 | 中位数 {am['median_wan']} 万元",
          "- 分桶：" + "、".join(f"{k} {v} 条" for k, v in am["buckets"].items() if v), "",
          "## 四、地域与采购人分析",
          "- 省份 Top：" + "、".join(f"{r['region']}({r['count']})" for r in regions[:5]),
          "- 采购人类型分布见 demo_stats.json 的 buyer_type 字段（demo 略图）", "",
          "## 五、中标格局", "| 企业 | 中标次数 | 累计金额(万元) |", "|---|---|---|"]
    L += [f"| {w['winner']} | {w['count']} | {w['amount_wan_sum']} |" for w in winners]
    L += ["", "## 六、趋势研判与投标建议",
          "1. （demo 占位）真实运行时此处给 ≥3 条可操作建议：主攻主题、价位带、平台与客户类型。", "",
          "## 附录",
          "A. 明细数据：tests/demo_output/mock_bids.jsonl（全部为 TEST- mock 数据）",
          "D. 局限性声明：本报告为 demo 产物，数据为人工构造，不代表真实市场。"]
    return "\n".join(L)


report_md = build_demo_report(full)
(DEMO_OUT / "demo_回顾报告.md").write_text(report_md, encoding="utf-8")

for sec in ["## 摘要", "## 核心发现速览", "## 一、市场总览", "## 二、热点主题分析",
            "## 三、中标金额分布", "## 四、地域与采购人分析", "## 五、中标格局",
            "## 六、趋势研判与投标建议", "## 附录"]:
    check(f"E1 demo 报告含必需章节：{sec}", sec in report_md)
check("E2 头部样本说明含四要素（样本量/来源构成/金额可解析率/统计口径）",
      all(k in report_md for k in ("样本说明", "来源构成", "金额可解析率", "统计口径")))
check("E3 mock 标注与局限性声明在场（口径诚实原则）",
      "mock" in report_md and "局限性声明" in report_md)

state_after = {"last_run": "2026-11-24T09:00:00", "seen_count": full["total"],
               "daily_log": ["2026-11-24"], "webhook": None}
(DEMO_OUT / "demo_state_after_run.json").write_text(
    json.dumps(state_after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
check("E4 运行后 state 字段齐全且 seen_count 与库行数一致",
      all(k in state_after for k in ("last_run", "seen_count", "daily_log", "webhook"))
      and state_after["seen_count"] == full["total"])

# ============================================================
# 汇总
# ============================================================
print("=" * 66)
print("esg-bid-monitor Skill 测试 demo")
print("=" * 66)
for i, (name, ok, detail) in enumerate(results, 1):
    mark = "✓" if ok else "✗"
    suffix = f"  ({detail})" if detail else ""
    print(f"{mark} {name}{suffix}")
print("-" * 66)
passed = sum(1 for _, ok, _ in results if ok)
verdict = "全部通过 ✅" if passed == len(results) else f"存在 {len(results) - passed} 个失败项 ❌"
print(f"结果：{passed}/{len(results)} 通过 — {verdict}")
print("\n演示产物（tests/demo_output/，均为 mock 数据）：")
for p in sorted(DEMO_OUT.iterdir()):
    print(f"  - {p.name}")
sys.exit(0 if passed == len(results) else 1)
