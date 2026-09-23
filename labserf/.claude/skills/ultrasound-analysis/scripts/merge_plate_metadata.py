#!/usr/bin/env python3
"""
merge_plate_metadata.py — join plate results to metadata, plate-group aware.

`us_proc`'s built-in `--metadata_csv` join matches on `well` alone. That is fine
for a single plate, but a run containing several plate groups
(`plate_P_1_1`, `plate_P_1_2`, …) reuses the same 96-well IDs in each, so a
well-only join silently attaches one plate's conditions to every plate and
duplicates every row. That matters most in exactly the case you would run two
plates for: a rotated-duplicate layout, where the same well ID is a *different*
condition on the second plate.

This joins on (plate_group, well) when the metadata carries a `plate_group`
column, and falls back to a well-only join when it does not. The plate group is
recovered from `scan_name` by stripping the trailing scan position, so
`plate_P_1_2_C03` -> `plate_P_1_2`.

Run `us_proc plate_ge` **without** `--metadata_csv`, then use this.

Usage
-----
    python merge_plate_metadata.py <plate>/processed_csv/all_wells_combined.csv \
        --metadata metadata.csv --out <plate>/processed_csv/all_wells_with_metadata.csv

    # also regenerate the metric-vs-voltage figures from the merged table
    python merge_plate_metadata.py ... --figures <plate>/fig
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

SCAN_POS_RE = re.compile(r"_([A-Za-z]\d{1,2})$")


def plate_group_of(scan_name: str) -> str:
    """'plate_P_1_2_C03' -> 'plate_P_1_2'."""
    return SCAN_POS_RE.sub("", str(scan_name))


def norm_well(w) -> str:
    """'A01' -> 'A1'; leaves anything unrecognised alone."""
    if not isinstance(w, str):
        if w is None or (isinstance(w, float) and pd.isna(w)):
            return ""
        w = str(w)
    m = re.match(r"^([A-Ha-h])0*(\d{1,2})$", w.strip())
    return f"{m.group(1).upper()}{int(m.group(2))}" if m else w.strip().upper()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_csv")
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--figures", default=None,
                    help="directory to write metric-vs-voltage figures into")
    ap.add_argument("--well-map", default=None,
                    help="scan-position -> well CSV. Use when the results carry "
                         "placeholder well ids (us_proc could not apply the map).")
    ap.add_argument("--plot-by-frame", action="store_true")
    args = ap.parse_args()

    df = pd.read_csv(args.results_csv)
    meta = pd.read_csv(args.metadata)
    meta.columns = [c.strip().lower() for c in meta.columns]

    if "well" not in meta.columns:
        sys.exit(f"metadata needs a 'well' column; has {list(meta.columns)}")
    if "scan_name" not in df.columns:
        sys.exit("results CSV has no 'scan_name' column — is this a plate run?")

    # A well_id like 'A1_w1' is us_proc's placeholder for "the well map did not
    # apply" — the scan position with the ROI index tacked on. Stripping the
    # suffix would turn it into a scan position that can collide with a real well
    # ID and join to the wrong condition, so stop instead. Remap from the well
    # map when one is supplied.
    placeholder = df["well_id"].astype(str).str.match(r"^[A-Ha-h]\d{1,2}_[Ww]\d+$")
    if placeholder.any() and not args.well_map:
        n = int(placeholder.sum())
        sys.exit(
            f"{n}/{len(df)} rows have placeholder well ids like "
            f"'{df.loc[placeholder, 'well_id'].iloc[0]}' — us_proc could not apply a "
            f"well map, so these are scan positions, not wells. Joining them to "
            f"metadata would attach the wrong conditions.\n"
            f"Fix: pass --well-map <well_map.csv> here to remap them, and check the "
            f"map's keys are unpadded (A1, not A01) for future runs."
        )

    if args.well_map:
        wm = pd.read_csv(args.well_map)
        wm.columns = [c.strip().lower() for c in wm.columns]
        key = wm.columns[0]
        lut = {}
        for _, r in wm.iterrows():
            pos = norm_well(r[key])
            for i in range(1, len(wm.columns)):
                lut[(pos, f"well{i}")] = norm_well(r[f"well{i}"])
        if "scan_position" not in df.columns:
            sys.exit("--well-map given but the results have no 'scan_position' column.")
        remapped = [lut.get((norm_well(p), str(rl)))
                    for p, rl in zip(df["scan_position"], df["roi_label"])]
        miss = sum(v is None for v in remapped)
        if miss:
            sys.exit(f"--well-map does not cover {miss} rows "
                     f"(e.g. scan position {df['scan_position'].iloc[0]!r}). "
                     f"Check the map's scan-position column.")
        df["well_id"] = remapped
        print(f"  Remapped well ids from {Path(args.well_map).name} "
              f"({len(set(remapped))} distinct wells)")

    # GE well_ids can carry a _W<n> replicate suffix; strip it before matching.
    df["_well"] = (df["well_id"].astype(str)
                   .str.replace(r"_[Ww]\d+$", "", regex=True).map(norm_well))
    df["plate_group"] = df["scan_name"].map(plate_group_of)
    meta["_well"] = meta["well"].map(norm_well)

    if "plate_group" in meta.columns:
        keys = ["plate_group", "_well"]
        print(f"  Joining on (plate_group, well) — "
              f"{meta['plate_group'].nunique()} plate group(s) in metadata")
    else:
        keys = ["_well"]
        print("  metadata has no plate_group column — joining on well alone.")
        if df["plate_group"].nunique() > 1:
            print(f"  WARNING: results span {df['plate_group'].nunique()} plate groups "
                  f"({', '.join(sorted(df['plate_group'].unique()))}) but the metadata "
                  f"cannot distinguish them. Conditions may be attached to the wrong "
                  f"plate. Add a plate_group column.")

    merged = df.merge(meta.drop(columns=["well"]), on=keys, how="left",
                      validate="many_to_one")

    cond_col = next((c for c in ("condition", "sample") if c in merged.columns), None)
    unmatched = merged[merged[cond_col].isna()] if cond_col else merged.iloc[0:0]
    n_wells = merged.groupby(keys).ngroups

    print(f"  {len(df)} result rows x {len(meta)} metadata rows "
          f"-> {len(merged)} merged rows, {n_wells} distinct well(s)")
    if len(unmatched):
        miss = sorted(unmatched[keys].drop_duplicates()
                      .astype(str).agg("/".join, axis=1).unique())
        print(f"  UNMATCHED: {len(unmatched)} rows across {len(miss)} well(s): "
              f"{miss[:12]}{' …' if len(miss) > 12 else ''}")
    else:
        print("  every result row matched a metadata row")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    merged.drop(columns=["_well"]).to_csv(out, index=False)
    print(f"  {out}")

    if args.figures:
        sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "Scripts"))
        try:
            from us_proc_v5_addBURST_colormap import generate_plate_figures
        except Exception as e:
            print(f"  [figures] could not import us_proc ({e}) — skipping.")
            return
        generate_plate_figures(merged.drop(columns=["_well"]), args.figures,
                               plot_by_frame=args.plot_by_frame)


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
