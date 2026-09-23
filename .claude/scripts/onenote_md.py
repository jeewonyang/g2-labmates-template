"""Convert OneNote page XML (from the desktop COM API) to markdown.

Deterministic and local: no model sees a page on its way in. The COM export
itself is `onenote_export.ps1`; this module turns each exported page into
markdown that keeps what a lab notebook needs - the outline structure, tables
(OneNote pages are mostly tables of conditions and results), and a marker
where an image or attached file sat, since those are not carried over.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://schemas.microsoft.com/office/onenote/2013/onenote}"


def _tag(el) -> str:
    return el.tag.replace(NS, "")


def html_to_text(fragment: str) -> str:
    """OneNote wraps run text as HTML: keep the words, drop the markup."""
    s = re.sub(r"<br\s*/?>", " ", fragment or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", s).strip()


def _oe_text(oe) -> str:
    parts = []
    for t in oe.findall(f"{NS}T"):
        parts.append(html_to_text(t.text or ""))
    return " ".join(p for p in parts if p).strip()


def _table(table) -> list[str]:
    rows = []
    for row in table.findall(f"{NS}Row"):
        cells = []
        for cell in row.findall(f"{NS}Cell"):
            texts = []
            for oe in cell.iter(f"{NS}OE"):
                t = _oe_text(oe)
                if t:
                    texts.append(t)
            cells.append(" / ".join(texts).replace("|", "\\|"))
        if any(cells):
            rows.append(cells)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return out


def _children(oe_children, depth: int, lines: list[str]) -> None:
    for oe in oe_children.findall(f"{NS}OE"):
        _oe(oe, depth, lines)


def _oe(oe, depth: int, lines: list[str]) -> None:
    table = oe.find(f"{NS}Table")
    if table is not None:
        lines.append("")
        lines.extend(_table(table))
        lines.append("")
    elif oe.find(f"{NS}Image") is not None:
        lines.append("  " * depth + "- _[image in the OneNote page]_")
    elif oe.find(f"{NS}InsertedFile") is not None:
        name = oe.find(f"{NS}InsertedFile").get("preferredName") or "file"
        lines.append("  " * depth + f"- _[attached file: {name}]_")
    else:
        text = _oe_text(oe)
        checked = oe.find(f"{NS}Tag")
        if text:
            box = ""
            if checked is not None:
                box = "[x] " if checked.get("completed") == "true" else "[ ] "
            lines.append("  " * depth + f"- {box}{text}")
    kids = oe.find(f"{NS}OEChildren")
    if kids is not None:
        _children(kids, depth + 1, lines)


def page_to_markdown(xml_text: str) -> dict:
    """Title, created time, and body markdown of one exported page."""
    root = ET.fromstring(xml_text.lstrip("﻿"))
    title_el = root.find(f"{NS}Title")
    title = ""
    if title_el is not None:
        title = " ".join(_oe_text(oe) for oe in title_el.iter(f"{NS}OE")).strip()
    title = title or root.get("name", "")
    lines: list[str] = []
    for outline in root.findall(f"{NS}Outline"):
        kids = outline.find(f"{NS}OEChildren")
        if kids is not None:
            _children(kids, 0, lines)
            lines.append("")
    for _ in root.findall(f"{NS}Image"):
        lines.append("- _[image in the OneNote page]_")
    for f in root.findall(f"{NS}InsertedFile"):
        lines.append(f"- _[attached file: {f.get('preferredName') or 'file'}]_")
    body = "\n".join(lines)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return {
        "title": title,
        "created": root.get("dateTime", ""),
        "modified": root.get("lastModifiedTime", ""),
        "page_id": root.get("ID", ""),
        "markdown": body,
    }


def read_page(path: Path) -> dict:
    return page_to_markdown(path.read_text(encoding="utf-8-sig"))
