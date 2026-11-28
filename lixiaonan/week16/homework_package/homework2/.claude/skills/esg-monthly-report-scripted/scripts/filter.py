#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规则层初筛脚本（纯标准库，M1）

用法:
    python filter.py --input results.json --window "2026-10-25:2026-11-24"
                     [--mode monthly|bid] [--keywords keywords.json]
                     [--client 中国神华] [--out filtered.json]

顺序执行的规则链（每条拒绝必须带 reason_code，绝不静默丢弃）：
  1. 去重：norm_url 相同 → dup_url；标题归一化指纹相同 → dup_title
  2. 时间窗：日期明确早于窗起点 → out_of_window；日期缺失/无法解析/晚于窗终点
     → 保留并标注（搜索摘要里常见"截止 XXXX-XX-XX"等未来日期，杀掉会误伤，留语义判定）
  3. 主题词命中：
     - bid 模式：标题/摘要未命中五大主题词 → keyword_miss 拒绝（标讯对主题相关性要求硬）
     - monthly 模式：词库未命中 → 仍保留，标 keyword_weak（月报检索词本身已带主题，
       摘要措辞各异，硬杀会造成"规则初筛误杀语义相关条目"）
  4. 黑名单巧合词（仅 bid）：标题命中且无 unless 豁免词 → blacklist_hit

passed 的语义是"待模型语义终判的清单"，不是最终入选。
输出 JSON：{"passed": [...], "rejected": [...], "stats": {...}}；stdout 输出，--out 同时落盘。
"""
import argparse
import json
import os

try:
    from _common import (die, load_candidates, normalize_url, parse_date_hint,
                         parse_window, read_json_input, title_fp, write_out)
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import (die, load_candidates, normalize_url, parse_date_hint,
                         parse_window, read_json_input, title_fp, write_out)

DEFAULT_KEYWORDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references", "keywords.json")


def load_keywords(path, mode):
    """加载词库配置；bid 模式缺主题/黑名单表则拒绝运行（无规则保护等于裸奔）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        die(f"无法读取词库 {path}: {e}")
    except json.JSONDecodeError as e:
        die(f"词库 JSON 解析失败 {path}: {e}")

    if mode == "bid":
        bid = data.get("bid", {})
        if not bid.get("themes") or "blacklist" not in bid:
            die(f"bid 模式要求词库包含 bid.themes 与 bid.blacklist（{path} 缺失）")
        return bid
    monthly = data.get("monthly", {})
    lines = monthly.get("lines", {})
    if not lines:
        die(f"monthly 模式要求词库包含 monthly.lines（{path} 缺失）")
    return monthly


def _monthly_keywords(kw, client):
    """三线词库拍平为关键词列表；{client} 占位替换，客户未知时丢弃该占位词。"""
    words = []
    for line_words in kw.get("lines", {}).values():
        for w in line_words:
            if "{client}" in w:
                if client:
                    words.append(w.replace("{client}", client))
                continue
            words.append(w)
    return words


def _match(words, text):
    """返回第一个命中的关键词（大小写不敏感）；无命中返回 None。"""
    t = text.lower()
    for w in words:
        if w and w.lower() in t:
            return w
    return None


def _date_note(dinfo, start, end):
    """时间窗判定：返回 (note|None, reject_reason|None)。"""
    if dinfo is None:
        return ("date_unknown（日期缺失/无法解析，留语义判定）", None)
    if dinfo["kind"] == "day":
        d = dinfo["date"]
        if d < start:
            return (None, f"日期 {d.isoformat()} 早于窗口起点 {start.isoformat()}")
        if d > end:
            return ("date_future（日期晚于窗口终点，摘要中的截止日期常见，留语义判定）", None)
        return ("日期在窗内", None)
    # 年-月粒度
    if (dinfo["y"], dinfo["m"]) < (start.year, start.month):
        return (None, f"年月 {dinfo['y']}-{dinfo['m']:02d} 早于窗口起点月份")
    if (dinfo["y"], dinfo["m"]) > (end.year, end.month):
        return ("date_future（年月晚于窗口终点，留语义判定）", None)
    return ("日期在窗内（按月粒度）", None)


def filter_candidates(cands, window, mode, kw, client=None):
    start, end = window
    passed, rejected = [], []
    seen_urls, seen_titles = set(), set()
    monthly_words = _monthly_keywords(kw, client) if mode == "monthly" else None
    themes = kw.get("themes", {}) if mode == "bid" else {}
    blacklist = kw.get("blacklist", []) if mode == "bid" else []

    for c in cands:
        if not isinstance(c, dict):
            rejected.append({"item": c, "reason_code": "invalid", "detail": "候选不是对象"})
            continue
        c = dict(c)
        url = c.get("norm_url") or normalize_url(c.get("url", ""))
        c["norm_url"] = url
        title = c.get("title") or ""
        text = f"{title} {c.get('snippet') or ''}"

        # 1. 去重（保留先到者）
        if not c.get("url") and not url:
            rejected.append({"item": c, "reason_code": "missing_url", "detail": "无 URL，无法核验入库"})
            continue
        if url and url in seen_urls:
            rejected.append({"item": c, "reason_code": "dup_url", "detail": f"与已见 URL 重复: {url}"})
            continue
        tfp = title_fp(title)
        if tfp and tfp in seen_titles:
            rejected.append({"item": c, "reason_code": "dup_title", "detail": f"与已见标题重复: {title}"})
            continue

        # 2. 时间窗
        note, reject = _date_note(parse_date_hint(c.get("date_hint")), start, end)
        if reject:
            rejected.append({"item": c, "reason_code": "out_of_window", "detail": reject})
            continue
        notes = [note] if note else []

        # 3. 主题词命中
        if mode == "bid":
            hit = _match([w for ws in themes.values() for w in ws], text)
            if not hit:
                rejected.append({"item": c, "reason_code": "keyword_miss",
                                 "detail": "标题/摘要未命中任何主题词"})
                continue
            notes.append(f"命中主题词:{hit}")
        else:
            hit = _match(monthly_words, text)
            notes.append(f"命中词库:{hit}" if hit else "keyword_weak（词库未命中，留语义判定）")

        # 4. 黑名单巧合词（仅 bid，标题层面）
        bl_hit = None
        for entry in blacklist:
            pattern = entry.get("pattern", "")
            if pattern and pattern in title:
                unless = entry.get("unless", [])
                if not any(u in title for u in unless):
                    bl_hit = f"标题命中『{pattern}』{entry.get('note', '')}"
                    break
        if bl_hit:
            rejected.append({"item": c, "reason_code": "blacklist_hit", "detail": bl_hit})
            continue

        if url:
            seen_urls.add(url)
        if tfp:
            seen_titles.add(tfp)
        c["filter_notes"] = notes
        passed.append(c)

    by_reason = {}
    for r in rejected:
        by_reason[r["reason_code"]] = by_reason.get(r["reason_code"], 0) + 1
    return {
        "passed": passed,
        "rejected": rejected,
        "stats": {"total": len(cands), "passed": len(passed),
                  "rejected": len(rejected), "by_reason": by_reason},
    }


def main():
    ap = argparse.ArgumentParser(description="规则层初筛（去重/时间窗/主题词/黑名单）")
    ap.add_argument("--input", required=True, help="候选 JSON 路径（search.py run 产出；'-' 读 stdin）")
    ap.add_argument("--window", required=True, help="时间窗 'YYYY-MM-DD:YYYY-MM-DD'（闭区间）")
    ap.add_argument("--mode", default="monthly", choices=["monthly", "bid"])
    ap.add_argument("--keywords", default=DEFAULT_KEYWORDS, help="词库 JSON（缺省取本 skill 的 references/keywords.json）")
    ap.add_argument("--client", default=None, help="客户名（替换月报词库中的 {client} 占位）")
    ap.add_argument("--out", help="filtered.json 落盘路径（stdout 始终输出）")
    args = ap.parse_args()

    try:
        start, end = parse_window(args.window)
        data = read_json_input(args.input)
    except ValueError as e:
        die(str(e))
    except OSError as e:
        die(f"无法读取输入 {args.input}: {e}")
    except json.JSONDecodeError as e:
        die(f"输入 JSON 解析失败: {e}")

    cands = load_candidates(data)
    kw = load_keywords(args.keywords, args.mode)
    write_out(filter_candidates(cands, (start, end), args.mode, kw, args.client), args.out)


if __name__ == "__main__":
    main()
