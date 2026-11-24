#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 端到端演示脚本（离线，零依赖，零联网）

串联 M1 三个脚本，用 tests/fixtures 的数据完整走一遍月报管线的前半程与质量闸门：

  阶段0  parse_args.py    自然语言报告期 → 精确日期区间 + 行业查表
  阶段1  filter.py        检索候选规则初筛（去重/时间窗/主题词，monthly 宽松模式）
  阶段2  （模拟）模型语义终判：只消费 filtered.passed 清单——脚本管"做对"，模型管"做好"
  阶段3  check.py report  合格报告放行 / 违规报告拦截（R1–R6 逐条展示）
  阶段4  check.py db      标讯库体检（bid 管线的质量闸门，R7）
  阶段5  filter.py bid    黑名单巧合词拦截与 unless 豁免演示

用法:
    python3 tests/demo_m1.py

产物（可随时删除）:
    tests/demo_output/{meta,filtered,check_good,check_bad,check_db,filtered_bid}.json

退出码: 所有阶段符合预期 → 0；任一不符 → 1（可当冒烟测试用）。
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(ROOT, ".claude", "skills", "esg-monthly-report-scripted", "scripts")
KW_MONTHLY = os.path.join(ROOT, ".claude", "skills", "esg-monthly-report-scripted", "references", "keywords.json")
KW_BID = os.path.join(ROOT, ".claude", "skills", "esg-bid-monitor-scripted", "references", "keywords.json")
FIX = os.path.join(HERE, "fixtures")
OUT = os.path.join(HERE, "demo_output")

MARK = ("✓", "✗")
_results = []


def step(title):
    print(f"\n{'─' * 66}\n▶ {title}\n{'─' * 66}")


def run_script(name, *args):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, name), *[str(a) for a in args]],
                          capture_output=True, text=True)


def expect(cond, msg):
    _results.append(bool(cond))
    print(f"  {MARK[0] if cond else MARK[1]} {msg}")


def show(payload, keys=None, limit=6):
    """精简打印 JSON 关键字段。"""
    if isinstance(payload, dict) and keys:
        payload = {k: payload[k] for k in keys if k in payload}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    lines = text.splitlines()
    print("\n".join(lines[:limit] + (["  …"] if len(lines) > limit else [])))


def main():
    os.makedirs(OUT, exist_ok=True)

    # ── 阶段0：参数解析 ────────────────────────────────────────────
    step("阶段0 parse_args.py：『近一个月』→ 精确日期区间，客户→行业查表")
    meta_path = os.path.join(OUT, "meta.json")
    r = run_script("parse_args.py", "--today", "2026-11-24", "--mode", "monthly",
                   "--client", "中国神华", "--out", meta_path)
    meta = json.loads(r.stdout) if r.returncode == 0 else {}
    expect(r.returncode == 0, "parse_args.py 正常退出")
    expect(meta.get("window") == "2026-10-25:2026-11-24", f"报告期解析: {meta.get('window')}")
    expect(meta.get("period_label") == "2026年11月刊", f"报告命名: {meta.get('period_label')}")
    expect(meta.get("industry") == "煤炭/传统能源", f"行业查表: 中国神华 → {meta.get('industry')}")
    show(meta, keys=["mode", "client", "industry", "start_date", "end_date", "period_label"])

    # ── 阶段1：规则初筛（monthly 宽松模式） ────────────────────────
    step("阶段1 filter.py：7 条检索候选 → 规则初筛（去重/时间窗/主题词宽松匹配）")
    filtered_path = os.path.join(OUT, "filtered.json")
    r = run_script("filter.py", "--input", os.path.join(FIX, "candidates_monthly.json"),
                   "--window", meta["window"], "--mode", "monthly",
                   "--client", "中国神华", "--keywords", KW_MONTHLY, "--out", filtered_path)
    filtered = json.loads(r.stdout) if r.returncode == 0 else {}
    s = filtered.get("stats", {})
    expect(r.returncode == 0, "filter.py 正常退出")
    expect(s.get("total") == 7 and s.get("passed") == 4 and s.get("rejected") == 3,
           f"初筛统计: total={s.get('total')} passed={s.get('passed')} rejected={s.get('rejected')}")
    expect(s.get("by_reason") == {"dup_url": 1, "dup_title": 1, "out_of_window": 1},
           f"拒绝原因分布: {s.get('by_reason')}")
    print()
    for c in filtered.get("rejected", []):
        print(f"  ✗ [{c['reason_code']}] {c['item'].get('title', '')[:30]} ← {c['detail'][:38]}")

    # ── 阶段2：模型语义终判（演示中仅展示交接清单） ────────────────
    step("阶段2 交接清单：以下 passed 条目交给模型做语义终判与笔记（真实管线由模型执行）")
    for c in filtered.get("passed", []):
        print(f"  • {c.get('title', '')[:36]}")
        for n in c.get("filter_notes", []):
            print(f"      - {n}")
    expect(len(filtered.get("passed", [])) > 0, f"交接清单 {len(filtered.get('passed', []))} 条（脚本不做语义判断，只做规则过滤）")

    # ── 阶段3：报告质量闸门 ───────────────────────────────────────
    step("阶段3 check.py report：合格报告放行 / 违规报告拦截")
    rg = run_script("check.py", "report", "--file", os.path.join(FIX, "report_good.md"),
                    "--window", meta["window"], "--notes", os.path.join(FIX, "notes_good.md"),
                    "--out", os.path.join(OUT, "check_good.json"))
    good = json.loads(rg.stdout)
    expect(rg.returncode == 0 and good["passed"], f"合格报告放行（errors={good['summary']['errors']}）")
    expect(good["summary"]["warns"] == 1, f"未来截止日期 2027-02-19 仅 warn 不判错")
    print()

    rb = run_script("check.py", "report", "--file", os.path.join(FIX, "report_bad.md"),
                    "--window", meta["window"], "--min-words", "150",
                    "--notes", os.path.join(FIX, "nonexistent_notes.md"),
                    "--out", os.path.join(OUT, "check_bad.json"))
    bad = json.loads(rb.stdout)
    expect(rb.returncode == 1 and not bad["passed"],
           f"违规报告拦截: exit=1, errors={bad['summary']['errors']}, warns={bad['summary']['warns']}")
    for f in bad["failures"]:
        flag = "ERROR" if f["severity"] == "error" else "warn "
        print(f"  [{f['rule']} {flag}] {f['detail'][:56]}")

    # ── 阶段4：标讯库体检（bid 管线的质量闸门） ─────────────────────
    step("阶段4 check.py db：bids.jsonl 体检（必填字段/日期/URL/指纹唯一/seen_count）")
    rgood = run_script("check.py", "db", "--db", os.path.join(FIX, "bids_good.jsonl"),
                       "--state", os.path.join(FIX, "state_ok.json"),
                       "--out", os.path.join(OUT, "check_db.json"))
    dbgood = json.loads(rgood.stdout)
    expect(rgood.returncode == 0 and dbgood["passed"], "合法标讯库放行（2 行，seen_count=2 一致）")

    rbad = run_script("check.py", "db", "--db", os.path.join(FIX, "bids_bad.jsonl"),
                      "--state", os.path.join(FIX, "state_bad.json"))
    dbbad = json.loads(rbad.stdout)
    errs = [f for f in dbbad["failures"] if f["severity"] == "error"]
    expect(rbad.returncode == 1 and len(errs) == 6,
           f"问题标讯库拦截: {len(errs)} 处 error（缺字段/坏日期/坏URL/指纹重复/seen_count 不一致）")

    # ── 阶段5：bid 模式黑名单演示 ──────────────────────────────────
    step("阶段5 filter.py bid 模式：黑名单巧合词拦截与 unless 豁免")
    r = run_script("filter.py", "--input", os.path.join(FIX, "candidates_bid.json"),
                   "--window", meta["window"], "--mode", "bid", "--keywords", KW_BID,
                   "--out", os.path.join(OUT, "filtered_bid.json"))
    bid = json.loads(r.stdout)
    expect(bid["stats"]["by_reason"].get("blacklist_hit") == 1, "『某医院绿色通道改造』→ blacklist_hit 拦截")
    expect(bid["stats"]["by_reason"].get("keyword_miss") == 1, "『市政绿化带养护』→ keyword_miss 拦截")
    waived = [c for c in bid["passed"] if "mine.example.org" in c["url"]]
    expect(bool(waived), "『矿区绿化+碳汇计量』→ unless 豁免词命中，放行待语义判定")
    for c in bid["rejected"]:
        if c["reason_code"] == "blacklist_hit":
            print(f"  ✗ {c['detail'][:60]}")

    # ── 汇总 ─────────────────────────────────────────────────────
    ok = sum(_results)
    print(f"\n{'═' * 66}\n演示结果: {ok}/{len(_results)} 项符合预期 {'—— M1 管线可交付' if ok == len(_results) else '—— 存在不符合项！'}")
    print(f"产物目录: {OUT}")
    return 0 if ok == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
