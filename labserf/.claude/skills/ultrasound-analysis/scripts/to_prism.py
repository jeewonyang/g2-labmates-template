#!/usr/bin/env python3
"""
to_prism.py — reshape a us_proc results CSV into GraphPad Prism import tables.

Prism wants a *wide* table: one row per X value, one column per replicate, with
replicates of the same condition placed in adjacent sub-columns. The long/tidy
CSVs that us_proc writes have to be pivoted before they can be pasted in.

Two files are written per metric:
  <out>/<metric>_prism_replicates.csv   rows = X, columns = "<group>__r1..rN"
  <out>/<metric>_prism_mean_sem.csv     rows = X, columns = "<group>__mean/__sem/__n"

Paste the replicates file into a Prism "Grouped" table (Y = replicate values in
side-by-side sub-columns); the mean/SEM file is for tables entered as computed
values, or for a quick sanity check against Prism's own summary.

Usage
-----
  python to_prism.py all_wells_with_metadata.csv --metric cnr_x_corr
  python to_prism.py results_avg.csv --metric sbr_x_corr --x frame_idx --out ./prism
  python to_prism.py merged.csv --metric am_bmode_ratio --group sample,condition
  python to_prism.py merged.csv --metric cnr_x_corr --pressure --probe GE624D
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CAL_DIR = Path(__file__).resolve().parent.parent / "calibration"

# Preference order for auto-picking the grouping columns.
GROUP_CANDIDATES = [
    ["sample", "condition"],
    ["sample", "short_condition"],
    ["short_condition"],
    ["condition"],
    ["sample"],
    ["roi_label"],
    ["well_id"],
    ["scan_name"],
]

# Preference order for the replicate identity within a group.
REPLICATE_CANDIDATES = ["well_id", "scan_name", "roi_label", "filename"]


def pick_group_cols(df: pd.DataFrame, explicit: str | None) -> list[str]:
    if explicit:
        cols = [c.strip() for c in explicit.split(",")]
        missing = [c for c in cols if c not in df.columns]
        if missing:
            sys.exit(f"--group column(s) not in CSV: {missing}\nAvailable: {list(df.columns)}")
        return cols
    for combo in GROUP_CANDIDATES:
        if all(c in df.columns for c in combo) and df[combo].notna().any(axis=None):
            return combo
    sys.exit("Could not infer grouping columns — pass --group explicitly.")


def pick_replicate_col(df: pd.DataFrame, group_cols: list[str]) -> str | None:
    for c in REPLICATE_CANDIDATES:
        if c in df.columns and c not in group_cols:
            return c
    return None


def attach_pressure(df: pd.DataFrame, probe: str, aperture: float | None,
                    depth_mm: float | None, tx_freq: float | None) -> pd.DataFrame:
    """Add a peak_positive_pressure_MPa column interpolated from the probe calibration."""
    if probe.upper().startswith("GE"):
        cal = pd.read_csv(CAL_DIR / "GE624D_pressure_calibration.csv")
        cal = cal[cal["Mode"] == "xAM"]
        if aperture is not None:
            cal = cal[cal["Aperture"] == aperture]
        if tx_freq is not None:
            cal = cal[cal["TxFrequency_MHz"] == tx_freq]
        if depth_mm is not None:
            cal = cal[cal["Location_mm"] == depth_mm]
    else:
        cal = pd.read_csv(CAL_DIR / "L22_L10_pressure_calibration.csv")
        cal = cal[(cal["Mode"] == "xAM") & (cal["probe"].str.contains("L22"))]
        if depth_mm is not None:
            cal = cal[cal["Location_mm"] == f"{depth_mm:g}mm"]

    if cal.empty:
        print("  [pressure] No matching calibration rows — skipping pressure column.")
        return df

    # If several calibration dates survive the filter, use the most recent source.
    if "source" in cal.columns and cal["source"].nunique() > 1:
        newest = sorted(cal["source"].unique())[-1]
        cal = cal[cal["source"] == newest]
        print(f"  [pressure] Multiple calibrations matched; using {newest}")

    cal = cal.sort_values("Voltage_V")
    df = df.copy()
    df["peak_positive_pressure_MPa"] = np.interp(
        df["voltage"].astype(float), cal["Voltage_V"], cal["PPP_MPa"],
        left=np.nan, right=np.nan,
    )
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="us_proc results CSV (tidy/long form)")
    ap.add_argument("--metric", default="cnr_x_corr",
                    help="value column to export (default: cnr_x_corr)")
    ap.add_argument("--x", default="voltage",
                    help="x-axis column: voltage (ramp) or frame_idx (timecourse)")
    ap.add_argument("--group", default=None,
                    help="comma-separated grouping columns (default: auto-detect)")
    ap.add_argument("--out", default=None, help="output directory (default: <csv dir>/prism)")
    ap.add_argument("--drop-post", action="store_true", default=True,
                    help="drop post-collapse rows (default: on)")
    ap.add_argument("--keep-post", dest="drop_post", action="store_false")
    ap.add_argument("--pressure", action="store_true",
                    help="also emit peak positive pressure (MPa) alongside voltage")
    ap.add_argument("--probe", default="L22-14vX", help="probe for --pressure lookup")
    ap.add_argument("--aperture", type=float, default=None, help="Xap for --pressure lookup")
    ap.add_argument("--depth", type=float, default=None, help="depth mm for --pressure lookup")
    ap.add_argument("--tx-freq", type=float, default=None, help="MHz for --pressure lookup")
    args = ap.parse_args()

    src = Path(args.csv)
    df = pd.read_csv(src)
    df.columns = [c.strip() for c in df.columns]

    if args.metric not in df.columns:
        sys.exit(f"Metric '{args.metric}' not in CSV.\nAvailable: "
                 f"{[c for c in df.columns if df[c].dtype.kind == 'f']}")
    if args.x not in df.columns:
        sys.exit(f"X column '{args.x}' not in CSV.")

    if args.drop_post and "is_post" in df.columns:
        before = len(df)
        df = df[df["is_post"] == False]  # noqa: E712 — pandas mask, not identity
        print(f"  Dropped {before - len(df)} post-collapse rows.")

    if args.pressure:
        df = attach_pressure(df, args.probe, args.aperture, args.depth, args.tx_freq)

    group_cols = pick_group_cols(df, args.group)
    rep_col = pick_replicate_col(df, group_cols)
    print(f"  Grouping by : {group_cols}")
    print(f"  Replicates  : {rep_col or '(none — rows within a group are pooled)'}")
    print(f"  X axis      : {args.x}")
    print(f"  Metric      : {args.metric}")

    df["_group"] = df[group_cols].astype(str).agg(" | ".join, axis=1)

    # --- replicate-wide table
    if rep_col:
        df["_rep"] = df.groupby(["_group", args.x])[rep_col].transform(
            lambda s: pd.factorize(s)[0] + 1
        )
    else:
        df["_rep"] = df.groupby(["_group", args.x]).cumcount() + 1

    wide = df.pivot_table(index=args.x, columns=["_group", "_rep"],
                          values=args.metric, aggfunc="mean")
    wide.columns = [f"{g}__r{r}" for g, r in wide.columns]
    wide = wide.sort_index()

    # --- mean / SEM table
    stats = (df.groupby(["_group", args.x])[args.metric]
               .agg(mean="mean", sd="std", n="count").reset_index())
    stats["sem"] = stats["sd"] / np.sqrt(stats["n"].clip(lower=1))
    ms = stats.pivot(index=args.x, columns="_group", values=["mean", "sem", "n"])
    ms.columns = [f"{g}__{stat}" for stat, g in ms.columns]
    ms = ms.sort_index()[sorted(ms.columns)]

    if args.pressure and "peak_positive_pressure_MPa" in df.columns and args.x == "voltage":
        pmap = df.groupby("voltage")["peak_positive_pressure_MPa"].first()
        wide.insert(0, "peak_positive_pressure_MPa", pmap.reindex(wide.index).values)
        ms.insert(0, "peak_positive_pressure_MPa", pmap.reindex(ms.index).values)

    out_dir = Path(args.out) if args.out else src.parent / "prism"
    out_dir.mkdir(parents=True, exist_ok=True)
    p1 = out_dir / f"{args.metric}_prism_replicates.csv"
    p2 = out_dir / f"{args.metric}_prism_mean_sem.csv"
    wide.to_csv(p1)
    ms.to_csv(p2)

    print(f"\n  {p1}   ({wide.shape[0]} x-values, {wide.shape[1]} columns)")
    print(f"  {p2}   ({len(group_cols)} grouping col(s), "
          f"{stats['_group'].nunique()} groups)")


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
