#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告/标讯库质量自查脚本（纯标准库，M1）

用法:
    python check.py report --file report.md [--window "2026-10-25:2026-11-24"]
                           [--min-words 300] [--notes notes.md] [--out check.json]
    python check.py db --db data/bids.jsonl [--state data/state.json] [--out check.json]

报告规则（对 A/B 两组通用——评测时对无脚本版产出同样运行，保证对比公平）：
  R1 引用一致性：正文 [n] 必须存在于附录来源清单；附录编号必须从 1 连续；附录未被正文引用 → warn
  R2 时间窗越界：正文中早于窗口起点的日期，所在行须含"数据日期"标注；
     晚于窗口终点的日期（如征求意见截止日）→ warn 不判错
  R3 占位残留：<!-- 模型撰写 --> / {{cite: / TODO 未清除
  R4 字数下限：各正文章节（跳过"摘要"与"附录"章）内容量 ≥ --min-words
  R5 格式警告：空章节 / 空 Mermaid 块 / 空表格行
  R6 产物齐套：--notes 指定的笔记文件必须存在

标讯库规则：
  R7 每行合法 JSON；14 个必填字段非空；publish_date 为合法 YYYY-MM-DD；
     url 为 http(s)；record_id 唯一；行数与 state.json 的 seen_count 一致（缺 state 文件 → warn）

failures 中 severity=error 任意一条 → exit 1；warn 不影响 exit code。
输出 JSON：{"mode", "passed", "failures", "summary"}；stdout 输出，--out 同时落盘。
"""
import argparse
import datetime
import json
import os
import re

try:
    from _common import die, extract_dates, parse_window, write_out
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import die, extract_dates, parse_window, write_out

# 18 字段模型中的必填子集（对齐作业1 extraction-rules.md；winner/amount/deadline 可空）
REQUIRED_FIELDS = ["record_id", "project_name", "stage", "theme", "industry_type",
                   "buyer", "buyer_type", "region", "publish_date", "source_name",
                   "source_level", "url", "summary", "collected_at"]

_H2 = re.compile(r"^##\s+")
_CITE = re.compile(r"\[(\d+)\](?!\()")
_APP_ROW = re.compile(r"^\s*(?:\|\s*)?(?:[-*]\s*)?(?:\d+[.、]\s*)?\[(\d+)\]")
_PLACEHOLDER = ("<!-- 模型撰写", "{{cite:")
_TODO = re.compile(r"\bTODO\b")
_MERMAID_EMPTY = re.compile(r"```mermaid\s*\n\s*```")
_EMPTY_ROW = re.compile(r"^\|(?:\s*\|)+\s*$")


def _fail(failures, rule, severity, detail, line=None):
    failures.append({"rule": rule, "severity": severity, "detail": detail, "line": line})


def _count_words(s):
    """内容量 = CJK 字符数 + 拉丁词组数（去空白后统计）。"""
    s = re.sub(r"\s+", "", s)
    return len(re.findall(r"[一-鿿]", s)) + len(re.findall(r"[A-Za-z0-9]+", s))


def _split_chapters(text):
    """按 ^## 切章：返回 [{title, start_line, body, start_body_line}, …]；保留章前导言为 title='' 章。"""
    chapters, cur = [], {"title": "", "start_line": 1, "lines": []}
    for i, ln in enumerate(text.splitlines(), 1):
        if _H2.match(ln):
            chapters.append(cur)
            cur = {"title": ln.lstrip("# ").strip(), "start_line": i, "lines": []}
        else:
            cur["lines"].append((i, ln))
    chapters.append(cur)
    for ch in chapters:
        ch["body"] = "\n".join(l for _, l in ch["lines"])
    return chapters


def check_report(text, window=None, min_words=300, notes_path=None):
    failures = []
    lines = text.splitlines()
    chapters = _split_chapters(text)
    appendix = [ch for ch in chapters if "附录" in ch["title"]]
    body = [ch for ch in chapters if "附录" not in ch["title"]]
    body_text = "\n".join(ch["body"] for ch in body)

    # R3 占位残留（全文）
    for i, ln in enumerate(lines, 1):
        for p in _PLACEHOLDER:
            if p in ln:
                _fail(failures, "R3", "error", f"占位残留：{p}", line=i)
        if _TODO.search(ln):
            _fail(failures, "R3", "error", "占位残留：TODO", line=i)

    # R1 引用一致性
    app_nums, body_cites = set(), set()
    for ch in appendix:
        for i, ln in ch["lines"]:
            m = _APP_ROW.match(ln)
            if m:
                app_nums.add(int(m.group(1)))
    for ch in body:
        for i, ln in ch["lines"]:
            for m in _CITE.finditer(ln):
                body_cites.add(int(m.group(1)))
    for n in sorted(body_cites - app_nums):
        _fail(failures, "R1", "error", f"正文引用 [{n}] 在附录来源清单中不存在")
    if app_nums:
        if min(app_nums) != 1:
            _fail(failures, "R1", "error", f"附录编号应从 [1] 开始，当前最小为 [{min(app_nums)}]")
        for n in sorted(set(range(1, max(app_nums) + 1)) - app_nums):
            _fail(failures, "R1", "error", f"附录编号不连续：缺失 [{n}]")
        for n in sorted(app_nums - body_cites):
            _fail(failures, "R1", "warn", f"附录来源 [{n}] 未被正文引用")
    elif body_cites:
        _fail(failures, "R1", "error", "正文有引用但未找到附录来源清单（应含 '## 附录' 章及 [n] 编号条目）")

    # R2 时间窗越界（仅正文；期外早于窗起点须带"数据日期"标注，晚于窗终点为 warn）
    if window:
        start, end = window
        for ch in body:
            for i, ln in ch["lines"]:
                for d in extract_dates(ln):
                    try:
                        if d["d"]:
                            dt = datetime.date(d["y"], d["m"], d["d"])
                            if dt < start and "数据日期" not in ln:
                                _fail(failures, "R2", "error",
                                      f"报告期外日期 {d['raw']} 未标注\"数据日期\"", line=i)
                            elif dt > end:
                                _fail(failures, "R2", "warn", f"晚于窗口终点的日期 {d['raw']}（如为截止日期可忽略）", line=i)
                        else:
                            if (d["y"], d["m"]) < (start.year, start.month) and "数据日期" not in ln:
                                _fail(failures, "R2", "error",
                                      f"报告期外年月 {d['raw']} 未标注\"数据日期\"", line=i)
                    except ValueError:
                        continue  # 非法日期（如 2026-13-40）不属 R2 管辖

    # R4 字数下限（跳过摘要与附录章）
    for ch in body:
        if not ch["title"] or "摘要" in ch["title"]:
            continue
        n = _count_words(ch["body"])
        if n < min_words:
            _fail(failures, "R4", "error", f"章节「{ch['title']}」内容量 {n} 低于下限 {min_words}")

    # R5 格式警告
    for ch in body:
        if ch["title"] and not ch["body"].strip():
            _fail(failures, "R5", "warn", f"空章节「{ch['title']}」", line=ch["start_line"])
    if _MERMAID_EMPTY.search(text):
        _fail(failures, "R5", "warn", "存在空 Mermaid 代码块")
    for i, ln in enumerate(lines, 1):
        if _EMPTY_ROW.match(ln):
            _fail(failures, "R5", "warn", "空表格行", line=i)

    # R6 产物齐套
    if notes_path and not os.path.isfile(notes_path):
        _fail(failures, "R6", "error", f"过程笔记不存在: {notes_path}")

    return failures


def check_db(db_path, state_path=None):
    failures = []
    n_lines, ids = 0, set()
    if not os.path.isfile(db_path):
        _fail(failures, "R7", "error", f"标讯库不存在: {db_path}")
        return failures
    with open(db_path, "r", encoding="utf-8") as f:
        for i, ln in enumerate(f, 1):
            ln = ln.strip()
            if not ln:
                continue
            n_lines += 1
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError as e:
                _fail(failures, "R7", "error", f"第 {i} 行不是合法 JSON: {e}", line=i)
                continue
            for k in REQUIRED_FIELDS:
                v = rec.get(k)
                if v is None or v == "" or v == []:
                    _fail(failures, "R7", "error", f"第 {i} 行必填字段 {k} 为空", line=i)
            pd = rec.get("publish_date")
            if pd:
                try:
                    datetime.date.fromisoformat(str(pd))
                except ValueError:
                    _fail(failures, "R7", "error", f"第 {i} 行 publish_date 非法: {pd!r}", line=i)
            url = rec.get("url")
            if url:
                try:
                    from urllib.parse import urlsplit
                    parts = urlsplit(str(url))
                    if parts.scheme not in ("http", "https") or not parts.netloc:
                        raise ValueError("非 http(s) URL")
                except ValueError:
                    _fail(failures, "R7", "error", f"第 {i} 行 url 非法: {url!r}", line=i)
            rid = rec.get("record_id")
            if rid:
                if rid in ids:
                    _fail(failures, "R7", "error", f"第 {i} 行 record_id 重复: {rid}", line=i)
                ids.add(rid)

    state_path = state_path or os.path.join(os.path.dirname(os.path.abspath(db_path)), "state.json")
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                seen = json.load(f).get("seen_count")
            if seen != n_lines:
                _fail(failures, "R7", "error", f"state.json seen_count={seen} 与标讯库行数 {n_lines} 不一致")
        except (json.JSONDecodeError, OSError) as e:
            _fail(failures, "R7", "error", f"state.json 读取失败: {e}")
    else:
        _fail(failures, "R7", "warn", f"未找到 state.json（{state_path}），跳过 seen_count 一致性检查")

    return failures


def main():
    ap = argparse.ArgumentParser(description="可代码化质量自查（R1–R7）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("report", help="报告自查")
    rp.add_argument("--file", required=True, help="报告 Markdown 路径")
    rp.add_argument("--window", help="报告期 'YYYY-MM-DD:YYYY-MM-DD'（缺省跳过 R2）")
    rp.add_argument("--min-words", type=int, default=300, help="各正文章节内容量下限（默认 300）")
    rp.add_argument("--notes", help="过程笔记路径（提供则检查存在性 R6）")
    rp.add_argument("--out", help="check.json 落盘路径")

    db = sub.add_parser("db", help="标讯库自查")
    db.add_argument("--db", required=True, help="bids.jsonl 路径")
    db.add_argument("--state", help="state.json 路径（缺省取 bids.jsonl 同目录）")
    db.add_argument("--out", help="check.json 落盘路径")

    args = ap.parse_args()

    if args.cmd == "report":
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            die(f"无法读取报告 {args.file}: {e}")
        window = None
        if args.window:
            try:
                window = parse_window(args.window)
            except ValueError as e:
                die(str(e))
        failures = check_report(text, window, args.min_words, args.notes)
        payload = {"mode": "report", "file": os.path.abspath(args.file)}
    else:
        failures = check_db(args.db, args.state)
        payload = {"mode": "db", "file": os.path.abspath(args.db)}

    errors = [f for f in failures if f["severity"] == "error"]
    warns = [f for f in failures if f["severity"] == "warn"]
    payload.update({
        "passed": not errors,
        "failures": failures,
        "summary": {"errors": len(errors), "warns": len(warns)},
    })
    write_out(payload, args.out)
    if errors:
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()
