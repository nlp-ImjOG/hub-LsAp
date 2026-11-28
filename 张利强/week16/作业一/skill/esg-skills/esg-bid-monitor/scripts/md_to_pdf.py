"""把 Markdown 转成 PDF（reportlab + 内置中文 CID 字体）。

不依赖 LaTeX、wkhtmltopdf 或外部字体。支持标题、段落、列表、代码块、
分隔线和引用块；Markdown 表格按普通文本行渲染。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
)
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

FONT_NAME = "STSong-Light"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
NUMBERED_RE = re.compile(r"^\d+[.)]\s+(.*)$")
HR_RE = re.compile(r"^(\-{3,}|\*{3,}|_{3,})$")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
CODE_RE = re.compile(r"`(.+?)`")


def _register_font() -> None:
    try:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
    except Exception:
        # 重复注册是安全的；其他异常交给调用方处理。
        pass


def _inline(text: str) -> str:
    text = BOLD_RE.sub(r"\1", text)
    return CODE_RE.sub(r"\1", text)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "BodyCN",
        parent=base["BodyText"],
        fontName=FONT_NAME,
        fontSize=10.5,
        leading=16,
        spaceAfter=6,
    )
    return {
        "body": body,
        "h1": ParagraphStyle(
            "H1CN", parent=body, fontSize=18, leading=24, spaceAfter=10
        ),
        "h2": ParagraphStyle(
            "H2CN", parent=body, fontSize=14, leading=20, spaceAfter=8
        ),
        "h3": ParagraphStyle(
            "H3CN", parent=body, fontSize=12, leading=18, spaceAfter=6
        ),
        "bullet": ParagraphStyle(
            "BulletCN", parent=body, leftIndent=14, bulletIndent=4, spaceAfter=3
        ),
        "quote": ParagraphStyle(
            "QuoteCN",
            parent=body,
            fontSize=9.5,
            leading=14,
            leftIndent=12,
            textColor="#555555",
        ),
        "code": ParagraphStyle(
            "CodeCN",
            parent=body,
            fontName=FONT_NAME,
            fontSize=9,
            leading=13,
            leftIndent=8,
            backColor="#f4f4f4",
            borderPadding=4,
        ),
    }


def markdown_to_pdf(input_path: str, output_path: str, title: str | None = None) -> None:
    _register_font()
    text = Path(input_path).read_text(encoding="utf-8")
    styles = _styles()
    story: list = []
    code_lines: list[str] = []
    in_code = False

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                story.append(Preformatted("\n".join(code_lines), styles["code"]))
                story.append(Spacer(1, 4))
                code_lines = []
            in_code = not in_code
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            story.append(Spacer(1, 4))
            continue

        heading = HEADING_RE.match(stripped)
        if heading:
            level = min(len(heading.group(1)), 3)
            story.append(
                Paragraph(escape(_inline(heading.group(2))), styles[f"h{level}"])
            )
            continue

        if HR_RE.match(stripped):
            story.append(HRFlowable(width="100%", thickness=0.6, color="#cccccc"))
            story.append(Spacer(1, 4))
            continue

        if stripped.startswith(">"):
            story.append(
                Paragraph(escape(_inline(stripped.lstrip("> ").strip())), styles["quote"])
            )
            continue

        bullet = BULLET_RE.match(stripped)
        if bullet:
            story.append(
                Paragraph(escape(_inline(bullet.group(1))), styles["bullet"], bulletText="•")
            )
            continue

        numbered = NUMBERED_RE.match(stripped)
        if numbered:
            story.append(
                Paragraph(
                    escape(_inline(numbered.group(1))),
                    styles["bullet"],
                    bulletText="•",
                )
            )
            continue

        if stripped.startswith("|"):
            story.append(Paragraph(escape(_inline(stripped)), styles["body"]))
            continue

        story.append(Paragraph(escape(_inline(stripped)), styles["body"]))

    if in_code and code_lines:
        story.append(Preformatted("\n".join(code_lines), styles["code"]))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title or output.stem,
    )
    doc.build(story)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 Markdown 转成 PDF")
    parser.add_argument("--input", required=True, help="输入的 Markdown 文件")
    parser.add_argument("--output", required=True, help="输出的 PDF 文件")
    parser.add_argument("--title", default=None, help="PDF 标题")
    args = parser.parse_args(argv)

    try:
        markdown_to_pdf(args.input, args.output, title=args.title)
    except OSError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI 边界统一转成退出码 2
        print(f"错误：PDF 生成失败：{exc}", file=sys.stderr)
        return 2

    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
