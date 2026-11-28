"""作业2 对比实验：量化「有确定性脚本」与「无脚本」两种 Skill 形态的差异。

跑法：
  python 对比实验.py                  # 离线：只跑有脚本态（确定性、结构覆盖、时延）
  python 对比实验.py --llm            # 需配置 LLM Key：额外跑无脚本态（自由成稿两次，测差异率）

输出：
  - 控制台对比表
  - 对比结果_{日期}.json（含各项指标）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import esg_monthly_report as esg  # noqa: E402
import report_writer  # noqa: E402
import config  # noqa: E402

REQUIRED_SECTIONS = [
    "执行摘要",
    "ESG 政策 / 标准 / 评价动态",
    "行业新闻与最佳实践",
    "客户公司动态",
    "对标企业 ESG 关键行动",
    "风险提示与下一步行动建议",
]


def section_coverage(text: str) -> float:
    hits = sum(1 for s in REQUIRED_SECTIONS if s in text)
    return hits / len(REQUIRED_SECTIONS)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_scripted(n: int = 2) -> dict:
    """有脚本态：确定性流水线跑两次，测一致性 / 结构覆盖 / 时延。"""
    t0 = time.time()
    first = esg.build_report("中国神华", "煤炭 / 煤电一体化", ["兖矿能源", "陕西煤业", "中煤能源", "国家能源集团"], 30, demo=True)
    elapsed = time.time() - t0
    second = esg.build_report("中国神华", "煤炭 / 煤电一体化", ["兖矿能源", "陕西煤业", "中煤能源", "国家能源集团"], 30, demo=True)
    return {
        "deterministic": sha(first) == sha(second),
        "coverage": section_coverage(first),
        "elapsed_s": round(elapsed, 2),
        "llm_calls": 0,  # demo 模式不调 LLM
        "output_chars": len(first),
    }


def run_unscripted() -> dict:
    """无脚本态（近似）：同一份素材、同一个开放式提示，让 LLM 直接自由成稿两次，测差异率与结构覆盖。

    注意：真实无脚本 Skill 还会自行规划检索词并多次搜索，这里为了可复现只测「自由成稿」这一环的方差。
    """
    import llm_summarize as L

    prompt = (
        "请为中国神华撰写 ESG 月报，覆盖：ESG政策/标准动态、煤炭行业新闻与最佳实践、"
        "公司动态与ESG影响建议、对标企业（兖矿能源/陕西煤业/中煤能源/国家能源集团）关键行动、风险与建议。"
        "直接输出完整 Markdown。"
    )
    texts = [L.complete("你是 ESG 咨询顾问。", prompt, temperature=0.8) for _ in range(2)]
    a, b = texts
    same = sha(a) == sha(b)
    # 差异率：用字符级近似（去空白后最长公共子序列比例）
    import difflib
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return {
        "deterministic": same,
        "diff_ratio": round(1 - ratio, 3),
        "coverage": section_coverage(a),
        "llm_calls": 2,
        "output_chars": len(a),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="额外运行无脚本态（需 LLM Key）")
    args = ap.parse_args()

    print("=== 有脚本态（确定性流水线）===")
    scripted = run_scripted()
    print(json.dumps(scripted, ensure_ascii=False, indent=2))

    result = {"scripted": scripted, "unscripted": None}
    if args.llm:
        if not config.get_settings().llm_enabled:
            print("\n[skip] 未配置 LLM Key，跳过无脚本态。")
        else:
            print("\n=== 无脚本态（LLM 自由成稿两次）===")
            un = run_unscripted()
            result["unscripted"] = un
            print(json.dumps(un, ensure_ascii=False, indent=2))

    out = os.path.join(os.path.dirname(__file__), f"对比结果_{report_writer.stamp()[:10]}.json")
    report_writer.save(out, json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[对比] 结果已保存：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
