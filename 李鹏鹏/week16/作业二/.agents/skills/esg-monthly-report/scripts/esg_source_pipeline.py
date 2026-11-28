#!/usr/bin/env python3
"""ESG 月报：检索与归集的确定性管线。

五个子命令，同一输入必得同一输出（网络响应落盘缓存，二次运行零请求）：

  plan    profile + 检索矩阵 -> 检索计划（六方向 × 检索式 × 通道 × 时间窗）
  search  执行计划 -> 候选命中（gov.cn 政策库 / 生态环境部 / 巨潮公告 / 必应 RSS）
  fetch   抓正文 -> 结构化文档（标题 / 机构 / 日期 + 日期来源 / 正文 / 数字 / 关键句）
  ledger  去重 + 时效分档 + 权威度分级 + 编号 -> sources.json + factcards.csv
  check   硬门禁（期外混入 / 无日期 / 无机构 / 方向覆盖 / 引用闭环 / 数字可溯源）

分工：脚本负责"找得到、记得准、编得对"，模型负责"看得出影响、写得出建议"。
"""

import argparse
import contextlib
import hashlib
import io
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

for _s in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def log(msg):
    print(msg, file=sys.stderr)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
CACHE = Path(__file__).resolve().parent.parent / ".cache"
CACHE.mkdir(exist_ok=True)

# 信源权威度：域名后缀 -> T1/T2/T3。未命中一律 T4（只作线索，不入引用账）。
# 信源权威度：域名后缀 -> T1/T2/T3。未命中一律 T4（只作线索，不入引用账）。
# 分级表放在 references/tier-map.json，便于维护：加一个域名不用改代码。
TIER_MAP_PATH = Path(__file__).resolve().parent.parent / "references/tier-map.json"


def _load_tiers():
    try:
        with TIER_MAP_PATH.open(encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"读不了权威度分级表 {TIER_MAP_PATH}：{e}") from e
    return {t: raw[t] for t in ("T1", "T2", "T3") if t in raw}


TIER_SUFFIX = _load_tiers()
TIER_RANK = {"T1": 0, "T2": 1, "T3": 2, "T4": 3}

CJK = re.compile(r"[\u4e00-\u9fff]")
NUM_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,10}(?:\.\d+)?)\s*"
    r"(万亿元|亿元|千万元|百万元|万元|亿吨|百万吨|万吨|千吨|吨|亿千瓦时|万千瓦时|千瓦时|"
    r"万千瓦|亿立方米|万立方米|立方米|平方公里|公顷|亩|个百分点|%|％|倍|元)")

# 数字归一化：把不同量纲写法折算到同一基准，不然“45.3百万吨”和“4530万吨”对不上
UNIT_BASE = {
    "万亿元": ("money", 1e12), "亿元": ("money", 1e8), "千万元": ("money", 1e7),
    "百万元": ("money", 1e6), "万元": ("money", 1e4), "元": ("money", 1),
    "亿吨": ("ton", 1e8), "百万吨": ("ton", 1e6), "万吨": ("ton", 1e4),
    "千吨": ("ton", 1e3), "吨": ("ton", 1),
    "亿千瓦时": ("kwh", 1e8), "万千瓦时": ("kwh", 1e4), "千瓦时": ("kwh", 1),
    "万千瓦": ("kw", 1e4),
    "亿立方米": ("vol", 1e8), "万立方米": ("vol", 1e4), "立方米": ("vol", 1),
    "平方公里": ("area", 1e6), "公顷": ("area", 1e4), "亩": ("area", 666.67),
    "%": ("pct", 1), "％": ("pct", 1), "个百分点": ("pct", 1), "倍": ("times", 1),
}


def num_tokens(text):
    """把带单位的数字折成 (量纲, 基准值)，容忍四舍五入带来的小差异。"""
    out = set()
    for m in NUM_RE.finditer(re.sub(r"\s+", "", text or "")):
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        fam, mult = UNIT_BASE.get(m.group(2), ("raw", 1))
        out.add((fam, val * mult))
    return out


def num_hit(tok, pool, rel=0.01):
    """报告里的数字能否在来源里找到（同量纲且相差不超过 1%）。"""
    fam, v = tok
    for f2, v2 in pool:
        if f2 != fam:
            continue
        if abs(v - v2) <= max(abs(v2) * rel, 1e-9):
            return True
    return False
DATE_CN = re.compile(r"(20\d{2})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})")
META_DATE_KEYS = ["article:published_time", "pubdate", "publishdate", "publish_date",
                  "PubDate", "weibo:article:create_at", "og:release_date", "dc.date",
                  "dc.date.issued", "date", "og:published_time", "sailthru.date"]


# ---------------------------------------------------------------- 基础设施

def http_get(url, refresh=False, timeout=25, post=None):
    """带磁盘缓存的取数。同 URL 二次运行不再发请求。"""
    key = hashlib.sha256((url + json.dumps(post, sort_keys=True, ensure_ascii=False)
                          if post else url).encode()).hexdigest()[:20]
    raw_f, meta_f = CACHE / f"{key}.raw", CACHE / f"{key}.json"
    if not refresh and raw_f.exists() and meta_f.exists():
        return raw_f.read_bytes(), json.loads(meta_f.read_text("utf-8"))
    for attempt in range(3):
        try:
            if post is not None:
                r = requests.post(url, data=post, headers={**HEADERS, "Referer": url},
                                  timeout=timeout)
            else:
                r = requests.get(url, headers=HEADERS, timeout=timeout)
            time.sleep(0.4)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            meta = {"url": url, "status": r.status_code,
                    "ctype": r.headers.get("content-type", ""), "ts": datetime.now().isoformat(timespec="seconds")}
            raw_f.write_bytes(r.content)
            meta_f.write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
            return r.content, meta
        except Exception as e:
            if attempt == 2:
                return b"", {"url": url, "error": f"{type(e).__name__}: {e}"[:200]}
            time.sleep(1.5 * (attempt + 1))
    return b"", {"url": url, "error": "unreachable"}


def to_text(raw, meta):
    if "json" in (meta.get("ctype") or ""):
        return raw.decode("utf-8", "ignore")
    m = re.search(r"charset=([\w-]+)", meta.get("ctype") or "", re.I)
    enc = (m.group(1) if m else "utf-8").lower()
    txt = raw.decode(enc, "ignore")
    if txt.count("\ufffd") > 20:  # 编码猜错，按 gb18030 重试
        txt = raw.decode("gb18030", "ignore")
    return txt


def clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"找不到输入文件：{path}")
    rows = []
    with p.open(encoding="utf-8") as f:
        for i, ln in enumerate(f, 1):
            if not ln.strip():
                continue
            try:
                rows.append(json.loads(ln))
            except ValueError as e:
                raise SystemExit(f"{path} 第 {i} 行不是合法 JSON：{e}") from e
    return rows


def js(b):
    """宽容解析 JSON；失败返回 None 而不是抛出。"""
    try:
        return json.loads(b.decode("utf-8", "ignore"))
    except ValueError as e:
        log(f"JSON 解析失败（{e}），已跳过该批次")
        return None


def _ld_date(script_text):
    """从 JSON-LD 取 datePublished，失败返回空串。"""
    try:
        j = json.loads(script_text or "{}")
    except ValueError:
        return ""
    j = j[0] if isinstance(j, list) and j else j
    return str(j.get("datePublished", ""))[:10] if isinstance(j, dict) else ""


def ms_to_date(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except Exception:
        return ""


def d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


# ---------------------------------------------------------------- plan

def cmd_plan(a):
    profile = json.loads(Path(a.profile).read_text("utf-8"))
    matrix = json.loads(Path(a.matrix).read_text("utf-8"))
    since, until = d(a.since), d(a.until)
    bg_since = since - timedelta(days=60)

    queries = []
    for did, spec in matrix["directions"].items():
        for ch in spec["channels"]:
            for i, q in enumerate(spec["queries"], 1):
                # cninfo 的 searchkey 是子串匹配，多个公司名必须拆成多次查询，否则一条不中
                variants = ([q.replace("{peers}", p) for p in (profile.get("peers") or [])]
                            if "{peers}" in q else [q])
                for j, one in enumerate(variants or [q.replace("{peers}", "")], 1):
                    qq = (one.replace("{company}", profile.get("client", ""))
                            .replace("{short}", profile.get("short", ""))
                            .replace("{code}", profile.get("code", "")))
                    queries.append({
                        "qid": f"{did}-{ch}-{i:02d}{chr(96 + j) if len(variants) > 1 else ''}",
                        "direction": did, "label": spec["label"], "tier": spec["tier"],
                        "channel": ch, "query": qq,
                        "window": [bg_since.isoformat(), until.isoformat()],
                    })
    plan = {"generated_at": datetime.now().isoformat(timespec="seconds"),
            "since": since.isoformat(), "until": until.isoformat(),
            "background_since": bg_since.isoformat(),
            "profile": profile, "channels": matrix["channels"], "queries": queries}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(plan, ensure_ascii=False, indent=1), "utf-8")
    print(f"plan: {len(queries)} 条检索式 × {len(matrix['directions'])} 方向 "
          f"窗口 {bg_since}~{until}（含 60 天背景窗）-> {a.out}")


# ---------------------------------------------------------------- search

def search_gov(q, cfg, refresh):
    """gov.cn 政策库。searchfield=title 是严格 AND（长词句命中为 0），
    因此同一检索式跑两种模式：标题精确 + 全文召回，由上层关键词过滤收窄。"""
    import urllib.parse as up
    hits = []
    for t in cfg.get("tiers", ["zhengcelibrary_gw", "zhengcelibrary_bm"]):
        for mode in ("title", ""):
            for p in range(1, int(cfg.get("pages", 1)) + 1):
                url = ("https://sousuo.www.gov.cn/search-gov/data?"
                       f"t={t}&q={up.quote(q)}&timetype=timeqb&sort=pubtime&sortType=1"
                       f"&searchfield={mode}&p={p}&n=20")
                raw, meta = http_get(url, refresh)
                if not raw:
                    continue
                data = js(raw) or {}
                lst = (data.get("searchVO") or {}).get("listVO") or []
                if not lst:
                    break
                for it in lst:
                    hits.append({"title": clean(it.get("title")), "url": it.get("url") or "",
                                 "date": (it.get("pubtimeStr") or "").replace(".", "-"),
                                 "publisher": it.get("puborg") or "国务院/部委",
                                 "date_source": "api", "channel": "gov",
                                 "match_mode": mode or "full",
                                 "snippet": clean(it.get("summary"))[:180],
                                 "docno": it.get("pcode") or ""})
    return hits


def search_mee(q, cfg, refresh):
    """生态环境部政策文件列表：日期直接编码在 URL 里（t20261117_），可确定性抽取。
    列表页与关键词无关，整份计划只抓一次，由 cmd_search 用全部检索词并集过滤。"""
    import urllib.parse as up
    hits = []
    for lst_url in cfg.get("lists", []):
        raw, meta = http_get(lst_url, refresh)
        if not raw:
            continue
        soup = BeautifulSoup(to_text(raw, meta), "html.parser")
        for aa in soup.find_all("a", href=True):
            href = str(aa["href"])
            m = re.search(r"t(20\d{2})(\d{2})(\d{2})_\d+\.s?html?$", href)
            if not m:
                continue
            title = clean(aa.get_text(" "))
            if len(title) < 8:
                continue
            url = up.urljoin(lst_url, href)
            hits.append({"title": title, "url": url,
                         "date": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
                         "publisher": "生态环境部", "date_source": "url",
                         "channel": "mee", "snippet": ""})
    return hits


def search_cninfo(q, cfg, refresh):
    hits = []
    win = cfg.get("_window")
    for col in cfg.get("columns", ["sse"]):
        for p in range(1, int(cfg.get("pages", 1)) + 1):
            body = {"pageNum": p, "pageSize": 30, "column": col, "tabName": "fulltext",
                    "stock": "", "seDate": f"{win[0]}~{win[1]}", "searchkey": q,
                    "isHLtitle": "true", "plate": ""}
            raw, meta = http_get("http://www.cninfo.com.cn/new/hisAnnouncement/query",
                                 refresh, post=body)
            if not raw:
                continue
            anns = (js(raw) or {}).get("announcements") or []
            if not anns:
                break
            for it in anns:
                hits.append({"title": clean(it.get("announcementTitle")),
                             "url": "http://static.cninfo.com.cn/" + (it.get("adjunctUrl") or ""),
                             "date": ms_to_date(it.get("announcementTime")),
                             "publisher": clean(it.get("secName")) or "上市公司",
                             "issuer": clean(it.get("secName")),
                             "date_source": "api", "channel": "cninfo", "snippet": "",
                             "stock": it.get("secCode") or ""})
    return hits


def search_web(q, cfg, refresh):
    """必应 RSS：免密可用，但 pubDate 是抓取时间而非发布时间 -> 一律标 date_trusted=no。"""
    import urllib.parse as up
    hits = []
    for p in range(int(cfg.get("pages", 1))):
        url = f"https://cn.bing.com/search?q={up.quote(q)}&format=rss&first={1 + p * 10}"
        raw, meta = http_get(url, refresh)
        if not raw:
            continue
        xml = raw.decode("utf-8", "ignore")
        for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
            t = re.search(r"<title>(.*?)</title>", it, re.S)
            lnk = re.search(r"<link>(.*?)</link>", it, re.S)
            de = re.search(r"<description>(.*?)</description>", it, re.S)
            if not (t and lnk):
                continue
            hits.append({"title": clean(t.group(1)), "url": clean(lnk.group(1)),
                         "date": "", "publisher": "", "date_source": "none",
                         "channel": "web", "snippet": clean(de.group(1))[:180] if de else ""})
    return hits


CHANNELS = {"gov": search_gov, "mee": search_mee, "cninfo": search_cninfo, "web": search_web}

# 免密通用检索（必应 RSS）命中率低且不回日期，这些站点只制造噪声，直接丢
NOISE_HOSTS = ("baike.baidu.com", "zhidao.baidu.com", "zhuanlan.zhihu.com", "zhihu.com",
               "wenku.baidu.com", "docin.com", "toutiao.com", "baijiahao.baidu.com",
               "360doc.com", "mbalib.com", "jianshu.com", "bilibili.com", "douyin.com")


def host_of(url):
    m = re.search(r"https?://([^/:]+)", url or "")
    return (m.group(1) if m else "").lower()


def keywords(q):
    return [w for w in re.split(r"[\s+　]+", q) if len(w) >= 2]


def keep_by_keyword(rows, kw, need_title=1, need_full=2):
    """确定性相关性过滤：标题精确模式要 1 个词，全文召回模式要 2 个词。"""
    out = []
    for r in rows:
        blob = r.get("title", "") + " " + r.get("snippet", "")
        n = sum(1 for k in kw if k in blob)
        if r.get("channel") == "gov":
            ok = n >= (need_title if r.get("match_mode") == "title" else need_full)
        else:
            ok = n >= 1
        if ok:
            out.append(r)
    return out


def cmd_search(a):
    plan = json.loads(Path(a.plan).read_text("utf-8"))
    cfg_all = plan.get("channels") or {}
    out = []

    # mee 列表页与具体检索式无关，全计划只抓一次，用政策方向全部检索词并集过滤
    mee_queries = [q for q in plan["queries"] if q["channel"] == "mee"]
    if mee_queries:
        kw = sorted({k for q in mee_queries for k in keywords(q["query"])})
        rows = search_mee("", dict(cfg_all.get("mee") or {}), a.refresh)
        for r in rows:
            blob = r["title"] + r.get("snippet", "")
            if any(k in blob for k in kw):
                r.update({"qid": "mee-union", "direction": "policy_domestic",
                          "label": mee_queries[0]["label"], "tier_hint": "T1",
                          "query": "union"})
                out.append(r)

    n_req = 1 if mee_queries else 0
    seen = set()
    for q in plan["queries"]:
        ch = q["channel"]
        if ch == "mee":
            continue
        fn = CHANNELS.get(ch)
        if not fn:
            continue
        cfg = dict(cfg_all.get(ch) or {})
        cfg["_window"] = q["window"]
        rows = fn(q["query"], cfg, a.refresh)
        n_req += 1
        if ch == "cninfo":
            # searchkey 是全文匹配：查“陕西煤业”会命中“陕西煤业化工集团”出资人发的别家公告。
            # 只留发行人自自身就是被查主体的那几条。
            rows = [r for r in rows if q["query"] in (r.get("issuer") or "")]
        rows = keep_by_keyword(rows, keywords(q["query"]))
        for r in rows:
            if ch == "web" and any(host_of(r["url"]) == h or host_of(r["url"]).endswith("." + h)
                                    for h in NOISE_HOSTS):
                continue
            key = (ch, r["url"])
            if key in seen:
                continue
            seen.add(key)
            r.update({"qid": q["qid"], "direction": q["direction"], "label": q["label"],
                      "tier_hint": q["tier"], "query": q["query"]})
            out.append(r)

    write_jsonl(a.out, out)
    by_ch, by_dir = {}, {}
    for r in out:
        by_ch[r["channel"]] = by_ch.get(r["channel"], 0) + 1
        by_dir[r["direction"]] = by_dir.get(r["direction"], 0) + 1
    print(f"search: {len(out)} 条候选，{n_req} 次查询")
    print(f"        按通道 {by_ch}")
    print(f"        按方向 {by_dir}")


# ---------------------------------------------------------------- fetch

def _pick_body(soup):
    for tag in soup(["script", "style", "nav", "aside", "header", "footer", "form", "noscript"]):
        tag.decompose()
    sels = ["article", "div#content", "div.content", "div.TRS_Editor", "div.article",
            "div#UCAP-CONTENT", "div.article-content", "div#zoom", "div.main-content",
            "div.article_content", "div.pages_content", "div.text", "div.detail",
            "div#article", "div.news_content", "div#news"]
    cands = [n for s in sels for n in soup.select(s)]
    if not cands:
        cands = [soup.body or soup]
    def score(n):
        txt = n.get_text(" ")
        return len(CJK.findall(txt)) - 3 * len(CJK.findall(" ".join(x.get_text(" ") for x in n.find_all("a"))))
    return max(cands, key=score)


def _meta(soup, *keys):
    for k in keys:
        for attr in ("property", "name", "itemprop"):
            n = soup.find("meta", attrs={attr: re.compile(f"^{re.escape(k)}$", re.I)})
            if n and n.get("content", "").strip():
                return n["content"].strip()
    return ""


def pdf_text(raw, max_pages, max_chars):
    """从 PDF 抽正文（公告的吨数/金额都在这里）。抽不到返回空串。"""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        log("未安装 PyPDF2，PDF 正文跳过")
        return ""
    try:
        reader = PdfReader(io.BytesIO(raw))
        parts = [(pg.extract_text() or "") for pg in reader.pages[:max_pages]]
    except Exception as e:  # 扫描件/加密件直接放弃，不退化成编造
        log(f"PDF 解析失败（{type(e).__name__}），仅用标题元数据")
        return ""
    return re.sub(r"\n{2,}", "\n", "\n".join(parts))[:max_chars]


def _enrich(rec, body):
    """正文落地之后的确定性加工：数字证据、抽取式摘要、日期回填与冲突标记。"""
    rec["body"] = body
    rec["body_chars"] = len(CJK.findall(body))

    # 数字抽取：数字 + 单位 + 所在整句，作为"不许编数字"的证据
    for m in NUM_RE.finditer(body):
        s0 = max(body.rfind("。", 0, m.start()), body.rfind("\n", 0, m.start())) + 1
        s1 = body.find("。", m.end())
        sent = re.sub(r"\s+", "", body[s0: s1 + 1 if s1 > 0 else m.end() + 60])[:160]
        rec["numbers"].append({"value": m.group(1) + m.group(2), "evidence": sent})
        if len(rec["numbers"]) >= 40:
            break

    # 抽取式摘要：按"含数字/含政策动作词/靠前"打分，取前 5 句保留原序
    sents = [s.strip() for s in re.split(r"(?<=[。！？])", body[:6000]) if len(CJK.findall(s)) >= 12]
    ACT = ("发布", "施行", "征求意见", "截止", "印发", "上调", "下调", "立项", "批复", "实施", "通知", "公告")
    scored = []
    for i, s in enumerate(sents[:60]):
        sc = 2 * len(NUM_RE.findall(s)) + 2 * sum(k in s for k in ACT) + max(0, 3 - i * 0.2)
        scored.append((sc, i, s))
    top = sorted(sorted(scored, key=lambda x: -x[0])[:5], key=lambda x: x[1])
    rec["key_sentences"] = [{"sent": s[:200], "score": round(sc, 1), "pos": i} for sc, i, s in top]
    return rec


def extract_doc(url, raw, meta, hint=None, pdf_pages=8):
    hint = hint or {}
    rec = {"url": url, "title": hint.get("title") or "", "publisher": hint.get("publisher") or "",
           "date": "", "date_source": "none", "body": "", "body_chars": 0,
           "numbers": [], "key_sentences": []}
    ctype = (meta.get("ctype") or "").lower()
    is_pdf = "pdf" in ctype or url.lower().endswith(".pdf")

    if is_pdf:
        body = pdf_text(raw, pdf_pages, 12000)
        rec["body_source"] = "pdf" if body else "pdf_meta_only"
        cand = hint.get("date") or ""
        rec["date_source"] = "api" if cand else "none"
        if not cand:  # 公告 PDF 首页通常写着 "2026年11月14日"
            for m in DATE_CN.finditer(body[:800]):
                y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 2015 <= y <= date.today().year + 1 and 1 <= mo <= 12 and 1 <= dd <= 31:
                    cand, rec["date_source"] = f"{y}-{mo:02d}-{dd:02d}", "body"
                    break
        rec["date"] = cand
        if not rec["title"]:
            first = [ln.strip() for ln in body.splitlines() if len(CJK.findall(ln)) > 6]
            rec["title"] = first[0][:120] if first else ""
        rec["date_hint"] = hint.get("date") or ""
        rec["date_conflict"] = False  # PDF 日期取自公告接口，不参与冲突判定
        return _enrich(rec, body)

    soup = BeautifulSoup(to_text(raw, meta), "html.parser")
    if not rec["title"]:
        rec["title"] = clean(_meta(soup, "og:title", "twitter:title") or
                             (soup.title.get_text(" ") if soup.title else ""))
    if not rec["publisher"]:
        rec["publisher"] = clean(_meta(soup, "og:site_name", "publisher", "application-name"))
        if not rec["publisher"] and " - " in rec["title"]:
            rec["publisher"] = rec["title"].split(" - ")[-1].strip()

    # 日期：JSON-LD > meta > URL > 正文，逐级降级并记录来源
    cand = ""
    for sc in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        cand = _ld_date(sc.string)
        if cand:
            rec["date_source"] = "jsonld"
            break
    if not cand:
        mv = _meta(soup, *META_DATE_KEYS)
        if mv:
            m = DATE_CN.search(mv) or re.search(r"(20\d{2})-(\d{2})-(\d{2})", mv)
            if m:
                cand = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                rec["date_source"] = "meta"
    if not cand:
        m = (re.search(r"/t(20\d{2})(\d{2})(\d{2})_", url) or
             re.search(r"/(20\d{2})-(\d{2})/(\d{2})/", url) or
             re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", url) or
             re.search(r"/(20\d{2})-(\d{2})-(\d{2})", url))
        if m:
            cand = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            rec["date_source"] = "url"
    body_node = _pick_body(soup)
    body = re.sub(r"[ \t\u3000]+", " ", body_node.get_text("\n")).strip()
    body = re.sub(r"\n{2,}", "\n", body)
    rec["body_source"] = "html"
    if not cand:
        for m in DATE_CN.finditer(body[:1200]):
            y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2015 <= y <= date.today().year + 1 and 1 <= mo <= 12 and 1 <= dd <= 31:
                cand, rec["date_source"] = f"{y}-{mo:02d}-{dd:02d}", "body"
                break
    rec["date"] = cand or hint.get("date") or ""
    if rec["date"] and rec["date_source"] == "none":
        rec["date_source"] = "api"
    # 模型声称的日期与页面实际抽取的日期不一致 -> 记下冲突，以页面为准
    rec["date_hint"] = hint.get("date") or ""
    rec["date_conflict"] = bool(rec["date_hint"] and rec["date"]
                                and rec["date_hint"] != rec["date"])
    return _enrich(rec, body)


def read_ingest(path, direction):
    """外部输入清单。.jsonl 走 JSON，其余按 TSV（url[\t标题\t日期\t机构]）。"""
    rows = []
    p = Path(path)
    if p.suffix.lower() == ".jsonl":
        for r in read_jsonl(p):
            rows.append({"url": r.get("url", ""), "title": r.get("title", ""),
                         "date": r.get("date", ""), "publisher": r.get("publisher", ""),
                         "sid": r.get("sid", ""), "date_source": "manual",
                         "channel": "ingest",
                         "direction": r.get("direction") or direction or "external",
                         "label": r.get("direction") or direction or "外部输入",
                         "note": r.get("note", ""), "tier_hint": "T1",
                         "qid": "ingest", "query": ""})
        return rows
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        rows.append({"url": parts[0], "title": parts[1] if len(parts) > 1 else "",
                     "date": parts[2] if len(parts) > 2 else "",
                     "publisher": parts[3] if len(parts) > 3 else "",
                     "date_source": "manual", "channel": "ingest",
                     "direction": direction or "external", "label": direction or "外部输入",
                     "tier_hint": "T1", "qid": "ingest", "query": ""})
    return rows


def cmd_fetch(a):
    rows = []
    if a.hits:
        rows += read_jsonl(a.hits)
    if a.ingest:
        for f in a.ingest:
            rows += read_ingest(f, a.direction)
    # 同 URL 去重，保留首次出现的元数据
    uniq, seen = [], set()
    for r in rows:
        u = (r.get("url") or "").split("#")[0]
        if not u.startswith("http") or u in seen:
            continue
        seen.add(u)
        uniq.append(r)
    docs = []
    for i, r in enumerate(uniq, 1):
        raw, meta = http_get(r["url"], a.refresh)
        if not raw:
            docs.append({**r, "fetch_error": meta.get("error", "empty"), "body": "",
                         "date_source": r.get("date_source") or "none", "numbers": [],
                         "key_sentences": [], "body_chars": 0, "body_source": "error"})
            continue
        doc = extract_doc(r["url"], raw, meta, hint=r)
        doc.update({k: r.get(k) for k in ("qid", "direction", "label", "tier_hint",
                                          "channel", "query", "snippet", "sid",
                                          "note", "issuer", "stock")})
        doc["body_sha256"] = hashlib.sha256(
            re.sub(r"\s+", "", doc["body"]).encode()).hexdigest()[:16] if doc["body"] else ""
        docs.append(doc)
        if i % 10 == 0:
            print(f"  fetch {i}/{len(uniq)}")
    write_jsonl(a.out, docs)
    ok = sum(1 for x in docs if not x.get("fetch_error"))
    dated = sum(1 for x in docs if x.get("date"))
    print(f"fetch: {len(docs)} 篇（成功 {ok}，带日期 {dated}）-> {a.out}")


# ---------------------------------------------------------------- ledger

def domain_of(url):
    m = re.search(r"https?://([^/]+)/", url + "/")
    return (m.group(1) if m else "").lower()


def tier_of(url, hint=None):
    host = domain_of(url)
    for t in ("T1", "T2", "T3"):
        for suf in TIER_SUFFIX[t]:
            if host == suf or host.endswith("." + suf):
                return t
    return "T4"


def norm_title(t):
    return re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]", "", t or "")


def bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def jaccard(x, y):
    a, b = bigrams(x), bigrams(y)
    return len(a & b) / max(1, len(a | b))


def cmd_ledger(a):
    docs = []
    for f in a.docs:
        docs += read_jsonl(f)
    since, until = d(a.since), d(a.until)
    bg_since = since - timedelta(days=60)
    rows = []
    for x in docs:
        t = tier_of(x["url"], x.get("tier_hint"))
        dt = x.get("date") or ""
        bucket = "undated"
        if dt:
            try:
                dv = d(dt)
                bucket = ("in_window" if since <= dv <= until else
                          "background_60d" if bg_since <= dv < since else
                          "future" if dv > until else "stale")
            except Exception:
                bucket = "undated"
        rows.append({**x, "tier": t, "date_bucket": bucket,
                     "publisher": x.get("publisher") or "",
                     "ntitle": norm_title(x.get("title"))})

    # 事件去重：标题字符二元组 Jaccard ≥ 0.72 且发布时间相近（≤ 10 天）才算同一事件。
    # 只有标题相似不够——“…8月份主要运营数据公告”与“…10月份主要运营数据公告”标题
    # 几乎一样却是两个事件，必须靠日期距离把它们分开。
    rows.sort(key=lambda r: (TIER_RANK[r["tier"]], r.get("date") or "9999"))

    def near(a1, a2, days=10):
        if not (a1 and a2):
            return True
        try:
            return abs((d(a1) - d(a2)).days) <= days
        except ValueError:
            return True

    events = []
    for r in rows:
        for ev in events:
            if jaccard(r["ntitle"], ev["_nt"]) >= 0.72 and near(r.get("date"), ev.get("date")):
                ev["also_reported_by"].append(
                    {"title": r["title"], "url": r["url"], "tier": r["tier"], "channel": r.get("channel")})
                break
        else:
            events.append({**r, "_nt": r["ntitle"], "also_reported_by": []})

    # 入账条件：权威度 <= T3（T4 只作线索）、有日期、有标题。不满足的留档但不编号。
    usable, rejected = [], []
    for ev in events:
        reason = ""
        if ev["tier"] == "T4":
            reason = "T4 自媒体/聚合，按质量线不入引用账"
        elif ev["date_bucket"] == "undated":
            reason = "无发布日期，不满足'可核验'"
        elif ev["date_bucket"] == "future":
            reason = "日期晚于统计期末"
        elif ev["date_bucket"] == "stale":
            reason = "发布日期早于背景窗（since-60d）"
        elif not ev.get("publisher"):
            reason = "无来源机构"
        if reason:
            ev["reject_reason"] = reason
            rejected.append(ev)
        else:
            usable.append(ev)

    usable.sort(key=lambda r: (r["direction"], TIER_RANK[r["tier"]],
                               r["date_bucket"] != "in_window", r.get("date") or ""))
    # 审计外部台账时保留它自己的编号，才能检验"引用编号是否闭环"
    keep = getattr(a, "keep_ids", False)
    used_ids = set()
    for i, ev in enumerate(usable, 1):
        own = (ev.get("sid") or "").strip() if keep else ""
        if own and own not in used_ids:
            ev["sid"] = own
        else:
            ev["sid"] = f"S{i:02d}"
        used_ids.add(ev["sid"])
        ev.pop("_nt", None)

    stats = {
        "n_docs": len(docs), "n_events": len(events), "n_usable": len(usable),
        "n_rejected": len(rejected),
        "rejected_reasons": {k: sum(1 for r in rejected if r["reject_reason"] == k)
                             for k in {r["reject_reason"] for r in rejected}},
        "by_direction": {dd: sum(1 for r in usable if r["direction"] == dd)
                         for dd in sorted({r["direction"] for r in rows})},
        "by_tier": {t: sum(1 for r in usable if r["tier"] == t) for t in ("T1", "T2", "T3")},
        "by_bucket": {b: sum(1 for r in usable if r["date_bucket"] == b)
                      for b in ("in_window", "background_60d")},
        "date_source": {},
        "n_with_publisher": sum(1 for r in usable if r.get("publisher")),
        "n_with_numbers": sum(1 for r in usable if r.get("numbers")),
    }
    for r in usable:
        stats["date_source"][r["date_source"]] = stats["date_source"].get(r["date_source"], 0) + 1

    out = {"generated_at": datetime.now().isoformat(timespec="seconds"),
           "since": a.since, "until": a.until, "background_since": bg_since.isoformat(),
           "stats": stats, "sources": usable, "rejected": rejected}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")

    # 事实卡：确定性列全部填好，判断列留空给模型
    import csv
    if a.cards:
        with open(a.cards, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sid", "日期", "来源机构", "标题", "类别", "权威度", "时效",
                        "链接", "关键数字", "建议动作【模型填】", "影响方向【模型填】",
                        "影响量级【模型填】", "与客户的关系【模型填】"])
            for r in usable:
                w.writerow([r["sid"], r["date"], r.get("publisher", ""), r["title"],
                            r["label"], r["tier"], r["date_bucket"], r["url"],
                            "; ".join(n["value"] for n in r.get("numbers", [])[:4]),
                            "", "", "", ""])
    if a.md:
        # 这张表同时是 `build_report.py --check` 认的来源表，可直接当报告附录粘过去
        lines = [f"# 事实台账（{a.since} ~ {a.until}）", "",
                 f"- 候选 {stats['n_docs']} 篇 → 归并事件 {stats['n_events']} 起 → "
                 f"入账 {stats['n_usable']} 条，剔除 {stats['n_rejected']} 条",
                 f"- 剔除原因：{json.dumps(stats['rejected_reasons'], ensure_ascii=False)}",
                 f"- 方向覆盖：{json.dumps(stats['by_direction'], ensure_ascii=False)}", "",
                 "## 来源清单", "",
                 "| 编号 | 机构 | 日期 | 类别 | 时效 | 标题 | 链接 |",
                 "|---|---|---|---|---|---|---|"]
        for r in usable:
            lines.append(f"| {r['sid']} | {r.get('publisher', '')} | {r['date']} | {r['label']} | "
                         f"{r['date_bucket']} | {r['title'][:60].replace('|', '/')} | {r['url']} |")
        Path(a.md).write_text("\n".join(lines) + "\n", "utf-8")
    print(f"ledger: 候选 {len(docs)} → 事件 {len(events)} → 入账 {len(usable)}，"
          f"剔除 {len(rejected)}（{stats['rejected_reasons']}）")
    print(f"        方向覆盖 {stats['by_direction']}  时效 {stats['by_bucket']}")


# ---------------------------------------------------------------- check

REQ_DIRECTIONS = ["policy_domestic", "policy_intl", "rating", "industry", "client", "peer"]


def cmd_check(a):
    led = json.loads(Path(a.ledger).read_text("utf-8"))
    usable = led["sources"]
    errs, warns = [], []
    ids = {r["sid"] for r in usable}

    miss = [dd for dd in REQ_DIRECTIONS if not any(r["direction"] == dd for r in usable)]
    if miss:
        errs.append(f"台账方向覆盖不足，缺：{miss}（硬性质量线要求六方向缺一不可）")
    if led["stats"]["n_with_publisher"] < len(usable):
        errs.append(f"{len(usable) - led['stats']['n_with_publisher']} 条入账条目无来源机构")
    bad = [r["sid"] for r in usable if r["date_source"] in ("none", "")]
    if bad:
        errs.append(f"{len(bad)} 条入账条目日期来源不明：{bad[:5]}")

    if a.report:
        md = Path(a.report).read_text("utf-8")
        # 引用编号容错：兼容 [S01]、〔S01〕、（S01）、S01、 等写法
        cited = set(re.findall(r"(?<![A-Za-z])(S\d{1,3})(?!\d)", md))
        unknown = cited - ids
        if unknown:
            errs.append(f"引用编号未闭环（报告引用了台账里没有的编号）：{sorted(unknown)}")
        unused = ids - cited
        if unused:
            print(f"[INFO ] 台账为候选池，{len(unused)} 条未入报告正文（属正常，不计警告）")
        # 六方向是“报告”的质量线，不是台账的：每个方向至少要有一条被正文引用
        cited_rows = [r for r in usable if r["sid"] in cited]
        gap = [dd for dd in REQ_DIRECTIONS if not any(r["direction"] == dd for r in cited_rows)]
        if gap:
            errs.append(f"报告正文未覆盖方向：{gap}（六方向缺一不可）")
        # 数字可溯源：报告里带单位的数字必须能在来源正文/标题中找到
        pool = set()
        for r in usable:
            pool |= num_tokens((r.get("body") or "") + " " + (r.get("title") or "") +
                              " " + " ".join(n["value"] for n in r.get("numbers", [])))
        misses = [f"{t[1]:,.4g}" for t in num_tokens(md) if not num_hit(t, pool)]
        if misses:
            warns.append(f"{len(misses)} 个数字未在来源中命中（需人工确认或标为脚本计算值）："
                         f"{sorted(set(misses))[:8]}")
        # 期外条目出现在正文：允许但必须标"（背景）"
        for r in usable:
            if r["date_bucket"] == "background_60d" and r["sid"] in cited:
                i = md.find(r["sid"])
                if i > 0 and "背景" not in md[max(0, i - 160): i + 160]:
                    warns.append(f"{r['sid']} 属期外（{r['date']} 发布），"
                                 f"正文引用处未标注'（背景）'")
        # 占位符
        for bad_s in ("（待补充）", "TODO", "待补充", "xxx", "XXX"):
            if bad_s in md:
                errs.append(f"正文存在占位符：{bad_s}")

    print("=" * 60)
    for e in errs:
        print("[ERROR]", e)
    for w in warns:
        print("[WARN ]", w)
    if not errs and not warns:
        print("✅ 全部门禁通过")
    print("=" * 60)
    print(f"台账 {len(usable)} 条 · 方向 {len([1 for dd in REQ_DIRECTIONS if any(r['direction'] == dd for r in usable)])}/6 "
          f"· 期外剔除 {led['stats']['rejected_reasons']}")
    return 1 if (errs or (a.strict and warns)) else 0


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description="ESG 月报检索与归集确定性管线")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("plan", help="生成检索计划")
    q.add_argument("--profile", required=True)
    q.add_argument("--matrix", default=str(Path(__file__).resolve().parent.parent /
                                           "references/search-matrix.json"))
    q.add_argument("--since", required=True)
    q.add_argument("--until", required=True)
    q.add_argument("--out", required=True)
    q.set_defaults(fn=cmd_plan)

    q = sub.add_parser("search", help="执行检索计划")
    q.add_argument("--plan", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--refresh", action="store_true")
    q.set_defaults(fn=cmd_search)

    q = sub.add_parser("fetch", help="抓正文并结构化")
    q.add_argument("--hits")
    q.add_argument("--ingest", nargs="+",
                   help="外部清单，可多份：.jsonl 或 TSV（每行 url[\\t标题\\t日期\\t机构]）")
    q.add_argument("--direction", help="ingest 条目归属方向")
    q.add_argument("--out", required=True)
    q.add_argument("--refresh", action="store_true")
    q.set_defaults(fn=cmd_fetch)

    q = sub.add_parser("ledger", help="去重/分档/编号")
    q.add_argument("--docs", nargs="+", required=True, help="可多份 docs.jsonl，自动合并")
    q.add_argument("--since", required=True)
    q.add_argument("--until", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--cards")
    q.add_argument("--md")
    q.add_argument("--keep-ids", action="store_true",
                   help="保留外部台账自带编号（用于审计手工整理的来源清单）")
    q.set_defaults(fn=cmd_ledger)

    q = sub.add_parser("check", help="硬门禁")
    q.add_argument("--ledger", required=True)
    q.add_argument("--report")
    q.add_argument("--strict", action="store_true")
    q.set_defaults(fn=cmd_check)

    a = p.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
