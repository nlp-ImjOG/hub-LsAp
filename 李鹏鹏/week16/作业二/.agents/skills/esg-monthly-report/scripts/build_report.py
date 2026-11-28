#!/usr/bin/env python
"""ESG 月报渲染器 + 引用质检。

用法：
    python scripts/build_report.py report.md --html report.html
    python scripts/build_report.py report.md --check          # 只做质检
    python scripts/build_report.py report.md --check --strict  # 有错就非零退出

实现了两件事：
1. Markdown -> 单文件 HTML（目录、表格、引用块、图片内嵌 base64、原生 HTML 直通）
2. 引用质检：正文里的 [n] 必须能在文末「来源」表格中找到对应编号，且来源必须含日期与链接

只依赖标准库。
"""

from __future__ import annotations

import argparse
import base64
import html as htmllib
import re
from pathlib import Path

CSS_FILE = Path(__file__).resolve().parent.parent / "assets" / "report.css"

DEFAULT_CSS = """
:root{--ink:#0f172a;--sub:#475569;--line:#e2e8f0;--accent:#0f766e;--warn:#b45309;--bg:#fff}
*{box-sizing:border-box}
body{margin:0;background:#eef2f6;color:var(--ink);
 font:16px/1.78 -apple-system,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif}
.page{max-width:980px;margin:0 auto;background:var(--bg);padding:60px 68px 72px;
 box-shadow:0 1px 3px rgba(15,23,42,.1)}
"""


# ------------------------------------------------------------------ 行内渲染

def inline(text: str) -> str:
    text = htmllib.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', text)
    # 引用编号 [1] [S01] 〔S01〕 渲染成上标；〔2026〕这类“文号”不算引用（〔〕必须带 S）
    text = re.sub(r"\[S?(\d+(?:\s*[,，\-–]\s*\d+)*)\]|〔S(\d+(?:\s*[,，\-–]\s*\d+)*)〕",
                  lambda m: f'<sup class="cite">[{m.group(1) or m.group(2)}]</sup>', text)
    return text


# ------------------------------------------------------------------ 块渲染

TABLE_SEP = re.compile(r"^\|[\s:|-]+\|$")


def render_blocks(md: str, base_dir: Path) -> tuple[str, list[dict]]:
    lines = md.split("\n")
    out: list[str] = []
    toc: list[dict] = []
    i = 0

    while i < len(lines):
        ln = lines[i]

        # 原生 HTML 块直通（卡片 / 时间线等自定义组件）
        if ln.strip().startswith("<") and not re.match(r"^<(sup|a|code|strong|em)\b", ln.strip()):
            buf = []
            while i < len(lines) and lines[i].strip():
                buf.append(lines[i])
                i += 1
            out.append("\n".join(buf))
            continue

        # 表格
        if ln.startswith("|") and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1].strip()):
            head = [c.strip() for c in ln.strip().strip("|").split("|")]
            aligns = [("right" if c.strip().endswith(":") else "left")
                      for c in lines[i + 1].strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            th = "".join(f'<th style="text-align:{aligns[k] if k < len(aligns) else "left"}">'
                         f'{inline(c)}</th>' for k, c in enumerate(head))
            body = "".join(
                "<tr>" + "".join(
                    f'<td style="text-align:{aligns[k] if k < len(aligns) else "left"}">{inline(c)}</td>'
                    for k, c in enumerate(r)) + "</tr>"
                for r in rows)
            out.append(f"<div class='tw'><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>")
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)", ln)
        if m:
            level, text = len(m.group(1)), m.group(2).strip()
            anchor = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", text).strip("-").lower() or f"h{len(toc)}"
            if level >= 2:
                toc.append({"level": level, "text": text, "anchor": anchor})
            out.append(f'<h{level} id="{anchor}">{inline(text)}</h{level}>')
            i += 1
            continue

        # 图片（相对路径 -> base64 内嵌）
        m = re.match(r"^!\[(.*?)\]\((.+?)\)\s*$", ln)
        if m:
            alt, src = m.group(1), m.group(2)
            p = Path(src) if Path(src).is_absolute() else (base_dir / src)
            if p.exists():
                b64 = base64.b64encode(p.read_bytes()).decode()
                mime = "image/svg+xml" if p.suffix == ".svg" else "image/png"
                out.append(f'<figure><img alt="{htmllib.escape(alt)}" '
                           f'src="data:{mime};base64,{b64}">'
                           + (f"<figcaption>{inline(alt)}</figcaption>" if alt else "")
                           + "</figure>")
            else:
                out.append(f'<p class="missing">[缺图: {htmllib.escape(src)}]</p>')
            i += 1
            continue

        # 引用块
        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip("> ").rstrip())
                i += 1
            out.append(f"<blockquote>{'<br>'.join(inline(x) for x in buf)}</blockquote>")
            continue

        # 有序 / 无序列表（支持一层缩进）
        if re.match(r"^\s*(?:[-*]|\d+\.)\s+", ln):
            ordered = bool(re.match(r"^\s*\d+\.\s+", ln))
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while i < len(lines) and re.match(r"^\s*(?:[-*]|\d+\.)\s+", lines[i]):
                raw = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", lines[i])
                sub = []
                j = i + 1
                while j < len(lines) and re.match(r"^\s{2,}(?:[-*]|\d+\.)\s+", lines[j]):
                    sub.append(re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", lines[j]))
                    j += 1
                if sub:
                    sub_html = "<ul>" + "".join(f"<li>{inline(s)}</li>" for s in sub) + "</ul>"
                    items.append(f"<li>{inline(raw)}{sub_html}</li>")
                    i = j
                else:
                    items.append(f"<li>{inline(raw)}</li>")
                    i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        # 分隔线
        if re.match(r"^(---+|\*\*\*+)$", ln.strip()):
            out.append("<hr>")
            i += 1
            continue

        if not ln.strip():
            i += 1
            continue

        # 段落
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,4}\s|!\[|\||>|\s*[-*]\s|\s*\d+\.\s|---)", lines[i]):
            buf.append(lines[i])
            i += 1
        if buf:
            out.append(f"<p>{inline(' '.join(buf))}</p>")
        else:
            i += 1

    return "\n".join(out), toc


def build_toc(toc: list[dict]) -> str:
    if not toc:
        return ""
    items = "".join(
        f'<li class="lv{t["level"]}"><a href="#{t["anchor"]}">{htmllib.escape(t["text"])}</a></li>'
        for t in toc)
    return f'<nav class="toc"><div class="toc-t">目录</div><ul>{items}</ul></nav>'


# ------------------------------------------------------------------ 质检

# 引用编号：兼容 [1] / [S01] / 〔S01〕。〔〕必须带 S——中文公文里〔2026〕是文号，不是引用。
CITE_RE = re.compile(r"\[S?(\d+(?:\s*[,，\-–]\s*\d+)*)\]|〔S(\d+(?:\s*[,，\-–]\s*\d+)*)〕")
SOURCE_ROW_RE = re.compile(r"^\|\s*\[?S?(\d+)\]?\s*\|(.*)\|\s*$")


def parse_sources(md: str) -> dict[int, dict]:
    """从文末来源表格里抽取编号 -> {org, date, url}。"""
    sources: dict[int, dict] = {}
    for line in md.split("\n"):
        m = SOURCE_ROW_RE.match(line.strip())
        if not m:
            continue
        sid, rest = int(m.group(1)), m.group(2)
        url = re.search(r"https?://[^\s|)]+", rest)
        date = re.search(r"20\d{2}-\d{2}(?:-\d{2})?", rest)
        sources[sid] = {"raw": rest.strip(), "url": url.group(0) if url else "",
                        "date": date.group(0) if date else ""}
    return sources


def check(md: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    sources = parse_sources(md)

    cited: set[int] = set()
    for m in CITE_RE.finditer(md):
        for part in re.split(r"[,，]", m.group(1) or m.group(2)):
            part = part.strip()
            if re.match(r"^\d+$", part):
                cited.add(int(part))
            elif re.match(r"^\d+\s*[-–]\s*\d+$", part):
                a, b = [int(x) for x in re.split(r"[-–]", part)]
                cited.update(range(a, b + 1))

    if not sources:
        errors.append("未找到「来源」表格：文末必须有 | 编号 | 机构 | 日期 | 链接 | 的表格")
    for n in sorted(cited):
        if n not in sources:
            errors.append(f"正文引用了 [{n}]，但来源表中没有编号 {n}")
    for n, s in sources.items():
        if not s["url"]:
            errors.append(f"来源 [{n}] 缺链接")
        if not s["date"]:
            warns.append(f"来源 [{n}] 缺发布日期")
    for n in sorted(set(sources) - cited):
        warns.append(f"来源 [{n}] 定义但正文未引用")

    # 未带引用的"事实句"提示：含数字与机构名的句子最好有引用
    for para in md.split("\n"):
        s = para.strip()
        if s.startswith(("|", "#", ">", "-", "*", "!")) or len(s) < 40:
            continue
        if re.search(r"\d{4}年|\d+\.\d+%|\d+\s*(?:万|亿)元", s) and not CITE_RE.search(s):
            warns.append(f"疑似缺引用（含数字与结论）：{s[:48]}…")

    # 占位符检查
    for bad in ["待补充", "TODO", "TBD", "XX", "（略）"]:
        if bad in md:
            errors.append(f"存在占位符「{bad}」，交付前必须替换")

    return errors, warns


# ------------------------------------------------------------------ CLI

def cmd(a) -> int:
    md_path = Path(a.markdown)
    md = md_path.read_text(encoding="utf-8")

    if a.check or a.strict:
        errors, warns = check(md)
        print(f"引用质检：{md_path.name}")
        for e in errors:
            print(f"  ✗ {e}")
        for w in warns[:40]:
            print(f"  · {w}")
        if len(warns) > 40:
            print(f"  · …… 另有 {len(warns) - 40} 条提示")
        print(f"结论：{len(errors)} 个错误，{len(warns)} 条提示")
        if a.strict and errors:
            return 1
        if not a.html:
            return 0

    if not a.html:
        print("未指定 --html，仅完成质检。")
        return 0

    body, toc = render_blocks(md, md_path.parent)
    title_m = re.search(r"^#\s+(.*)", md, re.M)
    title = title_m.group(1).strip() if title_m else md_path.stem
    css = CSS_FILE.read_text(encoding="utf-8") if CSS_FILE.exists() else DEFAULT_CSS

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{htmllib.escape(title)}</title>
<style>{css}</style></head>
<body><div class="page">
{build_toc(toc)}
{body}
<footer class="doc-foot">本文件由 esg-monthly-report 技能生成 · {md_path.name}</footer>
</div></body></html>"""
    Path(a.html).write_text(doc, encoding="utf-8")
    print(f"HTML -> {a.html}（{len(doc) / 1024:.0f} KB，{len(toc)} 个章节）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ESG 月报渲染 + 引用质检")
    ap.add_argument("markdown")
    ap.add_argument("--html", help="输出单文件 HTML")
    ap.add_argument("--check", action="store_true", help="只做引用质检")
    ap.add_argument("--strict", action="store_true", help="有错误时返回非零退出码")
    return cmd(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
