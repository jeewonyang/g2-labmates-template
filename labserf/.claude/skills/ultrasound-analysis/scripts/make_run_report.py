"""make_run_report.py — the standard per-run AI_analysis for one acquisition folder.

LabSerf's default is that **every acquisition folder carries its own analysis**,
so this writes into `<run>/AI_analysis/` and reads nothing outside `<run>` except
the probe calibration tables shipped with the skill.

What it produces (each figure as .png plus a .pdf beside it)
----------------
    <run>/AI_analysis/stats.json          every number the report quotes
    <run>/AI_analysis/dose_response.png   signal vs pressure, one line per group
    <run>/AI_analysis/collapse.png        peak signal and collapse threshold
    <run>/AI_analysis/qc.png              plate-rotation agreement (if 2 plates)
    <run>/AI_analysis/assets/strip.png    representative well image per group
    <run>/AI_analysis/RESULTS.md          scaffold with QC and tables filled in

The narrative in RESULTS.md is a scaffold, not a conclusion: it states what was
measured and leaves the interpretation section for the analyst (or for a
run-specific script in the same folder) to write.

Usage
-----
    python make_run_report.py "<run folder>"
    python make_run_report.py "<run folder>" --group-by ppv_variant --volt 12
    python make_run_report.py "<run folder>" --group-by dox --split-by oht
"""
from __future__ import annotations

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from scipy import stats as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report_lib import DOSE_COLORS, Run, fs  # noqa: E402

# Lab figure rules (figure-design skill): 8 pt Arial, 0.5 pt lines, greys +
# one orange. Every figure is written as PDF + PNG so it can be audited.
fs.use()
CAND_GROUPS = ["condition", "short_condition", "sample", "ppv_variant",
               "dox", "oht", "well_id"]


def pick_group(d, wanted=None):
    if wanted:
        if wanted not in d.columns:
            raise SystemExit(f"--group-by {wanted!r} not in {list(d.columns)}")
        return wanted
    for c in CAND_GROUPS:
        if c in d.columns and 1 < d[c].nunique() <= 40:
            return c
    raise SystemExit("no usable grouping column; pass --group-by")


def curves(ax, r, d, gcol, colors, metric="sbr_x", errorbars=True):
    keys = sorted(d[gcol].dropna().unique(), key=lambda v: (str(type(v)), v))
    for i, k in enumerate(keys):
        g = d[d[gcol] == k].groupby("voltage")[metric]
        m, e = g.mean(), g.sem()
        p = r.mpa(m.index)
        col = colors[i % len(colors)]
        if errorbars:
            ax.errorbar(p, m.values, yerr=e.values, color=col, lw=0.5, marker="o",
                        ms=2.5, capsize=1.5, capthick=0.5, elinewidth=0.5,
                        label=str(k))
        else:
            ax.plot(p, m.values, color=col, lw=0.5, label=str(k))
        j = int(np.argmax(m.values))
        if j < len(m) - 1:                      # turned over inside the ramp
            ax.plot(p[j], m.values[j], marker="v", ms=4, color=col,
                    mec=fs.INK, mew=0.5)
    ax.set_xlabel("Peak positive pressure (MPa)")
    ax.set_ylabel({"sbr_x": "xAM SBR (dB)", "sbr_b": "B-mode SBR (dB)",
                   "am_bmode_ratio": "xAM / B-mode"}.get(metric, metric))
    ax.legend(frameon=False, fontsize=8, title=gcol, title_fontsize=8)
    return keys


def small_multiples(r, d, gcol, keys, metric, title, stem):
    """One panel per group: that group in orange, every other group in pale grey.

    A single panel stops working past ~4 groups — no palette separates a dozen
    unordered conditions, and the legend ends up covering the data. Small
    multiples keep the lab rule of one orange per panel and let every curve be
    read against the whole run.
    """
    import textwrap
    ncols = min(4, len(keys))
    nrows = int(np.ceil(len(keys) / ncols))
    fig, axes = fs.grid(nrows, ncols, fs.DOUBLE_COLUMN - 8, 38 * nrows + 12,
                        sharex=True, sharey=True, squeeze=False)
    flat = axes.ravel()
    means = {}
    for k in keys:
        g = d[d[gcol] == k].groupby("voltage")[metric]
        means[k] = (r.mpa(g.mean().index), g.mean().values, g.sem().values)
    for ax, k in zip(flat, keys):
        for other, (p, m, _) in means.items():
            if other != k:
                ax.plot(p, m, color=fs.GREY_PALE, lw=0.5, zorder=1)
        p, m, e = means[k]
        ax.errorbar(p, m, yerr=e, color=fs.ACCENT, lw=0.5, marker="o", ms=2,
                    capsize=1, capthick=0.5, elinewidth=0.5, zorder=3)
        j = int(np.argmax(m))
        if j < len(m) - 1:                      # turned over inside the ramp
            ax.plot(p[j], m[j], marker="v", ms=4, color=fs.INK, zorder=4)
        ax.set_title(textwrap.fill(str(k).replace("_", " "), 24), fontsize=8)
    for ax in flat[len(keys):]:
        ax.axis("off")
    ylab = {"sbr_x": "xAM SBR (dB)", "sbr_b": "B-mode SBR (dB)",
            "am_bmode_ratio": "xAM / B-mode"}.get(metric, metric)
    for i, ax in enumerate(flat[:len(keys)]):
        if i % ncols == 0:
            ax.set_ylabel(ylab)
        if i + ncols >= len(keys):
            ax.set_xlabel("Peak positive pressure (MPa)")
            ax.xaxis.set_tick_params(labelbottom=True)
    fig.suptitle(f"{title}\norange: the panel's {gcol}; grey: all other groups; "
                 "\u25bc: signal turns over inside the ramp; mean \u00b1 s.e.m.",
                 fontsize=8)
    fig.tight_layout()
    fs.save(fig, stem)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--group-by", default=None,
                    help="condition column for the curves (default: auto-detect)")
    ap.add_argument("--volt", type=float, default=12.0,
                    help="reference voltage for the summary table (default 12)")
    ap.add_argument("--metric", default="sbr_x")
    ap.add_argument("--plate-sub", default="plate")
    ap.add_argument("--probe", default="GE624D")
    ap.add_argument("--no-strip", action="store_true",
                    help="skip the representative-image strip (slow on big runs)")
    a = ap.parse_args()

    calib = {} if a.probe.upper().startswith("GE") else {
        "probe": a.probe, "mode": None, "aperture": None,
        "freq_mhz": None, "location_mm": "5mm"}
    r = Run(a.run, plate_sub=a.plate_sub, calib=calib)
    r.mkout()
    d = r.pre()
    gcol = pick_group(d, a.group_by)
    keys = sorted(d[gcol].dropna().unique(), key=lambda v: (str(type(v)), v))
    # Grey -> orange ramp in sorted order, one colour per group, reused in every
    # panel so a group keeps its colour across the report (lab rule 4).
    colors = DOSE_COLORS if len(keys) == 4 else fs.ramp(len(keys))

    S = {"run": r.name, "group_by": gcol, "metric": a.metric,
         "ref_voltage": a.volt, "ref_pressure_MPa": round(r.pressure(a.volt), 3),
         "n_wells": int(d.groupby(["scan_name", "roi_label"]).ngroups),
         "voltages": [float(v) for v in sorted(d.voltage.unique())]}

    # ---- summary table + collapse threshold -----------------------------
    ref = d[np.isclose(d.voltage, a.volt)]
    well = ["scan_name", "roi_label"]
    rows = {}
    for k in keys:
        g = d[d[gcol] == k]
        gr = ref[ref[gcol] == k]
        pv = g.loc[g.groupby(well)[a.metric].idxmax()]
        m = g.groupby("voltage")[a.metric].mean()
        turned = int(np.argmax(m.values)) < len(m) - 1
        rows[str(k)] = {
            "n": int(gr.groupby(well).ngroups),
            "ref_mean": round(float(gr[a.metric].mean()), 2),
            "ref_sem": round(float(gr[a.metric].sem()), 2),
            "peak_mean": round(float(m.max()), 2),
            "peak_MPa": round(float(r.pressure(m.idxmax())), 2),
            "median_threshold_MPa": round(float(r.pressure(pv.voltage.median())), 2),
            "turned_over": bool(turned),
        }
    S["groups"] = rows
    S["ramp_truncated"] = not any(v["turned_over"] for v in rows.values())

    # ---- plate-rotation QC ----------------------------------------------
    groups = r.plate_groups()
    if len(groups) == 2 and "condition" in ref.columns:
        pg = ref.scan_name.map(lambda s: groups[0] if groups[0] in s else groups[1])
        w = ref.groupby(["condition", pg]).sbr_x.mean().unstack().dropna()
        if len(w) >= 3:
            S["plate_r"] = round(float(np.corrcoef(w.iloc[:, 0], w.iloc[:, 1])[0, 1]), 3)
            S["plate_mad"] = round(float(np.abs(w.iloc[:, 0] - w.iloc[:, 1]).mean()), 2)
            fig, ax = fs.figure(60, 60)
            ax.scatter(w.iloc[:, 0], w.iloc[:, 1], s=10, facecolors="white",
                       edgecolors=fs.INK, linewidths=0.5, zorder=3)
            lim = [min(w.min()) - .5, max(w.max()) + .5]
            ax.plot(lim, lim, ls=":", color=fs.GREY_DARK, lw=0.5)
            ax.set_xlim(lim); ax.set_ylim(lim)
            ax.set_xlabel(f"{groups[0]} (dB)"); ax.set_ylabel(f"{groups[1]} (dB)")
            ax.set_title(f"Position control\nr = {S['plate_r']}, "
                         f"MAD = {S['plate_mad']} dB", fontsize=8)
            fig.tight_layout(); fs.save(fig, f"{r.out}/qc")

    # ---- ROI geometry (what the numbers were measured over) --------------
    import glob as _g
    import json as _j
    tops, bots, wid = [], [], []
    for f in _g.glob(f"{r.roi_dir}/*_rois.json"):
        if os.path.basename(f).startswith("shared"):
            continue
        j = _j.load(open(f, encoding="utf-8"))
        for k in j:
            if k.startswith("well"):
                tops.append(j[k]["z_min"]); bots.append(j[k]["z_max"])
                wid.append(j[k]["x_max"] - j[k]["x_min"])
    if tops:
        S["roi"] = {"n": len(tops),
                    "top_mm": [round(min(tops), 2), round(float(np.median(tops)), 2),
                               round(max(tops), 2)],
                    "bottom_mm": sorted({round(b, 2) for b in bots})[:4],
                    "width_mm": round(float(np.median(wid)), 2)}

    # ---- figures ---------------------------------------------------------
    if len(keys) <= 4:
        fig, ax = fs.figure(88, 66)
        curves(ax, r, d, gcol, colors, a.metric)
        ax.set_title(f"{r.name}\n{a.metric} vs pressure", fontsize=8)
        fig.tight_layout(); fs.save(fig, f"{r.out}/dose_response")
    else:
        small_multiples(r, d, gcol, keys, a.metric,
                        f"{r.name} \u2014 {a.metric} vs pressure",
                        f"{r.out}/dose_response")

    # A little under the double column: tight bbox adds the rotated labels'
    # overhang back on, and the checker holds the 180 mm limit strictly.
    fig, axes = fs.grid(1, 2, fs.DOUBLE_COLUMN - 8, 70)
    lab = [str(k) for k in keys]
    # Ramp colours only while they are also the curve colours (<= 4 groups);
    # past that the groups are unordered categories and get one grey.
    bar_colors = ([colors[i % len(colors)] for i in range(len(lab))]
                  if len(keys) <= 4 else [fs.GREY] * len(lab))
    axes[0].bar(lab, [rows[k]["peak_mean"] for k in lab], 0.65,
                color=bar_colors, edgecolor=fs.INK, lw=0.5)
    axes[0].set_ylabel(f"Peak {a.metric} (dB)"); axes[0].set_title("Peak signal")
    axes[1].bar(lab, [rows[k]["median_threshold_MPa"] for k in lab], 0.65,
                color=bar_colors, edgecolor=fs.INK, lw=0.5)
    axes[1].set_ylabel("Median collapse threshold (MPa)")
    axes[1].set_title("Collapse threshold (top of ramp = not reached)")
    for ax in axes:
        ax.tick_params(axis="x", labelrotation=45)
        for t in ax.get_xticklabels():
            t.set_ha("right")
    fig.tight_layout(); fs.save(fig, f"{r.out}/collapse")

    # ---- representative image strip -------------------------------------
    if not a.no_strip:
        reps = {str(k): r.median_well(ref[ref[gcol] == k]) for k in keys
                if len(ref[ref[gcol] == k])}
        S["representative_wells"] = reps
        try:
            crops = [(k, r.well_crop(v["scan_name"], v["roi_label"], a.volt), v)
                     for k, v in reps.items()]
            allpx = np.concatenate([c[1][0].ravel() for c in crops])
            vmin, vmax = np.percentile(allpx, 55), np.percentile(allpx, 99.9)
            n = len(crops)
            # 25 mm per well image, capped at a double column.
            pw = min(25.0, fs.DOUBLE_COLUMN / max(n, 1))
            fig, axes = fs.grid(1, n, pw * n, pw * 1.35)
            for ax, (k, (db, ext, roi), v) in zip(np.atleast_1d(axes), crops):
                ax.imshow(db, extent=ext, cmap="hot", vmin=vmin, vmax=vmax,
                          aspect="auto")
                ax.add_patch(Rectangle((roi["x_min"], roi["z_min"]),
                                       roi["x_max"] - roi["x_min"],
                                       roi["z_max"] - roi["z_min"],
                                       fill=False, ec=fs.OVERLAY["sample"], lw=0.5))
                ax.set_title(str(k)[:18], fontsize=8)
                ax.set_xlabel(f"{v['sbr_x']:.1f} dB", fontsize=8, color=fs.GREY_DARK)
                ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
                for s in ax.spines.values():
                    s.set_visible(False)
            fig.suptitle(f"median well per {gcol} · {a.volt:g} V "
                         f"({S['ref_pressure_MPa']:.2f} MPa) · shared colour scale",
                         fontsize=8, color=fs.GREY_DARK, y=1.04)
            fs.save(fig, f"{r.assets}/strip")
        except Exception as e:                      # noqa: BLE001
            print(f"  (strip skipped: {e})")

    r.save_json(S)
    write_results_md(r, S, gcol, a)
    print(f"  wrote {r.out}/")
    for f in sorted(os.listdir(r.out)):
        print(f"    {f}")


def write_results_md(r, S, gcol, a):
    """Scaffold. Facts and QC are filled in; interpretation is left to write."""
    p = os.path.join(r.out, "RESULTS.md")
    if os.path.exists(p):
        print(f"  RESULTS.md exists — leaving it alone (delete to regenerate)")
        return
    g = S["groups"]
    tbl = "\n".join(
        f"| {k} | {v['n']} | {v['ref_mean']:.2f} ± {v['ref_sem']:.2f} | "
        f"{v['peak_mean']:.2f} | {v['peak_MPa']:.2f} | "
        f"{v['median_threshold_MPa']:.2f}{'' if v['turned_over'] else ' (not reached)'} |"
        for k, v in g.items())
    qc = []
    if "plate_r" in S:
        qc.append(f"- **Position control.** Two plates, the second rotated 180°. "
                  f"Agreement r = {S['plate_r']}, mean absolute difference "
                  f"{S['plate_mad']} dB.")
    if "roi" in S:
        t = S["roi"]
        qc.append(f"- **ROI geometry.** {t['n']} wells; tops {t['top_mm'][0]}–"
                  f"{t['top_mm'][2]} mm (median {t['top_mm'][1]}), shared bottom "
                  f"{'/'.join(str(b) for b in t['bottom_mm'])} mm, median width "
                  f"{t['width_mm']} mm.")
    if S["ramp_truncated"]:
        qc.append("- **The ramp never reached collapse** — every condition is still "
                  "rising at the top of the ramp, so this run carries no "
                  "information about collapse pressure.")
    open(p, "w", encoding="utf-8").write(f"""# {r.name} — results

**Reference voltage:** {a.volt:g} V ({S['ref_pressure_MPa']:.2f} MPa) ·
**Metric:** `{a.metric}` (uncorrected, dB) · **Wells:** {S['n_wells']} ·
**Grouped by:** `{gcol}`

> Generated by `make_run_report.py`. Numbers come from `stats.json`; regenerate
> both together. The Interpretation section is deliberately empty — fill it in,
> or add a run-specific script in this folder.

## Summary

| {gcol} | n | {a.metric} @ {a.volt:g} V | peak | peak at | median threshold |
|---|--:|--:|--:|--:|--:|
{tbl}

## Interpretation

_TODO_

## Quality control

{chr(10).join(qc) if qc else '_none recorded_'}

## Files

| Path | Contents |
|---|---|
| `stats.json` | every number quoted here |
| `dose_response.png` | {a.metric} vs pressure, one line per {gcol} |
| `collapse.png` | peak signal and collapse threshold per {gcol} |
| `assets/strip.png` | median well per {gcol} at {a.volt:g} V |
{'| `qc.png` | plate-rotation agreement |' if 'plate_r' in S else ''}
""")


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
