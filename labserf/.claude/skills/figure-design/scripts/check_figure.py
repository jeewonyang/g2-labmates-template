"""Audit a figure against the mechanical Shapiro Lab rules.

Checks what a machine can check — font family, font size, stroke width, page
size, color palette — from a vector file (PDF or SVG). The judgement rules
("the reader can tell 99% without the legend", "visually appealing") are for
the figure-designer agent, which looks at the rendered PNG.

    python check_figure.py fig.pdf [fig2.svg ...] [--json]

Exit status is 1 if any figure has a violation, so it can gate a pipeline.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
import zlib

MM = 25.4 / 72  # PDF/SVG points -> millimetres

REQUIRED_FONT_SIZE = 8.0
REQUIRED_LINE_WIDTH = 0.5
ALLOWED_FONTS = ("arial", "helvetica", "liberationsans", "arialmt", "helveticaneue")
SIZE_TOL = 0.15   # pt
WIDTH_TOL = 0.05  # pt

PALETTE = {
    "#000000", "#4D4D4D", "#646464", "#808080", "#969696", "#ADADAD",
    "#C8C8C8", "#DDDDDD", "#EBEBEB", "#FFFFFF",
    "#F28A00", "#FF9A00", "#5CB2C4", "#A2D5E0",
    "#3B6FB6", "#3E9B52", "#9E2B25",
    # figstyle.OVERLAY: outlines drawn on image data, where orange disappears
    "#FF00FF", "#00FFFF", "#00FF00",
}


# ------------------------------------------------------------------- PDF side

#: Stream dictionaries that mark data rather than drawing: embedded font
#: programs (TrueType embedding puts the whole Arial binary in the file) and
#: raster images. Their bytes tokenize as random PDF operators — "m", "S" —
#: and would read as phantom strokes.
_NON_DRAWING = (b"/Length1", b"/Length2", b"/FontFile", b"/Subtype /Image",
                b"/Subtype/Image", b"/Subtype /Type1C", b"/Subtype /CIDFontType0C",
                b"/Subtype /OpenType")


def _pdf_streams(raw: bytes) -> list[tuple[bool, bytes]]:
    """Decompressed drawing streams (page content and form XObjects).

    Good enough for matplotlib's simple PDFs. Markers are drawn as form
    XObjects, so those are kept; font programs and images are skipped.
    Returns (is_form_xobject, data) pairs.
    """
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        head = raw[max(0, m.start() - 600):m.start()]
        head = head[head.rfind(b" obj") + 1:] if b" obj" in head else head
        if any(k in head for k in _NON_DRAWING):
            continue
        is_form = b"/Form" in head
        blob = m.group(1)
        try:
            out.append((is_form, zlib.decompress(blob)))
        except zlib.error:
            out.append((is_form, blob))
    return out


def _pdf_page_size_mm(raw: bytes) -> tuple[float, float] | None:
    m = re.search(rb"/MediaBox\s*\[\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)", raw)
    if not m:
        return None
    x0, y0, x1, y1 = (float(v) for v in m.groups())
    return (x1 - x0) * MM, (y1 - y0) * MM


_PATH_OPS = {b"m", b"l", b"c", b"v", b"y", b"re", b"h"}
_STROKE_OPS = {b"S", b"s", b"B", b"B*", b"b", b"b*"}
_END_OPS = {b"f", b"F", b"f*", b"n"}   # paint-without-stroke or discard


def _stroked_widths(stream: bytes, inherited: bool = False) -> set[float]:
    """Line widths that are in force when a non-empty path is actually stroked.

    Two kinds of `w` paint nothing and must not count: the reset to 1 pt that
    matplotlib writes before every text block, and the 0.01 pt hairline of the
    colorbar's hidden background patch, which is set and then applied to an
    *empty* path. Walking the operators and requiring a path-construction op
    before the stroke separates both from real lines.

    A form XObject (matplotlib draws every marker as one) *inherits* the line
    width of whatever invokes it, so its starting width is unknown here, not
    the PDF default of 1 pt; strokes before its own `w` are not counted.
    """
    used: set[float] = set()
    width: float | None = None if inherited else 1.0   # PDF default is 1 pt
    stack: list[float | None] = []     # q/Q save and restore the width
    has_path = False
    toks = stream.split()
    for i, tok in enumerate(toks):
        if tok == b"w" and i > 0:
            try:
                width = round(float(toks[i - 1]), 3)
            except ValueError:
                pass
        elif tok == b"q":
            stack.append(width)
        elif tok == b"Q":
            width = stack.pop() if stack else width
        elif tok in _PATH_OPS:
            has_path = True
        elif tok in _STROKE_OPS:
            if has_path and width is not None:
                used.add(width)
            has_path = False
        elif tok in _END_OPS:
            has_path = False
    return used


def inspect_pdf(path: str) -> dict:
    raw = open(path, "rb").read()
    fonts, sizes, widths, colors = set(), set(), set(), set()

    for name in re.findall(rb"/BaseFont\s*/([#\w+.\-]+)", raw):
        n = name.decode("latin-1")
        # Subset fonts are prefixed "ABCDEF+".
        fonts.add(n.split("+")[-1])

    for is_form, stream in _pdf_streams(raw):
        for m in re.finditer(rb"/(F\d+|[A-Za-z0-9#.\-]+)\s+([\d.]+)\s+Tf", stream):
            sizes.add(round(float(m.group(2)), 3))
        widths |= _stroked_widths(stream, inherited=is_form)
        for m in re.finditer(rb"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(?:RG|rg)(?:\s|$)", stream):
            r, g, b = (float(v) for v in m.groups())
            colors.add("#%02X%02X%02X" % tuple(round(c * 255) for c in (r, g, b)))
        for m in re.finditer(rb"([\d.]+)\s+(?:G|g)(?:\s|$)", stream):
            v = round(float(m.group(1)) * 255)
            colors.add("#%02X%02X%02X" % (v, v, v))

    return {
        "fonts": sorted(fonts),
        "font_sizes": sorted(sizes),
        "line_widths": sorted(w for w in widths if w > 0),
        "colors": sorted(colors),
        "size_mm": _pdf_page_size_mm(raw),
    }


# ------------------------------------------------------------------- SVG side

def _svg_len_mm(v: str | None) -> float | None:
    if not v:
        return None
    m = re.match(r"([\d.]+)\s*(pt|px|mm|in)?", v)
    if not m:
        return None
    x, unit = float(m.group(1)), (m.group(2) or "px")
    return {"pt": MM, "px": MM, "mm": 1.0, "in": 25.4}[unit] * x


def inspect_svg(path: str) -> dict:
    root = ET.parse(path).getroot()
    fonts, sizes, widths, colors = set(), set(), set(), set()

    def props(el) -> dict[str, str]:
        d = {k: v for k, v in el.attrib.items() if not k.startswith("{")}
        for decl in (el.get("style") or "").split(";"):
            if ":" in decl:
                k, v = decl.split(":", 1)
                d[k.strip()] = v.strip()
        return d

    for el in root.iter():
        p = props(el)
        if "font-family" in p:
            # A CSS font stack is a preference list; only the first entry is
            # what actually renders. matplotlib writes the whole
            # `font.sans-serif` fallback chain, and the later entries are
            # never used.
            first = p["font-family"].split(",")[0].strip().strip("'\"")
            if first:
                fonts.add(first)
        if "font-size" in p:
            s = _svg_len_mm(p["font-size"])
            if s:
                sizes.add(round(s / MM, 3))
        if "stroke-width" in p:
            w = _svg_len_mm(p["stroke-width"])
            if w:
                widths.add(round(w / MM, 3))
        for key in ("stroke", "fill"):
            v = (p.get(key) or "").strip()
            if v.startswith("#") and len(v) == 7:
                colors.add(v.upper())

    w = _svg_len_mm(root.get("width"))
    h = _svg_len_mm(root.get("height"))
    return {
        "fonts": sorted(fonts),
        "font_sizes": sorted(sizes),
        "line_widths": sorted(x for x in widths if x > 0),
        "colors": sorted(colors),
        "size_mm": (w, h) if w and h else None,
    }


# -------------------------------------------------------------------- verdict

def check(path: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        found = inspect_pdf(path)
    elif ext == ".svg":
        found = inspect_svg(path)
    else:
        return {
            "file": path,
            "violations": [
                f"{ext or 'this file'} cannot be audited — font size and line width are "
                "not recoverable from a raster image. Save the figure as PDF or SVG too."
            ],
            "notes": [],
            "found": {},
        }

    violations, notes = [], []

    bad_fonts = [f for f in found["fonts"]
                 if f.lower().replace(" ", "").replace("-", "") not in ALLOWED_FONTS]
    if bad_fonts:
        violations.append(f"non-Arial font(s): {', '.join(bad_fonts)} (rule: 8 pt Arial for everything)")
    if any("bold" in f.lower() for f in found["fonts"]):
        violations.append("bold font detected (rule: Arial, not bold)")

    bad_sizes = [s for s in found["font_sizes"] if abs(s - REQUIRED_FONT_SIZE) > SIZE_TOL]
    if bad_sizes:
        violations.append(
            f"font size(s) {', '.join(f'{s:g}' for s in bad_sizes)} pt "
            f"(rule: everything at {REQUIRED_FONT_SIZE:g} pt)")

    bad_widths = [w for w in found["line_widths"] if abs(w - REQUIRED_LINE_WIDTH) > WIDTH_TOL]
    if bad_widths:
        violations.append(
            f"line width(s) {', '.join(f'{w:g}' for w in bad_widths)} pt "
            f"(rule: {REQUIRED_LINE_WIDTH:g} pt for everything)")

    off = [c for c in found["colors"] if c not in PALETTE]
    if off:
        notes.append(
            f"{len(off)} color(s) outside the lab palette: {', '.join(off[:8])}"
            f"{' ...' if len(off) > 8 else ''}. Fine for density maps and "
            "channel-identity colors; check it is deliberate.")

    if found.get("size_mm"):
        w, h = found["size_mm"]
        notes.append(f"canvas {w:.1f} x {h:.1f} mm "
                     f"({'fits' if w <= 180.5 else 'WIDER THAN'} a 180 mm double column)")
        if w > 180.5:
            violations.append(f"figure is {w:.1f} mm wide, past the 180 mm double-column limit")

    return {"file": path, "violations": violations, "notes": notes, "found": found}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = [check(f) for f in args.files]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            status = "FAIL" if r["violations"] else "pass"
            print(f"[{status}] {r['file']}")
            for v in r["violations"]:
                print(f"    ! {v}")
            for n in r["notes"]:
                print(f"    - {n}")
            f = r["found"]
            if f:
                print(f"      fonts={f['fonts']} sizes={f['font_sizes']} widths={f['line_widths']}")
    return 1 if any(r["violations"] for r in results) else 0


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    sys.exit(main())
