"""作业二 A/B 对比指标计算：用同一把尺子量"无脚本"与"有脚本"两份产物。

复用技能管线里的数字归一化逻辑，避免两套口径。
用法：python ab_metrics.py  -> 打印对比表并写 data/metrics.json
"""

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def _load_pipeline():
    """按路径加载技能里的管线模块（复用它的数字归一化，不抄一份）。"""
    path = ROOT / ".agents/skills/esg-monthly-report/scripts/esg_source_pipeline.py"
    spec = importlib.util.spec_from_file_location("esg_source_pipeline", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"加载不了管线模块：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


esp = _load_pipeline()

REQ_DIRS = ["policy_domestic", "policy_intl", "rating", "industry", "client", "peer"]

ARMS = {
    "A_无脚本": {"ledger": "data/armA/audit_A.json",
                 "report": "reports/A_无script_中国神华_ESG月报_2026-11.md",
                 "docs": "data/armA/docs_A.jsonl"},
    "B_有脚本": {"ledger": "data/armB/sources_B.json",
                 "report": "reports/B_有script_中国神华_ESG月报_2026-11.md",
                 "docs": "data/docs_semantic.jsonl"},
}


def load(path):
    p = ROOT / path
    try:
        with p.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"读不了 {path}: {e}") from e


def load_jsonl(path):
    p = ROOT / path
    try:
        with p.open(encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"读不了 {path}: {e}") from e


def measure(name, cfg):
    led = load(cfg["ledger"])
    md = (ROOT / cfg["report"]).read_text("utf-8")
    sources = led["sources"]
    stats = led["stats"]
    ids = {r["sid"] for r in sources}

    cited = set(re.findall(r"(?<![A-Za-z])(S\d{1,3})(?!\d)", md))
    valid_cited = cited & ids
    broken = cited - ids

    # 期外引用是否标了"（背景）"
    unmarked = []
    for r in sources:
        if r["date_bucket"] != "background_60d" or r["sid"] not in cited:
            continue
        i = md.find(r["sid"])
        if i > 0 and "背景" not in md[max(0, i - 160): i + 160]:
            gap = (esp.d(led["since"]) - esp.d(r["date"])).days
            unmarked.append({"sid": r["sid"], "date": r["date"], "超窗天数": gap})

    # 数字可溯源
    pool = set()
    for r in sources:
        pool |= esp.num_tokens((r.get("body") or "") + " " + (r.get("title") or "") +
                               " " + " ".join(n["value"] for n in r.get("numbers", [])))
    nums = esp.num_tokens(md)
    num_miss = [t for t in nums if not esp.num_hit(t, pool)]

    dirs_cited = {r["direction"] for r in sources if r["sid"] in cited}

    return {
        "arm": name,
        "候选/声称来源数": stats["n_docs"],
        "归并后事件数": stats["n_events"],
        "可入账数": stats["n_usable"],
        "被剔除数": stats["n_rejected"],
        "剔除原因": stats["rejected_reasons"],
        "报告引用编号数": len(cited),
        "引用合格数": len(valid_cited),
        "引用未闭环数": len(broken),
        "引用未闭环编号": sorted(broken),
        "引用合格率": round(len(valid_cited) / max(1, len(cited)) * 100, 1),
        "报告覆盖方向": sorted(dirs_cited),
        "方向覆盖数": len(dirs_cited),
        "期外未标注背景": len(unmarked),
        "期外未标注明细": sorted(unmarked, key=lambda x: -x["超窗天数"]),
        "数字未溯源数": len(num_miss),
        "数字总数": len(nums),
        "数字溯源率": round((1 - len(num_miss) / max(1, len(nums))) * 100, 1),
        "日期来源分布": stats["date_source"],
    }


def main():
    rows = [measure(k, v) for k, v in ARMS.items()]

    # 模型自带日期 vs 页面实际日期（衡量"手工摘日期"的出错率）
    conflicts = []
    for f in ("data/armA/docs_A.jsonl", "data/docs_semantic.jsonl"):
        for r in load_jsonl(f):
            if r.get("date_conflict"):
                conflicts.append({"来源": Path(f).name, "声称": r.get("date_hint"),
                                  "页面实际": r.get("date"), "标题": (r.get("title") or "")[:40]})
    print(f"日期冲突：{len(conflicts)} 处（模型提供的日期与页面抽取日期不一致）")
    for c in conflicts:
        print(f"  {c['声称']} -> {c['页面实际']}  {c['标题']}")
    print()

    hdr = ["指标"] + [r["arm"] for r in rows]
    keys = ["候选/声称来源数", "归并后事件数", "可入账数", "被剔除数", "报告引用编号数",
            "引用合格数", "引用未闭环数", "引用合格率", "方向覆盖数", "期外未标注背景",
            "数字总数", "数字未溯源数", "数字溯源率"]
    print(f"{hdr[0]:<14}{hdr[1]:>14}{hdr[2]:>14}")
    for k in keys:
        print(f"{k:<14}{str(rows[0][k]):>14}{str(rows[1][k]):>14}")

    out = {"arms": rows, "date_conflicts": conflicts}
    (ROOT / "data/metrics.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print("\n-> data/metrics.json")


if __name__ == "__main__":
    main()
