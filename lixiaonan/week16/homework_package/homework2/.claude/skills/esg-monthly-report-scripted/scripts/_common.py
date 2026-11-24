#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享工具（纯标准库）：URL 归一化 / 标题归一化 / 指纹 / 日期抽取 / JSON 读写。

本模块被同目录各脚本 import（脚本目录天然在 sys.path 上）；
跨 skill 包分发时随 scripts/ 整目录复制，保持 skill 包自包含。
"""
import base64
import datetime
import hashlib
import json
import os
import re
import sys
from urllib.parse import parse_qsl, urlencode, unquote, urlsplit, urlunsplit

# 追踪参数：URL 归一化时剔除（utm_ 前缀按前缀匹配，其余精确匹配）
TRACKING_PARAMS = re.compile(
    r"^(utm_.+|spm|from|fbclid|gclid|msclkid|ref|ref_src|share|share_token|tt_from|vd_source|vd_checksum)$",
    re.IGNORECASE,
)

# 搜索引擎跳转包装：DuckDuckGo /l/?uddg=<urlencode(url)>
_WRAP_HOSTS = {"duckduckgo.com", "www.duckduckgo.com", "html.duckduckgo.com", "lite.duckduckgo.com"}

# 全角→半角映射表（含全角空格 0x3000）
_FULL2HALF = {0x3000: 0x20}
for _c in range(0xFF01, 0xFF5F):
    _FULL2HALF[_c] = _c - 0xFEE0

# 日期抽取：ISO 日期 / 中文日期 / 年-月（后跟非日期避免与 ISO 冲突）
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_CN = re.compile(r"(?<!\d)(\d{4})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?")
_YM = re.compile(r"(?<![\d-])(\d{4})-(\d{1,2})(?!-?\d)")


def die(msg, code=1):
    """错误退出：消息进 stderr，不进 stdout（stdout 只输出合法 JSON）。"""
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def unwrap_redirect(url):
    """解包搜索引擎跳转链；无法解包的（如 baidu/link?url=、Google News）原样返回。"""
    try:
        parts = urlsplit(url)
        host = parts.netloc.lower()
        if host in _WRAP_HOSTS and parts.path.startswith("/l/"):
            q = dict(parse_qsl(parts.query))
            if "uddg" in q:
                return unwrap_redirect(unquote(q["uddg"]))
        if host.endswith("bing.com") and parts.path.startswith("/ck/"):
            u = dict(parse_qsl(parts.query)).get("u", "")
            if u.startswith("a1"):
                b = u[2:] + "=" * (-len(u[2:]) % 4)
                return unwrap_redirect(base64.urlsafe_b64decode(b).decode("utf-8", "ignore"))
    except Exception:
        pass
    return url


def normalize_url(url):
    """URL 归一化（仅用于去重身份判断，不改变抓取用的原始 URL）：
    解包跳转链 → scheme 统一 https → host 小写 → 去 fragment → 剔除追踪参数并排序 → 去尾斜杠。
    """
    if not url or not isinstance(url, str):
        return ""
    url = unwrap_redirect(url.strip())
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    scheme = "https" if parts.scheme in ("http", "https", "") else parts.scheme
    host = parts.netloc.lower()
    if not host:
        return url
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
         if not TRACKING_PARAMS.match(k)]
    q.sort()
    return urlunsplit((scheme, host, path, urlencode(q), ""))


def norm_title(title):
    """标题归一化：全角→半角、去空白与中英文标点、小写——用于 dup_title 指纹。"""
    if not title:
        return ""
    t = str(title).translate(_FULL2HALF)
    t = re.sub(r"[\s　]+", "", t)
    t = re.sub(r"[，。、；：？！,.:;?!'\"()（）【】\[\]{}<>《》「」—\-_·…~～*#|]", "", t)
    return t.lower()


def sha1_12(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def title_fp(title):
    return sha1_12(norm_title(title)) if title else ""


def extract_dates(text):
    """抽取文本中的日期线索，按出现顺序返回 [{"y":…, "m":…, "d":…|None, "raw":…}, …]。
    支持三种写法：2026-11-03 / 2026年11月(3日)（含空格变体）/ 2026-11（年-月，如"2026-11 中旬"）。
    """
    hits = []
    for m in _ISO.finditer(text):
        hits.append((m.start(), {"y": int(m.group(1)), "m": int(m.group(2)), "d": int(m.group(3)), "raw": m.group(0)}))
    for m in _CN.finditer(text):
        d = int(m.group(3)) if m.group(3) else None
        hits.append((m.start(), {"y": int(m.group(1)), "m": int(m.group(2)), "d": d, "raw": m.group(0)}))
    iso_spans = [(m.start(), m.end()) for m in _ISO.finditer(text)]
    for m in _YM.finditer(text):
        if any(s <= m.start() < e for s, e in iso_spans):
            continue  # 已被 ISO 完整覆盖（2026-11-03 的前半段）
        hits.append((m.start(), {"y": int(m.group(1)), "m": int(m.group(2)), "d": None, "raw": m.group(0)}))
    hits.sort(key=lambda x: x[0])
    return [h for _, h in hits]


def parse_date_hint(hint):
    """date_hint → {"kind":"day","date":date} | {"kind":"month","y":…,"m":…} | None（缺失/无法解析）。"""
    if not hint:
        return None
    hits = extract_dates(str(hint))
    if not hits:
        return None
    h = hits[0]
    try:
        if h["d"]:
            return {"kind": "day", "date": datetime.date(h["y"], h["m"], h["d"])}
        return {"kind": "month", "y": h["y"], "m": h["m"]}
    except ValueError:
        return None


def parse_window(s):
    """'YYYY-MM-DD:YYYY-MM-DD' → (date, date)，闭区间；非法格式抛 ValueError。"""
    try:
        a, b = s.split(":", 1)
        return datetime.date.fromisoformat(a.strip()), datetime.date.fromisoformat(b.strip())
    except (ValueError, AttributeError) as e:
        raise ValueError(f"时间窗格式应为 'YYYY-MM-DD:YYYY-MM-DD'，收到: {s!r}（{e}）")


def read_json_input(path):
    """读取 JSON 输入；'-' 表示 stdin。"""
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_candidates(data):
    """search.py 产出兼容：接受裸数组或 {"candidates": [...]}。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("candidates"), list):
        return data["candidates"]
    die("输入格式应为候选数组或 {\"candidates\": [...]}（search.py run 的输出）")


def write_out(payload, out_path=None):
    """JSON 输出到 stdout；--out 指定时同时落盘（与 stats.py 约定一致）。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if out_path:
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError as e:
            die(f"无法写入输出文件 {out_path}: {e}")
