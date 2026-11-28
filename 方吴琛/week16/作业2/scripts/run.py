"""命令行入口。

用法:
  python run.py monthly --client 陕西煤业 --industry 煤炭 --year-month 2026-10
  python run.py bidding --mode aggregate [--region 广东] [--max-queries 30]
  python run.py bidding --mode monitor

可选环境变量:
  ESG_LLM_API_KEY / ZHIPUAI_API_KEY  启用 LLM 总结(无则降级为抽取式)
  TAVILY_API_KEY / ESG_SEARCH_BACKEND=tavily  切换搜索后端
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 让 scripts/ 目录可作为包根被导入
sys.path.insert(0, str(Path(__file__).resolve().parent))

from esg_monthly import MonthlyParams, run as run_monthly
from esg_bidding import aggregate, monitor


def main():
    ap = argparse.ArgumentParser(description="ESG 高代码脚本流水线")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("monthly", help="生成 ESG 月报")
    m.add_argument("--client", required=True)
    m.add_argument("--industry", required=True)
    m.add_argument("--benchmark", default="中国神华")
    m.add_argument("--year-month", default="")
    m.add_argument("--focus", default="")
    m.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "examples"))

    b = sub.add_parser("bidding", help="ESG 招投标汇总/监控")
    b.add_argument("--mode", choices=["aggregate", "monitor"], default="aggregate")
    b.add_argument("--region", default="")
    b.add_argument("--max-queries", type=int, default=0)
    b.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "examples"))

    args = ap.parse_args()

    if args.cmd == "monthly":
        p = MonthlyParams(
            client=args.client, industry=args.industry,
            benchmark=args.benchmark, year_month=args.year_month, focus=args.focus,
        )
        path, metrics = run_monthly(p, args.out)
        print(f"[月报] 已生成:{path}")
        print(json.dumps(metrics.__dict__, ensure_ascii=False, indent=2))
    elif args.cmd == "bidding":
        if args.mode == "aggregate":
            path, metrics, stats = aggregate(
                args.out, args.region or None,
                args.max_queries or None,
            )
            print(f"[汇总] 已生成:{path}")
            print("metrics:", json.dumps(metrics.__dict__, ensure_ascii=False))
            print("stats:", json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
        else:
            path, metrics = monitor(args.out)
            print(f"[监控] 已生成:{path}")
            print(json.dumps(metrics.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
