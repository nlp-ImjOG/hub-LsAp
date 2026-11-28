"""Markdown 报告生成工具：标题 / 表格 / 落地保存。"""
from __future__ import annotations

import os
from datetime import datetime


def h(level: int, text: str) -> str:
    return f"{'#' * level} {text}\n"


def table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def bullet(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) + "\n"


def banner(text: str) -> str:
    return f"> {text}\n"


def save(path: str, content: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return os.path.abspath(path)


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
