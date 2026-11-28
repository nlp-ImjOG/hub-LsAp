#!/usr/bin/env python3
"""esg-monthly-report Skill 测试 demo

用法（在 part1 目录或任意位置均可）：
    python3 tests/test_skill_demo.py

覆盖两类检查：
  A. Skill 包结构校验（对标实施报告第七章"Skill 结构规范"验收项）
  B. 产出物质量校验（对标 report-template.md 质量自查清单中可程序化的项）
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / ".claude" / "skills" / "esg-monthly-report"
REPORTS = ROOT / "reports"
REPORT_MD = REPORTS / "中国神华_ESG月报_2026-11.md"
REPORT_HTML = REPORTS / "中国神华_ESG月报_2026-11.html"
NOTES = REPORTS / "notes-中国神华_2026-11.md"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ---------- A. Skill 包结构校验 ----------
skill = read(SKILL_DIR / "SKILL.md")
check("A1 SKILL.md 存在", bool(skill), str(SKILL_DIR / "SKILL.md"))

# frontmatter 解析（不依赖 yaml 库，按 --- 分隔逐行取 key:value）
m = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
fm = {}
if m:
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
check("A2 frontmatter 含 name=esg-monthly-report",
      fm.get("name") == "esg-monthly-report", fm.get("name", ""))
desc = fm.get("description", "")
check("A3 description 为 pushy 触发描述（>100 字且含触发词'月报'）",
      len(desc) > 100 and "月报" in desc, f"len={len(desc)}")

n_lines = skill.count("\n") + 1
check("A4 SKILL.md 正文 <500 行（渐进式加载规范）", bool(skill) and n_lines < 500, f"{n_lines} 行")

refs = ["search-playbook.md", "report-template.md", "benchmark-companies.md"]
for r in refs:
    p = SKILL_DIR / "references" / r
    size = p.stat().st_size if p.exists() else 0
    check(f"A5 references/{r} 存在且非空", size > 200, f"{size} 字节")
    check(f"A6 SKILL.md 声明了 {r} 的读取时机", r in skill)

# ---------- B. 报告产出质量校验 ----------
rep = read(REPORT_MD)
check("B1 月报 Markdown 存在", bool(rep), str(REPORT_MD))

for sec in ["## 一、ESG 政策", "## 二、行业动态", "## 三、公司动态", "## 四、对标企业", "### 附录 A"]:
    check(f"B2 必需章节存在：{sec}", sec in rep)

for tag in ["E（环境）", "S（社会）", "G（治理）"]:
    check(f"B3 3.2 影响分析含维度：{tag}", tag in rep)

cites = set(re.findall(r"\[(\d+)\]", rep))
rows = set(re.findall(r"^\| \[(\d+)\]", rep, re.M))
check("B4 正文引用与附录A来源一一对应（≥20条）",
      bool(cites) and cites == rows and len(cites) >= 20,
      f"引用 {len(cites)} 个编号 / 附录 {len(rows)} 行")

sec33 = rep.split("### 3.3 建议行动")[-1].split("\n## ")[0]
n_sugg = len(re.findall(r"^\d+\. ", sec33, re.M))
check("B5 3.3 建议行动 ≥3 条", n_sugg >= 3, f"{n_sugg} 条")

check("B6 报告期外数据均有标注（'报告期前'/'数据日期标注'）",
      "报告期前" in rep or "数据日期标注" in rep)
check("B7 免责声明存在（'不构成投资'）", "不构成投资" in rep)

html_size = REPORT_HTML.stat().st_size if REPORT_HTML.exists() else 0
check("B8 HTML 版报告存在", html_size > 10000, f"{html_size} 字节")

notes = read(NOTES)
check("B9 检索笔记存在且含筛选标记（入选/落选）", "【入选】" in notes and "落选" in notes)
check("B10 笔记含客户与报告期头信息", "中国神华" in notes and "2026-10-24" in notes)

# ---------- 汇总 ----------
print("=" * 66)
print("esg-monthly-report Skill 测试 demo")
print("=" * 66)
for i, (name, ok, detail) in enumerate(results, 1):
    mark = "✓" if ok else "✗"
    suffix = f"  ({detail})" if detail else ""
    print(f"{mark} {name}{suffix}")
passed = sum(1 for _, ok, _ in results if ok)
print("-" * 66)
verdict = "全部通过 ✅" if passed == len(results) else f"存在 {len(results) - passed} 个失败项 ❌"
print(f"结果：{passed}/{len(results)} 通过 — {verdict}")
sys.exit(0 if passed == len(results) else 1)
