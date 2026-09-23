#!/usr/bin/env python3
"""
plate_map_to_metadata.py — turn a human-written grid plate map into the tidy
metadata CSV the processing pipeline joins against.

Plate maps get written as a grid because that is how a plate looks on the bench:

    Plate 1  (Dox ug/mL, 4-OHT nM)
    Row,1,2,3,4,...,12
    A,MEDIA,MEDIA,MEDIA,PBS,...
    B,Dox 0.0 / 4-OHT 0,...
    ...
    <blank line>
    Plate 2 = Plate 1 rotated 180 deg
    Row,1,2,...
    ...

`us_proc` wants one row per well (`well,sample,condition,...`). This converts
between them, keeps every plate block in the file, and pulls numeric dose columns
out of the free text when it recognises a `name value` pattern so figures can
sort and colour by dose instead of by string.

Usage
-----
    python plate_map_to_metadata.py plate_map_grid.csv --out metadata.csv

    # name the acquisition folders each grid block corresponds to, in order
    python plate_map_to_metadata.py plate_map_grid.csv --out metadata.csv \
        --plate-groups plate_P_1_1,plate_P_1_2

    # restrict to the rows actually imaged (a 6-row scan of an 8-row plate)
    python plate_map_to_metadata.py plate_map_grid.csv --out metadata.csv --rows A-F

Output columns
--------------
    plate_group   acquisition folder this block maps to (if --plate-groups given)
    plate_block   the block's title line, verbatim
    well          A1 … H12, leading zeros stripped
    sample        the raw cell text
    condition     the raw cell text (pipelines group on sample+condition)
    <dose cols>   one numeric column per recognised `name value` token
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROW_LETTERS = "ABCDEFGH"
# "Dox 0.1", "4-OHT 30", "IPTG 1e-3" -> (name, value)
DOSE_RE = re.compile(r"([A-Za-z][\w\-]*)\s+([0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)")


def slug(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", name.lower()).strip("_")


def parse_blocks(path: Path) -> list[dict]:
    """Split the file into {title, header, rows} blocks keyed off the 'Row' header."""
    with path.open(newline="", encoding="utf-8-sig") as fh:
        raw = [r for r in csv.reader(fh)]

    blocks, title = [], ""
    i = 0
    while i < len(raw):
        row = raw[i]
        cells = [c.strip() for c in row]
        nonempty = [c for c in cells if c]

        if not nonempty:
            i += 1
            continue

        # A header row starts the grid; whatever non-empty line preceded it is the title.
        if cells and cells[0].lower() in ("row", "rows", ""):
            if cells[0].lower() in ("row", "rows"):
                cols = [c for c in cells[1:] if c]
                data = {}
                i += 1
                while i < len(raw):
                    r = [c.strip() for c in raw[i]]
                    if not r or not r[0] or r[0].upper() not in ROW_LETTERS:
                        break
                    data[r[0].upper()] = r[1:]
                    i += 1
                blocks.append({"title": title, "cols": cols, "data": data})
                title = ""
                continue

        if len(nonempty) == 1:          # a lone cell on its own line is a block title
            title = nonempty[0]
        i += 1

    return blocks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("grid_csv")
    ap.add_argument("--out", required=True)
    ap.add_argument("--plate-groups", default=None,
                    help="comma-separated acquisition folder names, one per grid "
                         "block, in file order (e.g. plate_P_1_1,plate_P_1_2)")
    ap.add_argument("--rows", default=None,
                    help="restrict to these plate rows, e.g. 'A-F' or 'B,C,D'")
    ap.add_argument("--drop-empty", action="store_true", default=True,
                    help="skip wells whose cell is blank (default on)")
    args = ap.parse_args()

    blocks = parse_blocks(Path(args.grid_csv))
    if not blocks:
        sys.exit(f"No 'Row,1,2,...' grid blocks found in {args.grid_csv}")

    groups = args.plate_groups.split(",") if args.plate_groups else []
    if groups and len(groups) != len(blocks):
        sys.exit(f"{len(blocks)} grid block(s) in the file but "
                 f"{len(groups)} --plate-groups given.")

    keep = None
    if args.rows:
        if "-" in args.rows and "," not in args.rows:
            a, b = args.rows.split("-")
            keep = set(ROW_LETTERS[ROW_LETTERS.index(a.strip().upper()):
                                   ROW_LETTERS.index(b.strip().upper()) + 1])
        else:
            keep = {r.strip().upper() for r in args.rows.split(",")}

    records, dose_cols = [], []
    for bi, blk in enumerate(blocks):
        for rl, cells in blk["data"].items():
            if keep and rl not in keep:
                continue
            for ci, col in enumerate(blk["cols"]):
                text = cells[ci].strip() if ci < len(cells) else ""
                if args.drop_empty and not text:
                    continue
                rec = {
                    "plate_group": groups[bi] if groups else f"block{bi + 1}",
                    "plate_block": blk["title"],
                    "well": f"{rl}{int(col)}",
                    "sample": text,
                    "condition": text,
                }
                for name, val in DOSE_RE.findall(text):
                    c = slug(name)
                    rec[c] = float(val)
                    if c not in dose_cols:
                        dose_cols.append(c)
                records.append(rec)

    if not records:
        sys.exit("No wells parsed — check --rows and the grid layout.")

    cols = ["plate_group", "plate_block", "well", "sample", "condition"] + dose_cols
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow(r)

    print(f"  {len(blocks)} grid block(s) -> {len(records)} wells")
    for bi, blk in enumerate(blocks):
        n = sum(1 for r in records
                if r["plate_group"] == (groups[bi] if groups else f"block{bi + 1}"))
        print(f"    {(groups[bi] if groups else 'block%d' % (bi + 1)):<14} "
              f"{n:>3} wells   {blk['title']}")
    if dose_cols:
        print(f"  numeric dose columns: {', '.join(dose_cols)}")
    print(f"  {out}")


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
