#!/usr/bin/env python3
"""
make_well_map.py — build the GE scan-position -> physical-well map.

The GE probe images three wells at once, so an acquisition folder named
`plate_P_1_1_A01` is a **scan position**, not a well. `us_proc plate_ge` needs a
CSV telling it which three 96-well positions each scan covers:

    acoustic_plate_reader_well,well1,well2,well3
    A01,B1,B2,B3
    A02,B4,B5,B6
    ...

The scan-position letters are a sequential index over the rows that were actually
scanned, which is **not** the same as the plate row when only part of the plate is
imaged. A 6-row scan of the middle of a plate (`--first-row B`) has scan row A
sitting on plate row B, scan row B on plate row C, and so on. Getting this offset
wrong silently attaches every result to the wrong condition, so it is an explicit
argument with no default guessing.

Usage
-----
    # 6 scan rows starting at plate row B, 4 positions per row (3 wells each)
    python make_well_map.py --out well_map.csv --rows 6 --cols 4 --first-row B

    # a full-plate 8-row scan
    python make_well_map.py --out well_map.csv --rows 8 --cols 4 --first-row A

    # right-to-left column order (serpentine or reversed stage travel)
    python make_well_map.py --out well_map.csv --rows 6 --cols 4 --first-row B --reverse-cols
"""

from __future__ import annotations

import argparse
import csv
import string
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rows", type=int, required=True,
                    help="number of scan rows (P.xLines)")
    ap.add_argument("--cols", type=int, required=True,
                    help="scan positions per row (P.zLines); each covers 3 wells")
    ap.add_argument("--first-row", required=True,
                    help="plate row the FIRST scan row sits on (A-H). "
                         "For a middle-rows-only scan of B-G, pass B.")
    ap.add_argument("--wells-per-position", type=int, default=3,
                    help="3 for the GE probe, 1 for L22 (default 3)")
    ap.add_argument("--reverse-cols", action="store_true",
                    help="scan columns run right-to-left")
    ap.add_argument("--pad", type=int, default=1,
                    help="zero-padding of the scan position number. Default 1 (A1). "
                         "us_proc normalises the folder's scan id by stripping "
                         "leading zeros before looking it up, so a map keyed A01 "
                         "never matches and every well silently falls back to an "
                         "'A1_w1' placeholder. Only change this if you know the "
                         "consumer expects padding.")
    args = ap.parse_args()

    first = args.first_row.strip().upper()
    if first not in string.ascii_uppercase[:8]:
        sys.exit("--first-row must be a plate row letter A-H.")
    r0 = string.ascii_uppercase.index(first)
    if r0 + args.rows > 8:
        sys.exit(f"{args.rows} scan rows starting at {first} runs past plate row H.")

    n = args.wells_per_position
    if args.cols * n > 12:
        sys.exit(f"{args.cols} positions x {n} wells = {args.cols * n} columns > 12.")

    rows = []
    for i in range(args.rows):
        scan_row = string.ascii_uppercase[i]              # sequential scan index
        plate_row = string.ascii_uppercase[r0 + i]        # physical plate row
        for j in range(args.cols):
            col_block = (args.cols - 1 - j) if args.reverse_cols else j
            wells = [f"{plate_row}{col_block * n + k + 1}" for k in range(n)]
            rows.append([f"{scan_row}{j + 1:0{args.pad}d}"] + wells)

    header = ["acoustic_plate_reader_well"] + [f"well{k + 1}" for k in range(n)]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)

    print(f"  {len(rows)} scan positions x {n} wells = {len(rows) * n} wells")
    print(f"  scan rows A-{string.ascii_uppercase[args.rows - 1]}  ->  "
          f"plate rows {first}-{string.ascii_uppercase[r0 + args.rows - 1]}")
    for r in rows[:3]:
        print(f"    {r[0]} -> {', '.join(r[1:])}")
    print(f"    ...")
    print(f"    {rows[-1][0]} -> {', '.join(rows[-1][1:])}")
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
