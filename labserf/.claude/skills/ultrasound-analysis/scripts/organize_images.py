#!/usr/bin/env python3
"""
organize_images.py — file the saved xAM/B-mode PNGs by voltage and colorscale,
and rename them from scan position to sample/condition.

`us_proc` writes images flat into `<plate>/images/` named after the acquisition
folder (`plate_P_1_1_A01_xAM_12.0V.png`). That tells you nothing at a glance and
loses the colorscale, so two runs at different display settings overwrite or
intermix. This moves them into

    <plate>/images/V<voltage>_cmin<min>_cmax<max>/<sample_condition>_R<n>_xAM_<V>V.png

which is the layout the lab already uses. `_R<n>` disambiguates repeats of the
same condition — with a rotated duplicate plate that is the two plate copies.

Run it after `merge_plate_metadata.py`, whose merged CSV supplies the condition
for each scan position.

Usage
-----
    python organize_images.py <plate>/images \
        --merged <plate>/processed_csv/all_wells_with_metadata.csv \
        --cmin 30 --cmax 80

    # keep the originals in place
    python organize_images.py ... --cmin 30 --cmax 80 --copy

    # build the label from different columns
    python organize_images.py ... --cmin 30 --cmax 80 --label-cols sample,condition
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

# plate_P_1_1_A01_xAM_12.0V.png  /  ..._Bmode_12.0V.png  /  ..._xAM_12.0V_diff.png
NAME_RE = re.compile(
    r"^(?P<scan>.+?)_(?P<mode>xAM|Bmode)_(?P<volt>[0-9]+\.?[0-9]*)V(?P<rest>.*)\.png$",
    re.IGNORECASE)


def sanitize(text: str) -> str:
    """Match the lab's existing filenames: '/' -> '-', spaces -> '_'."""
    t = re.sub(r"\s*/\s*", "/", str(text).strip())
    t = t.replace("/", "-")
    t = re.sub(r"\s+", "_", t)
    return re.sub(r"[^0-9A-Za-z._+\-]", "", t)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images_dir")
    ap.add_argument("--merged", required=True,
                    help="all_wells_with_metadata.csv from merge_plate_metadata.py")
    ap.add_argument("--cmin", type=float, required=True,
                    help="colorscale min used for --save_images (dB)")
    ap.add_argument("--cmax", type=float, required=True)
    ap.add_argument("--label-cols", default="condition",
                    help="comma-separated metadata columns forming the label "
                         "(default: condition)")
    ap.add_argument("--copy", action="store_true",
                    help="copy instead of move (leaves the flat originals)")
    args = ap.parse_args()

    img_dir = Path(args.images_dir)
    if not img_dir.is_dir():
        sys.exit(f"Not a directory: {img_dir}")

    df = pd.read_csv(args.merged)
    if "scan_name" not in df.columns:
        sys.exit("merged CSV has no 'scan_name' column.")
    cols = [c.strip() for c in args.label_cols.split(",")]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        sys.exit(f"--label-cols not in merged CSV: {missing}\n"
                 f"available: {[c for c in df.columns if df[c].dtype == object]}")

    # One label per scan position: the distinct condition(s) its wells carry,
    # in well order, deduplicated (all three are usually the same condition).
    labels: dict[str, str] = {}
    for scan, sub in df.groupby("scan_name"):
        seen, parts = set(), []
        for _, r in sub.sort_values("roi_label").iterrows():
            v = "_".join(str(r[c]) for c in cols if pd.notna(r[c]))
            if v and v not in seen:
                seen.add(v)
                parts.append(v)
        labels[str(scan)] = sanitize("__".join(parts)) or str(scan)

    pngs = sorted(p for p in img_dir.iterdir()
                  if p.is_file() and p.suffix.lower() == ".png"
                  and not p.name.startswith("._"))
    if not pngs:
        sys.exit(f"No PNGs directly in {img_dir}")

    counters: dict[tuple, int] = defaultdict(int)
    moved, skipped = 0, []
    for p in pngs:
        m = NAME_RE.match(p.name)
        if not m:
            skipped.append(p.name)
            continue
        scan, mode, volt, rest = (m.group("scan"), m.group("mode"),
                                  m.group("volt"), m.group("rest"))
        label = labels.get(scan)
        if label is None:
            skipped.append(f"{p.name} (no metadata for {scan})")
            continue

        out_dir = img_dir / f"V{float(volt):.1f}_cmin{args.cmin:g}_cmax{args.cmax:g}"
        out_dir.mkdir(parents=True, exist_ok=True)
        key = (out_dir.name, label, mode, volt, rest)
        counters[key] += 1
        dest = out_dir / f"{label}_R{counters[key]}_{mode}_{float(volt):.1f}V{rest}.png"

        if args.copy:
            shutil.copy2(p, dest)
        else:
            shutil.move(str(p), dest)
        moved += 1

    print(f"  {moved} image(s) {'copied' if args.copy else 'moved'}")
    for d in sorted({p.parent for p in img_dir.rglob('*.png')} - {img_dir}):
        n = len(list(d.glob('*.png')))
        print(f"    {d.name}/  ({n} images)")
        for f in sorted(d.glob('*.png'))[:3]:
            print(f"      {f.name}")
        if n > 3:
            print(f"      … {n - 3} more")
    if skipped:
        print(f"  skipped {len(skipped)}: {skipped[:5]}")


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
