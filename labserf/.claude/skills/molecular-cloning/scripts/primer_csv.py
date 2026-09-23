"""Write primer tables in the lab's Primer_All format.

The first five columns are exactly those of
Sequences/Sequence_JWY/Primer_All(Sheet1).csv — Date, name, sequence, ta, Note —
so a block can be pasted straight into that sheet. The lab's convention of
putting "63C; 5816 bp (template)" on the forward row only, and leaving the
reverse row's ta blank, is reproduced, because that is how the sheet reads.

Diagnostic columns follow to the right: they are ignored by a paste into the
five-column sheet but carry the per-primer numbers worth checking before
ordering.
"""

from __future__ import annotations

import csv
import datetime
import os

LAB_FIELDS = ["Date", "name", "sequence", "ta", "Note"]
DIAG_FIELDS = ["tm_C", "length_nt", "gc_pct", "template", "template_len_bp",
               "product_bp", "role", "warnings"]


def _ta_cell(pair) -> str:
    """The `ta` cell: annealing temperature and the PCR **product** length.

    The number beside Ta is the amplicon, not the template, because that is
    what sets the cycling: 30 s per kb of product for Q5, and the >10 kb
    threshold where a long-range protocol becomes necessary. The template's own
    length is still carried, in the `template_len_bp` diagnostic column.

    Primer_All is inconsistent on this — vector primers there were written with
    the template length, insert primers with the product — so a block pasted
    from here will read as the amplicon throughout.
    """
    bits = "%.0fC; %d bp" % (pair.ta, pair.product_len)
    if pair.template_name:
        bits += " (%s)" % pair.template_name
    return bits


def rows_for_pair(pair, date: str = "", note: str = "") -> list:
    """Two CSV rows for one primer pair, lab-style."""
    out = []
    for i, p in enumerate((pair.forward, pair.reverse)):
        out.append({
            "Date": date if i == 0 else "",
            "name": p.name,
            "sequence": p.sequence,
            "ta": _ta_cell(pair) if i == 0 else "",
            "Note": (note or pair.description) if i == 0 else "",
            "tm_C": "%.1f" % p.tm,
            "length_nt": p.length,
            "gc_pct": "%.0f" % p.gc,
            "template": p.template_name,
            "template_len_bp": p.template_len,
            "product_bp": pair.product_len if i == 0 else "",
            "role": p.role,
            "warnings": "; ".join(p.warnings),
        })
    return out


def write(pairs, path: str, date: str | None = None, notes=None,
          blank_between: bool = True) -> str:
    """Write one or more PrimerPairs to `path`.

    `pairs` may be a single pair, a list of pairs, or a list of
    (pair, note) tuples.
    """
    if not isinstance(pairs, (list, tuple)):
        pairs = [pairs]
    # "%-m/%-d" is not portable (Windows raises); build Primer_All's M/D/YYYY by hand.
    if date is None:
        today = datetime.date.today()
        date = f"{today.month}/{today.day}/{today.year}"

    rows = []
    for i, item in enumerate(pairs):
        pair, note = item if isinstance(item, tuple) else (item, "")
        if notes and i < len(notes):
            note = notes[i]
        rows.extend(rows_for_pair(pair, date if i == 0 else "", note))
        if blank_between and i < len(pairs) - 1:
            rows.append({k: "" for k in LAB_FIELDS + DIAG_FIELDS})

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LAB_FIELDS + DIAG_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def summarise(pairs) -> str:
    """A short text report of a design, for printing to the user."""
    if not isinstance(pairs, (list, tuple)):
        pairs = [pairs]
    lines = []
    for item in pairs:
        pair = item[0] if isinstance(item, tuple) else item
        lines.append(pair.description)
        lines.append("  Ta %.0f C   product %d bp   template %s (%d bp)"
                     % (pair.ta, pair.product_len, pair.template_name or "?",
                        pair.template_len))
        for p in (pair.forward, pair.reverse):
            lines.append("  %-28s %s" % (p.name, p.sequence))
            lines.append("  %-28s %d nt, Tm %.1f C, GC %.0f%%"
                         % ("", p.length, p.tm, p.gc))
        for w in pair.warnings():
            lines.append("  ! %s" % w)
        lines.append("")
    return "\n".join(lines)
