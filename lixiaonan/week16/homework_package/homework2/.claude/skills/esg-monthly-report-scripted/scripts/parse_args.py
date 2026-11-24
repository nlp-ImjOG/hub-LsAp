#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参数与日期解析脚本（纯标准库，M1）

用法:
    python parse_args.py [--today YYYY-MM-DD] [--client 中国神华] [--industry 行业]
                         [--mode monthly|report|monitor] [--period 表达式]
                         [--industry-map 行业表.json] [--out meta.json]

- 将自然语言时间表达解析为精确的日期闭区间 [start_date, end_date]：
  近一个月/近N个月/近2年(近两年等)/近半年/近24h/YYYY-MM/YYYY-MM-DD/A至B（至|到|~）；
- 客户→行业查表；查不到输出 null + needs_search 提示，绝不猜测（行业由模型检索确认后可用 --industry 指定）；
- 结果 JSON 输出到 stdout；--out 指定时同时落盘。

--today 专为测试存在：让日期逻辑对固定锚点可断言。
"""
import argparse
import datetime
import json
import re

try:
    from _common import die, write_out
except ImportError:
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import die, write_out

# 各模式的默认报告期
MODE_DEFAULT_PERIOD = {
    "monthly": "近一个月",
    "report": "近2年",
    "monitor": "近24h",
}

# 内置客户→行业映射（作业1已知客户）；其他客户查不到 → needs_search，不猜测
INDUSTRY_MAP = {
    "中国神华": "煤炭/传统能源",
    "陕西煤业": "煤炭",
    "中煤能源": "煤炭",
    "兖矿能源": "煤炭",
    "国家能源集团": "煤炭/综合能源",
    "龙源电力": "电力/新能源",
    "三峡集团": "电力/清洁能源",
    "中国石化": "石油化工",
    "中国石油": "石油天然气",
    "中国宝武": "钢铁",
    "鞍钢集团": "钢铁",
    "比亚迪": "汽车/新能源",
    "宁德时代": "动力电池/新能源",
    "招商银行": "银行/金融",
}

_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _num(s):
    return _CN_NUM.get(s) or int(s)


def parse_period(expr, today):
    """时间表达 → (start_date, end_date) 闭区间。非法表达抛 ValueError。"""
    expr = (expr or "").strip()

    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s*(?:至|到|~|～)\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", expr)
    if m:
        return (_make_date(int(m.group(1)), int(m.group(2)), int(m.group(3))),
                _make_date(int(m.group(4)), int(m.group(5)), int(m.group(6))))

    m = re.match(r"^(\d{4})[-/](\d{1,2})$", expr)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        last = _last_day(y, mo)
        return (datetime.date(y, mo, 1), datetime.date(y, mo, last))

    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", expr)
    if m:
        d = _make_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return (d, d)

    m = re.match(r"^近(\d+|[一二两三四五六七八九])个?月$", expr)
    if m:
        return (today - datetime.timedelta(days=30 * _num(m.group(1))), today)

    m = re.match(r"^近(\d+|[一二两三四五六七八九])年$", expr)
    if m:
        return (today - datetime.timedelta(days=365 * _num(m.group(1))), today)

    if expr == "近半年":
        return (today - datetime.timedelta(days=182), today)
    if expr in ("近24h", "近24小时", "近一日", "近一天"):
        return (today - datetime.timedelta(days=1), today)

    raise ValueError(
        f"无法解析时间表达 {expr!r}；支持：近N个月/近N年/近半年/近24h/YYYY-MM/YYYY-MM-DD/A至B")


def _make_date(y, mo, d):
    try:
        return datetime.date(y, mo, d)
    except ValueError as e:
        raise ValueError(f"非法日期 {y}-{mo}-{d}: {e}")


def _last_day(y, mo):
    if mo == 12:
        return 31
    return (datetime.date(y, mo + 1, 1) - datetime.timedelta(days=1)).day


def resolve_industry(args):
    """行业解析优先级：--industry 显式指定 > --industry-map 文件 > 内置查表 > needs_search。"""
    client = args.client
    if args.industry:
        return args.industry, "cli", []
    mapping = dict(INDUSTRY_MAP)
    if args.industry_map:
        try:
            with open(args.industry_map, "r", encoding="utf-8") as f:
                mapping.update(json.load(f))
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"无法读取行业表 {args.industry_map}: {e}")
    if client in mapping:
        return mapping[client], "builtin", []
    return None, "needs_search", [
        f"行业未知：请检索「{client} 主营业务 行业」确认后，用 --industry 指定（行业决定检索词与对标企业）"
    ]


def main():
    ap = argparse.ArgumentParser(description="参数与日期解析（月报/标讯共用）")
    ap.add_argument("--today", help="今天日期 YYYY-MM-DD（缺省取系统当天；测试用它固定锚点）")
    ap.add_argument("--client", default="中国神华", help="客户名称（默认中国神华，与作业1 skill 约定一致）")
    ap.add_argument("--industry", help="显式指定行业，跳过查表")
    ap.add_argument("--industry-map", help="行业映射 JSON 文件路径（合并覆盖内置表）")
    ap.add_argument("--mode", default="monthly", choices=["monthly", "report", "monitor"],
                    help="任务模式：monthly 月报 / report 标讯回溯 / monitor 标讯监控")
    ap.add_argument("--period", help="报告期表达（缺省按 mode 取默认：月报=近一个月）")
    ap.add_argument("--out", help="meta.json 落盘路径（stdout 始终输出）")
    args = ap.parse_args()

    if args.today:
        try:
            today = datetime.date.fromisoformat(args.today)
        except ValueError as e:
            die(f"--today 格式应为 YYYY-MM-DD: {e}")
    else:
        today = datetime.date.today()

    try:
        start, end = parse_period(args.period or MODE_DEFAULT_PERIOD[args.mode], today)
        industry, industry_source, hints = resolve_industry(args)
    except ValueError as e:
        die(str(e))

    if start > end:
        die(f"报告期起点 {start} 晚于终点 {end}")

    label = (f"{end.year}年{end.month}月刊" if args.mode == "monthly"
             else f"{start.isoformat()} ~ {end.isoformat()}")

    write_out({
        "mode": args.mode,
        "client": args.client,
        "industry": industry,
        "industry_source": industry_source,
        "today": today.isoformat(),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "period_label": label,
        "window": f"{start.isoformat()}:{end.isoformat()}",
        "hints": hints,
    }, args.out)


if __name__ == "__main__":
    main()
