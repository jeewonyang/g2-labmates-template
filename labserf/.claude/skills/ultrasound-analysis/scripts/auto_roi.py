#!/usr/bin/env python3
"""
auto_roi.py — infer ROI placement from image evidence + geometry priors, so the
xAM and BURST pipelines can run unattended.

Writes ROI JSON files in exactly the format `us_proc_v5` already reads, so no
change to the processing scripts is needed:

    plate_l22 / plate_ge : <plate>/roi/<well_folder>_rois.json   -> run with --roi_per_well
    manual               : <parent>/Processed-Data/<scan>_roi/rois.json
    burst                : <burst folder>/output/roi_defs.json

**Every run also writes a review image** showing the reference frame with each
ROI drawn on it. Look at it before trusting the numbers — that is the whole point
of automating the drawing rather than the checking.

How it finds the wells
----------------------
1. Build a reference image that shows the vessel regardless of GV content:
   B-mode (averaged over pre-collapse frames) for xAM modes, and the
   burst-minus-background difference image for BURST.
2. Subtract a per-row low percentile. The plate bottom, the meniscus and the
   ceiling reflection are full-width horizontal lines; the wells are localized.
   Row-percentile subtraction removes the former and leaves the latter.
3. Restrict to a depth prior window (AM ~5 mm, BURST ~8 mm or P.txFocus_mm).
4. Seed lateral centres from the layout prior, then refine each to the nearest
   local maximum. A seeded search still finds an *empty* well, which a pure
   peak-finder would miss — and empty wells are exactly the ones you need.
5. Size each ROI from the half-maximum extent of its own peak, clamped to
   sane physical bounds.
6. Place the noise ROI in the darkest band below the samples, and (GE) the
   ceiling ROI on the bright reflection below that.

Usage
-----
    # whole plate, one ROI set per well
    python auto_roi.py "<date>/plate" --mode plate_ge
    python auto_roi.py "<date>/plate" --mode plate_l22

    # a single manual/phantom acquisition (circular wells)
    python auto_roi.py "<acquisition folder>" --mode manual --n-rois 2

    # a BURST acquisition
    python auto_roi.py "<BURST folder>" --mode burst --n-rois 2

    # override the depth prior / sizes
    python auto_roi.py ... --depth-mm 6.0 --depth-tol 2.0 --roi-width 2.4
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")          # review images only; never opens a window
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "figure-design" / "scripts"))
import figstyle as fs  # noqa: E402  (lab figure rules: 8 pt Arial, 0.5 pt lines)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from identify_dataset import (          # noqa: E402
    classify, read_p_struct, _first, VSEQ_RE, BLOCK_RE, find_well_folders,
)

# ---------------------------------------------------------------- priors

# Depth of the imaged sample, in mm. The user's working rule.
DEPTH_PRIOR = {"xAM": 5.0, "BURST": 8.0}

# Lateral well centres, mm, relative to the array centre.
#   GE   images three U-bottom wells at once, 9 mm apart (P.zDist = 27 = 3 x 9).
#   L22  images one well, centred.
LATERAL_PRIOR = {
    "plate_ge":  [-9.0, 0.0, 9.0],
    "plate_l22": [0.0],
}

ROI_SHAPE = {          # what the vessel actually looks like in each layout
    "plate_ge":  "rect",     # U-bottom well, wider than tall
    "plate_l22": "rect",
    "manual":    "circle",   # phantom inclusions are round
    "burst":     "circle",
}

DEFAULTS = dict(
    roi_width=2.0,      # mm, lateral, fallback when the peak has no clear width
    roi_height=1.1,     # mm, axial
    min_width=0.8, max_width=4.0,
    min_height=0.5, max_height=3.0,
    min_radius=0.4, max_radius=2.0,
    noise_height=1.6,   # mm, axial extent of the noise band
)


# ---------------------------------------------------------------- loading

def _g(folder, pattern: str) -> list:
    """glob inside a directory, escaping metacharacters in the directory name.

    Acquisition folders are named from free-text sample lists such as
    "{Q7,G82A,G82P}_2024-11-23@00-07-48"; a "[" in one of those would otherwise
    be read as a glob character set.
    """
    return sorted(glob.glob(os.path.join(glob.escape(str(folder)), pattern)))


def _load_imgdata(path: str):
    import scipy.io
    m = scipy.io.loadmat(path, squeeze_me=True, struct_as_record=False)
    I = m["ImgData"]
    if hasattr(I, "Imx"):
        return (np.asarray(I.Imb, float), np.asarray(I.Xb, float).ravel(),
                np.asarray(I.Zb, float).ravel(),
                np.asarray(I.Imx, float), np.asarray(I.Xx, float).ravel(),
                np.asarray(I.Zx, float).ravel())
    im = np.asarray(I.Im, float)
    x = np.asarray(I.x, float).ravel(); z = np.asarray(I.z, float).ravel()
    return np.zeros_like(im), x, z, im, x, z


def reference_xam(folder: str, prefer: str = "bmode"):
    """
    Reference image for an xAM acquisition folder.

    Returns (ref, X, Z, xam_peak, note).
      ref      — what ROIs are fitted to (B-mode mean: shows the vessel whether
                 or not it contains gas vesicles)
      xam_peak — brightest xAM frame, drawn underneath the ROIs in the review
                 image so signal and placement can be judged together
    """
    files = sorted(_g(folder, "Imgdata_*.mat") or _g(folder, "*.mat"),
                   key=lambda f: int(m.group(1)) if (m := VSEQ_RE.search(f)) else 0)
    if not files:
        raise FileNotFoundError(f"No .mat files in {folder}")

    P = read_p_struct(files[0])
    seed = np.atleast_1d(P.get("seed", [])).ravel()
    n_pre = len(seed) if len(seed) else len(files)

    b_sum = None; n_b = 0
    best_x = None; best_mean = -np.inf
    Xb = Zb = Xx = Zx = None

    for i, f in enumerate(files):
        try:
            Imb, Xb_, Zb_, Imx, Xx_, Zx_ = _load_imgdata(f)
        except Exception:
            continue
        if i < n_pre:                       # pre-collapse frames only
            b_sum = Imb if b_sum is None else b_sum + Imb
            n_b += 1
            # brightest xAM, ignoring the top 20 % where the interface echo sits
            skip = Imx.shape[0] // 5
            s = Imx[skip:, :].mean()
            if s > best_mean:
                best_mean, best_x = s, Imx
        Xb, Zb, Xx, Zx = Xb_, Zb_, Xx_, Zx_

    if n_b == 0:
        raise RuntimeError(f"No usable frames in {folder}")

    b_mean = b_sum / n_b
    if prefer == "xam" or (b_mean.max() <= 0):
        return best_x, Xx, Zx, best_x, f"brightest xAM frame ({len(files)} frames)"
    return b_mean, Xb, Zb, best_x, f"mean of {n_b} pre-collapse B-mode frames"


def reference_burst(folder: str):
    """
    Reference image for a BURST folder: burst frame minus post-collapse mean.
    The collapse transient is what localizes the sample.
    """
    import h5py
    blocks = sorted(_g(folder, "image_block_*.mat"),
                    key=lambda f: int(BLOCK_RE.search(os.path.basename(f)).group(1)))
    if not blocks:
        raise FileNotFoundError(f"No image_block_*.mat in {folder}")

    frames, x, z = [], None, None
    n_pre = n_col = n_post = 0
    focus = np.nan
    for i, p in enumerate(blocks):
        with h5py.File(p, "r") as f:
            R = np.array(f["RData"], float)
            if x is None:
                x = np.array(f["x"], float).ravel()
                z = np.array(f["z"], float).ravel()
                if "P" in f:
                    g = lambda k: float(np.array(f["P"][k]).ravel()[0]) if k in f["P"] else np.nan
                    n_pre = int(g("numPreColFrames") or 0)
                    n_col = int(g("numColFrames") or 0)
                    n_post = int(g("numPostColFrames") or 0)
                    focus = g("txFocus_mm")
        frames.append(R if R.shape == (len(z), len(x)) else R.T)

    A = np.stack(frames)
    if n_post > 0 and (n_pre + n_col) < len(A):
        bg_idx = np.arange(n_pre + n_col, len(A))
    else:
        bg_idx = np.arange(max(0, len(A) - 10), len(A))
    burst_idx = int(np.argmax(A.mean(axis=(1, 2))))

    diff = A[burst_idx] - A[bg_idx].mean(axis=0)
    note = (f"burst frame {burst_idx + 1} minus mean of {len(bg_idx)} background "
            f"frames ({n_pre} pre / {n_col} collapse / {n_post} post)")
    return np.clip(diff, 0, None), x, z, focus, note


# ---------------------------------------------------------------- detection

def _db(im):
    a = np.abs(np.asarray(im, float))
    return 20 * np.log10(np.clip(a, 1e-10, None))


def _suppress_horizontal(db: np.ndarray, q: float = 25.0) -> np.ndarray:
    """Remove full-width horizontal structure (plate bottom, meniscus, ceiling)."""
    return db - np.percentile(db, q, axis=1, keepdims=True)


def _smooth(v: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n) | 1)
    k = np.ones(n) / n
    return np.convolve(v, k, mode="same")


def _half_max_extent(profile: np.ndarray, coord: np.ndarray, i_peak: int,
                     lo: float, hi: float, fallback: float) -> tuple[float, float]:
    """Walk out from a peak to half its height above the local floor."""
    floor = np.percentile(profile, 20)
    half = floor + 0.5 * (profile[i_peak] - floor)
    if not np.isfinite(half) or profile[i_peak] <= floor:
        c = coord[i_peak]
        return c - fallback / 2, c + fallback / 2

    a = i_peak
    while a > 0 and profile[a] > half:
        a -= 1
    b = i_peak
    while b < len(profile) - 1 and profile[b] > half:
        b += 1

    c0, c1 = float(coord[a]), float(coord[b])
    width = np.clip(c1 - c0, lo, hi)
    mid = 0.5 * (c0 + c1)
    return mid - width / 2, mid + width / 2


def detect_interface(ref, X, Z, search=(1.0, 7.0)) -> float:
    """
    Depth of the plate bottom / coupling interface: the strongest *full-width*
    horizontal echo in the shallow part of the image.

    This is the same feature the GE acquisition tracks as `P.interfacePos`. The
    sample sits below it, so it makes a reliable floor for the sample search —
    without it, a well with weak contents lets the search lock onto the interface.
    """
    db = _db(ref)
    lo, hi = np.searchsorted(Z, search[0]), np.searchsorted(Z, search[1])
    if hi - lo < 3:
        return float(Z[0])
    row = _smooth(db[lo:hi, :].mean(axis=1), 5)
    return float(Z[lo + int(np.argmax(row))])


def well_top_depth(ref, X, Z, cx, halfwidth=1.0, frac=0.20,
                   search=(2.0, 7.0)) -> float:
    """
    Depth at which one well's contents begin.

    Measured on the row-percentile-suppressed image, so the full-width plate
    echo is already gone and what rises is the well itself. Walking up from the
    column's peak to `frac` of its height finds the top of the ramp; the ROI's
    top edge has to sit at least this shallow or the top of the well is cut off.
    """
    resid = _suppress_horizontal(_db(ref))
    xs = np.where(np.abs(X - cx) <= halfwidth)[0]
    if xs.size == 0:
        return float(Z[0])
    prof = _smooth(resid[:, xs].mean(axis=1), 9)
    sel = np.where((Z >= search[0]) & (Z <= search[1]))[0]
    if sel.size < 3:
        return float(Z[0])
    pk = int(sel[np.argmax(prof[sel])])
    floor = np.percentile(prof[sel], 20)
    thr = floor + frac * (prof[pk] - floor)
    a = pk
    while a > sel[0] and prof[a - 1] >= thr:
        a -= 1
    return float(Z[a])


def detect_samples(ref, X, Z, *, lateral_seeds, depth_mm, depth_tol,
                   shape, cfg, search_halfwidth=3.0, z_floor=None):
    """Locate one ROI per lateral seed. Returns list of ROI dicts + diagnostics.

    `cfg["linear"]` switches detection from dB to linear intensity. BURST needs
    it: its reference is a background-subtracted difference clipped at zero, so
    ~30% of pixels are exact zeros. In dB those become -200, and the row-wise
    percentile suppression then subtracts either ~-200 or ~+100 depending on
    whether a quarter of the row happens to be empty — which makes the profile
    peak on the *emptier* rows below the disc, not on the disc. The review
    images showed the result: signal ROIs ~0.8 mm too deep and oversized. The
    linear image is already background-free, so it needs no suppression.
    """
    if cfg.get("linear"):
        resid = np.asarray(ref, float)
    else:
        db = _db(ref)
        resid = _suppress_horizontal(db)

    z_lo_search = depth_mm - depth_tol
    if z_floor is not None:
        z_lo_search = max(z_lo_search, z_floor)
    zsel = np.where((Z >= z_lo_search) & (Z <= depth_mm + depth_tol))[0]
    if zsel.size < 3:
        zsel = np.where((Z >= depth_mm - depth_tol) & (Z <= depth_mm + depth_tol))[0]
    if zsel.size < 3:
        zsel = np.arange(len(Z))
    dz = float(np.median(np.diff(Z))) if len(Z) > 1 else 0.01
    dx = float(np.median(np.diff(X))) if len(X) > 1 else 0.01

    lat_prof = _smooth(resid[zsel, :].mean(axis=0), max(3, int(0.3 / max(dx, 1e-6))))

    rois, diag = [], []
    for seed in lateral_seeds:
        cand = np.where(np.abs(X - seed) <= search_halfwidth)[0]
        if cand.size == 0:
            cand = np.array([int(np.argmin(np.abs(X - seed)))])
        i_x = int(cand[np.argmax(lat_prof[cand])])

        x_lo, x_hi = _half_max_extent(lat_prof, X, i_x,
                                      cfg["min_width"], cfg["max_width"],
                                      cfg["roi_width"])

        # depth profile, restricted to this well's own lateral span
        xs = np.where((X >= x_lo) & (X <= x_hi))[0]
        if xs.size == 0:
            xs = np.array([i_x])
        dep_prof_full = _smooth(resid[:, xs].mean(axis=1),
                                max(3, int(0.2 / max(dz, 1e-6))))
        i_z = int(zsel[np.argmax(dep_prof_full[zsel])])

        fixed_z = cfg.get("fixed_z")
        if fixed_z is not None and shape != "circle":
            # One depth window for every well on the plate. The wells are at the
            # same stage height and the xAM sensitivity band is a property of the
            # acquisition, so letting each ROI find its own depth only adds
            # well-to-well variation that is not biology. i_z is still recorded
            # so the review output shows where the peak actually sat.
            z_lo, z_hi = fixed_z
        else:
            z_lo, z_hi = _half_max_extent(dep_prof_full, Z, i_z,
                                          cfg["min_height"], cfg["max_height"],
                                          cfg["roi_height"])
            if z_floor is not None and z_lo < z_floor:
                # never let the ROI reach up into the interface echo
                z_hi += (z_floor - z_lo)
                z_lo = z_floor

        # --- clamp to the depth band where xAM is actually sensitive ---------
        # xAM signal dies away below the transmit focus, so a box fitted to the
        # B-mode (which keeps showing the well right down to its far wall) runs
        # into a dead zone and dilutes the mean. The band is a property of the
        # acquisition, not of the well, so it is measured once across the plate
        # and applied to every well — including empty ones, which then keep the
        # same geometry and stay comparable.
        band = cfg.get("signal_band")
        if band is not None and shape != "circle" and cfg.get("fixed_z") is None:
            z_lo = max(z_lo, band[0])
            z_hi = min(z_hi, band[1])
            if z_hi - z_lo < cfg["min_height"]:      # band and well barely overlap
                mid = 0.5 * (max(z_lo, band[0]) + min(z_hi, band[1]))
                z_lo, z_hi = mid - cfg["min_height"] / 2, mid + cfg["min_height"] / 2

        fill_ref = cfg.get("fill_ref")

        # --- follow the sample surface in an under-filled well ---------------
        # The shared window fixes the depth for normally-filled wells; here the
        # top is pushed DOWN (never up) to wherever the agarose actually starts,
        # so a half-filled well is measured on sample rather than on empty space.
        surf_top = None
        if cfg.get("fill_top_pct") is not None and shape != "circle":
            tops, _ = fill_surface_per_column(fill_ref if fill_ref is not None else ref,
                                              X, Z, x_lo, x_hi, z_lo, z_hi)
            good = tops[np.isfinite(tops)]
            if good.size >= 3:
                cand = float(np.percentile(good, cfg["fill_top_pct"]))
                # only ever deepen, and never past the point of collapsing the box
                if cand > z_lo + 0.05 and (z_hi - cand) >= cfg["min_height"]:
                    z_lo = cand; surf_top = cand

        # --- trim away unfilled parts of a partially loaded well -------------
        fill = cfg.get("min_fill")
        fill_ref = cfg.get("fill_ref")
        if fill is not None and fill_ref is not None and shape != "circle":
            x_lo, x_hi, z_lo, z_hi, filled = _trim_to_filled(
                fill_ref, X, Z, x_lo, x_hi, z_lo, z_hi, fill, cfg,
                lock_depth=cfg.get("fixed_z") is not None)
        else:
            filled = None

        scale = cfg.get("roi_scale", 1.0)
        if scale != 1.0:
            # Shrink/grow about the centre. The half-maximum extent covers the
            # whole vessel, which is more reproducible than a hand-drawn box but
            # reads 1-2 dB lower because it averages in the dimmer well edges.
            # Scale < 1 concentrates on the core, matching the historical
            # hand-drawn convention more closely.
            cx, cz = 0.5 * (x_lo + x_hi), 0.5 * (z_lo + z_hi)
            hw = 0.5 * (x_hi - x_lo) * scale
            x_lo, x_hi = cx - hw, cx + hw
            if cfg.get("fixed_z") is None:
                hh = 0.5 * (z_hi - z_lo) * scale
                z_lo, z_hi = cz - hh, cz + hh

        if shape == "circle":
            r = float(np.clip(0.25 * ((x_hi - x_lo) + (z_hi - z_lo)),
                              cfg["min_radius"], cfg["max_radius"]))
            roi = {"center_x": 0.5 * (x_lo + x_hi),
                   "center_z": 0.5 * (z_lo + z_hi), "radius": r}
        else:
            roi = {"x_min": x_lo, "x_max": x_hi, "z_min": z_lo, "z_max": z_hi}

        rois.append(roi)
        if cfg.get("linear"):
            # Linear profile: express contrast as a ratio in dB so the printed
            # "dB" means the same thing in both modes. The floor is bounded
            # away from zero because a clipped difference image has true zeros.
            peak = float(lat_prof[i_x])
            floor = max(float(np.percentile(lat_prof, 20)), 1e-3 * abs(peak), 1e-12)
            contrast = float(20 * np.log10(max(peak, 1e-12) / floor))
        else:
            contrast = float(lat_prof[i_x] - np.percentile(lat_prof, 20))
        diag.append({"seed_x": seed, "found_x": float(X[i_x]),
                     "found_z": float(Z[i_z]), "contrast_db": contrast,
                     "filled_frac": filled, "surface_top": surf_top})
    return rois, diag, resid


def fill_surface_per_column(fill_ref, X, Z, x_lo, x_hi, z_lo, z_hi, margin=0.9):
    """
    Depth of the sample surface in each column of a well.

    A well that was not filled to the top holds its agarose lower down, under a
    dished (concave) surface — shallower against the walls, deeper mid-well. The
    shared depth window then starts *above* the sample and the ROI averages in
    empty space, which reads as a weak well.

    Detected on the raw B-mode: within each column, walk down from the top of the
    search band to the first depth where the signal crosses the midpoint between
    that column's own low and high levels and stays there. Returns one depth per
    column (NaN where no clear step exists).
    """
    db = _db(fill_ref)
    xs = np.where((X >= x_lo) & (X <= x_hi))[0]
    zs = np.where((Z >= z_lo - margin) & (Z <= z_hi))[0]
    if xs.size == 0 or zs.size < 6:
        return np.array([]), np.array([])
    dz = float(np.median(np.diff(Z))) if len(Z) > 1 else 0.01
    run = max(2, int(0.12 / max(dz, 1e-6)))          # must stay above threshold this long
    tops = []
    for c in xs:
        prof = _smooth(db[zs, c], 5)
        lo, hi = np.percentile(prof, 15), np.percentile(prof, 85)
        if hi - lo < 4.0:                             # no step: uniformly full or empty
            tops.append(np.nan); continue
        thr = lo + 0.5 * (hi - lo)
        hit = np.nan
        for i in range(len(prof) - run):
            if np.all(prof[i:i + run] >= thr):
                hit = Z[zs[i]]; break
        tops.append(hit)
    return np.asarray(tops, dtype=float), xs


def _trim_to_filled(fill_ref, X, Z, x_lo, x_hi, z_lo, z_hi, target, cfg,
                    lock_depth=False):
    """
    Shrink a candidate box until most of it is actually filled with sample.

    A U-bottom well that was under-loaded holds a concave-up meniscus: the middle
    is full but the sample thins out towards the walls, so the nominal rectangle
    contains air. Averaging that in reports a real well as weak.

    "Filled" is judged on the row-percentile-suppressed B-mode: a pixel counts if
    it is within `fill_db` of the box's own 90th percentile. The box is trimmed
    from whichever edge is emptiest until the filled fraction reaches `target`
    (or the box hits its minimum size).

    Returns (x_lo, x_hi, z_lo, z_hi, filled_fraction).
    """
    resid = _suppress_horizontal(_db(fill_ref))
    fill_db = cfg.get("fill_db", 12.0)

    def box_idx(a, b, c, d):
        xs = np.where((X >= a) & (X <= b))[0]
        zs = np.where((Z >= c) & (Z <= d))[0]
        return xs, zs

    def filled_frac(a, b, c, d):
        xs, zs = box_idx(a, b, c, d)
        if xs.size == 0 or zs.size == 0:
            return 0.0, None
        sub = resid[np.ix_(zs, xs)]
        thr = np.percentile(sub, 90) - fill_db
        return float((sub >= thr).mean()), sub >= thr

    frac, mask = filled_frac(x_lo, x_hi, z_lo, z_hi)
    if mask is None:
        return x_lo, x_hi, z_lo, z_hi, frac

    dx = float(np.median(np.diff(X))) if len(X) > 1 else 0.01
    dz = float(np.median(np.diff(Z))) if len(Z) > 1 else 0.01
    step_x, step_z = max(dx, 0.05), max(dz, 0.03)

    if lock_depth:
        # The depth window is shared across the plate, so part of it can sit above
        # a deeper-seated well. That emptiness is in the locked axis and shrinking
        # laterally cannot fix it — chasing a whole-box target here would eat the
        # well's width instead. Judge each COLUMN against the well's own typical
        # column and drop only edge columns that are clearly emptier: that removes
        # wall and meniscus edges while leaving the width alone.
        for _ in range(60):
            _, mask = filled_frac(x_lo, x_hi, z_lo, z_hi)
            if mask is None or mask.size == 0 or (x_hi - x_lo) <= cfg["min_width"]:
                break
            colfill = mask.mean(axis=0)
            ref = np.median(colfill)
            if ref <= 0:
                break
            cut = cfg.get("edge_col_frac", 0.5) * ref
            if colfill[0] < cut:
                x_lo += step_x
            elif colfill[-1] < cut:
                x_hi -= step_x
            else:
                break
        frac, _ = filled_frac(x_lo, x_hi, z_lo, z_hi)
        return x_lo, x_hi, z_lo, z_hi, frac

    # Free depth: trim whichever edge is emptiest until the box meets the target.
    for _ in range(60):
        if frac >= target:
            break
        _, mask = filled_frac(x_lo, x_hi, z_lo, z_hi)
        if mask is None or mask.size == 0:
            break
        cand = []
        if (x_hi - x_lo) > cfg["min_width"]:
            cand.append(("xl", mask[:, 0].mean()))
            cand.append(("xr", mask[:, -1].mean()))
        if (z_hi - z_lo) > cfg["min_height"]:
            cand.append(("zt", mask[0, :].mean()))
            cand.append(("zb", mask[-1, :].mean()))
        if not cand:
            break
        edge = min(cand, key=lambda t: t[1])[0]
        if edge == "xl":
            x_lo += step_x
        elif edge == "xr":
            x_hi -= step_x
        elif edge == "zt":
            z_lo += step_z
        else:
            z_hi -= step_z
        frac, _ = filled_frac(x_lo, x_hi, z_lo, z_hi)

    return x_lo, x_hi, z_lo, z_hi, frac


def xam_sensitivity_band(profiles, Z, drop_db=6.0, min_peak_db=3.0, z_window=None):
    """
    Depth range over which xAM actually carries signal, measured across a plate.

    `profiles` is one normalized xAM depth profile (dB, relative to that well's
    own noise floor) per well. Wells whose peak never rises `min_peak_db` above
    their floor are empty and are excluded — they carry no information about
    where the focus is. The band is the contiguous span around the median
    profile's peak that stays within `drop_db` of it.

    Returns (z_lo, z_hi, n_wells_used) or None when nothing has signal.
    """
    # Confine the search to where a sample can plausibly be. Plates show a strong
    # specular reflection ~10 mm below the wells that is brighter in xAM than the
    # sample itself; without this window the band locks onto that instead.
    if z_window is not None:
        ok = np.where((Z >= z_window[0]) & (Z <= z_window[1]))[0]
    else:
        ok = np.arange(len(Z))
    if ok.size < 3:
        return None

    good = [p for p in profiles
            if np.nanmax(p[ok]) - np.nanmedian(p[ok]) >= min_peak_db]
    if len(good) < 2:
        return None
    med = np.nanmedian(np.vstack(good), axis=0)

    i_pk = int(ok[np.nanargmax(med[ok])])
    thr = med[i_pk] - drop_db

    lo_bound, hi_bound = int(ok[0]), int(ok[-1])
    a = i_pk
    while a > lo_bound and med[a - 1] >= thr:
        a -= 1
    b = i_pk
    while b < hi_bound and med[b + 1] >= thr:
        b += 1
    return float(Z[a]), float(Z[b]), len(good)


def well_xam_profile(Imx, X, Z, x_lo, x_hi):
    """xAM depth profile inside one well's lateral span, in dB above its own floor."""
    xs = np.where((X >= x_lo) & (X <= x_hi))[0]
    if xs.size == 0:
        return None
    prof = _db(Imx[:, xs].mean(axis=1))
    return _smooth(prof - np.nanpercentile(prof, 20), 9)


def detect_noise(ref, X, Z, sample_rois, cfg, avoid_below=1.0):
    """Darkest horizontal band below the samples, over the central lateral half."""
    db = _db(ref)
    z_bottom = max(r.get("z_max", r.get("center_z", 0) + r.get("radius", 0))
                   for r in sample_rois)
    x_span = X.max() - X.min()
    x_lo, x_hi = X.min() + 0.25 * x_span, X.min() + 0.75 * x_span
    xs = np.where((X >= x_lo) & (X <= x_hi))[0]

    row = db[:, xs].mean(axis=1)
    dz = float(np.median(np.diff(Z))) if len(Z) > 1 else 0.01
    band = max(3, int(cfg["noise_height"] / max(dz, 1e-6)))

    lo_idx = np.searchsorted(Z, z_bottom + avoid_below)
    hi_idx = len(Z) - band
    if lo_idx >= hi_idx:                      # not enough depth below the sample
        lo_idx, hi_idx = 0, max(1, len(Z) - band)

    cums = np.convolve(row, np.ones(band) / band, mode="valid")
    win = cums[lo_idx:hi_idx]
    if win.size == 0:
        i0 = lo_idx
    else:
        i0 = lo_idx + int(np.argmin(win))
    return {"x_min": float(x_lo), "x_max": float(x_hi),
            "z_min": float(Z[i0]), "z_max": float(Z[min(i0 + band, len(Z) - 1)])}


def detect_ceiling(ref, X, Z, noise_roi, cfg):
    """Brightest full-width horizontal reflection below the noise band (GE plates)."""
    db = _db(ref)
    x_span = X.max() - X.min()
    x_lo, x_hi = X.min() + 0.22 * x_span, X.min() + 0.78 * x_span
    xs = np.where((X >= x_lo) & (X <= x_hi))[0]
    row = db[:, xs].mean(axis=1)

    lo_idx = np.searchsorted(Z, noise_roi["z_max"])
    if lo_idx >= len(Z) - 3:
        lo_idx = max(0, len(Z) - 20)
    i_pk = lo_idx + int(np.argmax(row[lo_idx:]))
    dz = float(np.median(np.diff(Z))) if len(Z) > 1 else 0.01
    half = max(2, int(1.4 / max(dz, 1e-6)))
    a, b = max(0, i_pk - half), min(len(Z) - 1, i_pk + half)
    return {"x_min": float(x_lo), "x_max": float(x_hi),
            "z_min": float(Z[a]), "z_max": float(Z[b])}


# ---------------------------------------------------------------- review image

def _draw_rois(ax, roi_data, only=None):
    # figstyle.OVERLAY: magenta reads against every part of the `hot` ramp
    # (black -> red -> white); orange and white vanish on a saturated BURST
    # difference image. Same colours as every other LabSerf image overlay.
    colors = {"noise": fs.OVERLAY["noise"], "ceiling": fs.OVERLAY["ceiling"]}
    for label, r in roi_data.items():
        if only is not None and label not in only:
            continue          # ROI lies outside this panel's depth window
        c = colors.get(label, fs.OVERLAY["sample"])
        if "radius" in r:
            ax.add_patch(Circle((r["center_x"], r["center_z"]), r["radius"],
                                fill=False, edgecolor=c, lw=0.5))
            ax.text(r["center_x"] - r["radius"], r["center_z"] - r["radius"] - 0.25,
                    label, color=c, fontsize=8)
        else:
            ax.add_patch(Rectangle((r["x_min"], r["z_min"]),
                                   r["x_max"] - r["x_min"], r["z_max"] - r["z_min"],
                                   fill=False, edgecolor=c, lw=0.5))
            ax.text(r["x_min"], r["z_min"] - 0.25, label,
                    color=c, fontsize=8)


def _roi_zlim(roi_data, Z, pad=1.5, keys=None):
    """Depth window that comfortably contains the named ROIs, for review panels."""
    lo, hi = [], []
    items = roi_data.items() if keys is None else [
        (k, v) for k, v in roi_data.items() if k in keys]
    for _, r in items:
        if "radius" in r:
            lo.append(r["center_z"] - r["radius"]); hi.append(r["center_z"] + r["radius"])
        else:
            lo.append(r["z_min"]); hi.append(r["z_max"])
    if not lo:
        return None
    return max(float(Z.min()), min(lo) - pad), min(float(Z.max()), max(hi) + pad)


def _show(ax, im, X, Z, title, cmap="hot", log=True, zlim=None):
    # A BURST difference image is already background-subtracted and clipped at 0,
    # so most of it is exactly zero; taking dB of that saturates the display.
    # Show those linearly instead.
    disp = _db(im) if log else np.asarray(im, float)
    # Scale the display over the depth window being reviewed, not the whole image:
    # most of an xAM frame is noise below the sample, and including it pushes the
    # percentile range up until the wells wash out.
    if zlim is not None:
        zs = np.where((Z >= zlim[0]) & (Z <= zlim[1]))[0]
        ref = disp[zs, :] if zs.size else disp
    else:
        ref = disp
    lo, hi = (55, 99.7) if log else (50, 99.5)
    ax.imshow(disp, extent=[X.min(), X.max(), Z.max(), Z.min()], cmap=cmap,
              vmin=np.nanpercentile(ref, lo), vmax=np.nanpercentile(ref, hi),
              origin="upper", interpolation="nearest",
              aspect="equal" if zlim is None else "auto")
    if zlim is not None:
        ax.set_ylim(zlim[1], zlim[0])
    ax.set_title(title, fontsize=8)
    ax.set_xlabel("Lateral (mm)", fontsize=8)
    ax.set_ylabel("Depth (mm)", fontsize=8)


def save_review(path, ref, X, Z, roi_data, note, second=None, second_title=None,
                title=None, log=True):
    fs.use()
    n = 2 if second is not None else 1
    fig, axes = fs.grid(1, n, 86.0 * n, 80.0)
    axes = np.atleast_1d(axes)
    zl = _roi_zlim(roi_data, Z, pad=2.5)
    _show(axes[0], ref, X, Z, f"Reference — {note}", log=log, zlim=zl)
    _draw_rois(axes[0], roi_data)
    if second is not None:
        _show(axes[1], second, X, Z, second_title or "xAM", zlim=zl)
        _draw_rois(axes[1], roi_data)
    fig.suptitle(title or Path(path).parent.name, fontsize=8)
    fig.tight_layout()
    fs.save_png(fig, str(path))


def save_contact_sheet(path, panels, ncols=6, subtitle="", zoom_samples=False):
    """One small panel per well, so a whole plate can be checked at a glance."""
    fs.use()
    n = len(panels)
    ncols = min(ncols, max(1, n))
    nrows = int(np.ceil(n / ncols))
    # Fit a double column: panel width follows from the column count.
    pw = (fs.DOUBLE_COLUMN - 8) / ncols
    ph = pw * (0.6 if zoom_samples else 1.07)
    fig, axes = fs.grid(nrows, ncols, pw * ncols, ph * nrows + 14)
    axes = np.atleast_1d(axes).ravel()
    for ax, (name, im, X, Z, roi_data) in zip(axes, panels):
        keys = ([k for k in roi_data if k not in ("noise", "ceiling")]
                if zoom_samples else None)
        _show(ax, im, X, Z, name, zlim=_roi_zlim(roi_data, Z, keys=keys))
        _draw_rois(ax, roi_data, only=keys)
        ax.set_xlabel(""); ax.set_ylabel("")
    for ax in axes[n:]:
        ax.axis("off")
    fig.suptitle(f"Auto-ROI review — {n} scan positions{subtitle}\n"
                 f"magenta = sample, cyan = noise, green = ceiling", fontsize=8)
    fig.tight_layout()
    fs.save_png(fig, str(path))


# ---------------------------------------------------------------- drivers

def run_xam_folder(folder, labels, lateral_seeds, shape, depth_mm, depth_tol,
                   cfg, want_ceiling, prefer_ref, search_halfwidth,
                   use_interface=True, interface_gap=0.35, cached=None):
    ref, X, Z, xam, note = cached if cached is not None else reference_xam(folder, prefer_ref)
    cfg = dict(cfg, fill_ref=ref)      # judge "filled" on the B-mode reference
    z_if = detect_interface(ref, X, Z) if use_interface else None
    z_floor = (z_if + interface_gap) if z_if is not None else None
    rois, diag, _ = detect_samples(ref, X, Z, lateral_seeds=lateral_seeds,
                                   depth_mm=depth_mm, depth_tol=depth_tol,
                                   shape=shape, cfg=cfg,
                                   search_halfwidth=search_halfwidth,
                                   z_floor=z_floor)
    roi_data = {"noise": detect_noise(ref, X, Z, rois, cfg)}
    for lab, r in zip(labels, rois):
        roi_data[lab] = r
    if want_ceiling:
        roi_data["ceiling"] = detect_ceiling(ref, X, Z, roi_data["noise"], cfg)
    for d in diag:
        d["interface_z"] = z_if
    return roi_data, ref, X, Z, xam, note, diag


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--mode", default="auto",
                    choices=["auto", "plate_ge", "plate_l22", "manual", "burst"])
    ap.add_argument("--n-rois", type=int, default=None,
                    help="number of sample ROIs (manual/burst; default 2)")
    ap.add_argument("--labels", default=None, help="comma-separated ROI labels")
    ap.add_argument("--shape", default="auto", choices=["auto", "rect", "circle"])
    ap.add_argument("--depth-mm", type=float, default=None,
                    help="expected sample depth (default: 5 for xAM, 8 or P.txFocus_mm for BURST)")
    ap.add_argument("--depth-tol", type=float, default=2.5,
                    help="+/- search window around the depth prior, mm (default 2.5)")
    ap.add_argument("--roi-width", type=float, default=DEFAULTS["roi_width"])
    ap.add_argument("--roi-height", type=float, default=DEFAULTS["roi_height"])
    ap.add_argument("--roi-scale", type=float, default=1.0,
                    help="shrink (<1) or grow (>1) every sample ROI about its centre. "
                         "Default 1.0 covers the whole vessel; ~0.7 concentrates on "
                         "the bright core, which reads ~1-2 dB higher and is closer "
                         "to the historical hand-drawn convention.")
    ap.add_argument("--reference", default="bmode", choices=["bmode", "xam"],
                    help="image to fit ROIs to (default bmode — shows the well "
                         "whether or not it contains GVs)")
    ap.add_argument("--signal-band", default="auto",
                    help="depth range (mm) over which xAM is sensitive, as 'lo,hi'. "
                         "'auto' (default) measures it from the wells that have "
                         "signal; 'off' disables the clamp. xAM dies below the "
                         "transmit focus while B-mode does not, so without this a "
                         "B-mode-fitted ROI averages in a dead zone.")
    ap.add_argument("--depth-range", default=None, metavar="LO,HI",
                    help="use this exact sample-ROI depth window (mm) for every "
                         "well, overriding the measured one.")
    ap.add_argument("--depth-max", type=float, default=None, metavar="MM",
                    help="cap the deep edge of the measured window at this depth. "
                         "xAM fades below the focus while the well's specular "
                         "bottom echo stays bright, so the measured band can run "
                         "past where there is usable signal.")
    ap.add_argument("--top-percentile", type=float, default=10.0, metavar="P",
                    help="percentile of the measured per-well top depths used as "
                         "the shared ROI top (default 10, i.e. reach the top of "
                         "~90%% of wells). Raise it to trade top coverage for less "
                         "empty space in the deeper-sitting wells.")
    ap.add_argument("--interface-gap", type=float, default=0.25, metavar="MM",
                    help="start the ROI this far below the plate-bottom interface "
                         "echo (default 0.25). The well begins immediately under "
                         "the interface, so the top edge is set from the interface, "
                         "not from where the xAM profile peaks.")
    ap.add_argument("--no-fixed-depth", dest="fixed_depth", action="store_false",
                    help="let each well find its own depth extent (default: one "
                         "window shared by every well on the plate)")
    ap.set_defaults(fixed_depth=True)
    ap.add_argument("--band-drop-db", type=float, default=6.0,
                    help="how far below its peak the median xAM profile may fall "
                         "and still count as sensitive (default 6 dB)")
    ap.add_argument("--fill-top-pct", type=float, default=80.0, metavar="P",
                    help="in an under-filled well the agarose sits below the shared "
                         "window top under a dished surface. The ROI top is pushed "
                         "down to this percentile of the per-column sample-surface "
                         "depths (default 80, i.e. clear of ~80%% of columns). Set to "
                         "-1 to disable and keep the shared top everywhere.")
    ap.add_argument("--min-fill", type=float, default=0.80,
                    help="minimum fraction of a sample ROI that must contain sample. "
                         "Under-loaded U-bottom wells hold a concave meniscus; the "
                         "box is trimmed until it clears this (default 0.80).")
    ap.add_argument("--fill-db", type=float, default=12.0,
                    help="a pixel counts as filled if within this many dB of the "
                         "ROI's 90th percentile (default 12)")
    ap.add_argument("--well-spacing", type=float, default=9.0,
                    help="GE lateral well spacing, mm (default 9)")
    ap.add_argument("--out", default=None, help="override output ROI JSON path")
    ap.add_argument("--review", default=None, help="override review image path")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing ROI JSON files")
    args = ap.parse_args()

    cfg = dict(DEFAULTS, roi_width=args.roi_width, roi_height=args.roi_height,
               roi_scale=args.roi_scale, min_fill=args.min_fill,
               fill_db=args.fill_db, signal_band=None,
               fill_top_pct=(None if args.fill_top_pct < 0 else args.fill_top_pct))
    root = Path(args.folder).resolve()

    # ---- resolve mode
    mode = args.mode
    if mode == "auto":
        res = classify(root)
        if res["layout"] == "plate":
            mode = res["us_proc_mode"]
        elif res["layout"] in ("flat", "session"):
            kinds = {a["kind"] for a in (res.get("acquisitions") or [])}
            mode = "burst" if kinds == {"BURST"} else "manual"
        else:
            sys.exit(f"Could not infer a mode for {root} (layout={res['layout']}). "
                     f"Pass --mode explicitly.")
        print(f"Mode        : {mode} (inferred)")
    else:
        print(f"Mode        : {mode}")

    shape = ROI_SHAPE[mode] if args.shape == "auto" else args.shape

    # ================================================== BURST
    if mode == "burst":
        folders = ([root] if _g(root, "image_block_*.mat")
                   else sorted(p for p in root.iterdir()
                               if p.is_dir() and _g(p, "image_block_*.mat")))
        if not folders:
            sys.exit(f"No BURST blocks found under {root}")
        n = args.n_rois or 2
        labels = ([l.strip() for l in args.labels.split(",")] if args.labels
                  else [f"signal_{i+1:02d}" for i in range(n)])

        for fld in folders:
            ref, X, Z, focus, note = reference_burst(str(fld))
            depth = args.depth_mm or (focus if np.isfinite(focus) else DEPTH_PRIOR["BURST"])
            seeds = _seed_positions(X, n)
            rois, diag, _ = detect_samples(ref, X, Z, lateral_seeds=seeds,
                                           depth_mm=depth, depth_tol=args.depth_tol,
                                           shape=shape, cfg=dict(cfg, linear=True),
                                           search_halfwidth=(X.max() - X.min()) / (2 * n))
            roi_data = {"noise": detect_noise(ref, X, Z, rois, cfg)}
            for lab, r in zip(labels, rois):
                roi_data[lab] = r

            out = Path(args.out) if args.out else fld / "output" / "roi_defs.json"
            rev = Path(args.review) if args.review else fld / "output" / "auto_roi_review.png"
            _write(out, _to_burst_bundle(roi_data, shape, note), args.force)
            save_review(rev, ref, X, Z, roi_data, note, title=fld.name, log=False)
            print(f"  {fld.name}: depth prior {depth:.1f} mm  ->  "
                  + ", ".join(f"{d['found_x']:+.2f}/{d['found_z']:.2f} mm "
                              f"({d['contrast_db']:.1f} dB)" for d in diag))
            print(f"    ROI  : {out}")
            print(f"    review: {rev}")
        return

    # ================================================== plates
    if mode in ("plate_ge", "plate_l22"):
        plate_dir = root / "plate" if (root / "plate").is_dir() else root
        wells = find_well_folders(plate_dir)
        if not wells:
            sys.exit(f"No well folders under {plate_dir}")

        if mode == "plate_ge":
            labels = ["well1", "well2", "well3"]
            seeds = [-args.well_spacing, 0.0, args.well_spacing]
            halfwidth = args.well_spacing / 3
        else:
            labels = ["sample"]
            seeds = [0.0]
            halfwidth = 2.0
        if args.labels:
            labels = [l.strip() for l in args.labels.split(",")]

        depth = args.depth_mm or DEPTH_PRIOR["xAM"]
        roi_dir = plate_dir / "roi"
        panels, n_ok = [], 0
        print(f"Depth prior : {depth:.1f} +/- {args.depth_tol:.1f} mm")
        print(f"Wells       : {len(wells)} scan positions x {len(labels)} ROI(s)")

        # ---- pass 1: load every well once, and measure where xAM is sensitive
        panels_x = []
        cache, profiles, Zref = {}, [], None
        for wf, _ in wells:
            try:
                ref, X, Z, xam, note = reference_xam(str(wf), args.reference)
            except Exception as e:
                print(f"  [SKIP] {wf.name}: {e}")
                continue
            cache[wf.name] = (ref, X, Z, xam, note)
            Zref = Z
            for sd in seeds:
                pr = well_xam_profile(xam, X, Z, sd - halfwidth, sd + halfwidth)
                if pr is not None:
                    profiles.append(pr)

        band = None
        if args.signal_band == "off":
            print("Signal band : disabled (--signal-band off)")
        elif args.signal_band != "auto":
            lo, hi = (float(v) for v in args.signal_band.split(","))
            band = (lo, hi)
            print(f"Signal band : {lo:.2f}-{hi:.2f} mm (given)")
        elif profiles and Zref is not None:
            # same window the sample search uses, floored at the interface
            z_if = detect_interface(*cache[next(iter(cache))][:3])
            win = (max(depth - args.depth_tol, z_if + 0.35), depth + args.depth_tol)
            res = xam_sensitivity_band(profiles, Zref, drop_db=args.band_drop_db,
                                       z_window=win)
            if res:
                band = (res[0], res[1])
                print(f"Signal band : {band[0]:.2f}-{band[1]:.2f} mm  "
                      f"(xAM within {args.band_drop_db:.0f} dB of peak, "
                      f"from {res[2]}/{len(profiles)} wells with signal)")
            else:
                print("Signal band : no well had enough xAM signal — not clamping")
        # ---- one depth window for the whole plate -------------------------
        fixed_z = None
        if args.fixed_depth:
            if args.depth_range:
                lo, hi = (float(v) for v in args.depth_range.split(","))
                fixed_z = (lo, hi)
                print(f"Depth window: {lo:.2f}-{hi:.2f} mm (given, all wells)")
            else:
                # Top edge measured from the wells themselves. Wells across a
                # plate do not sit at one height, so take a low percentile of the
                # measured tops: the shared window then reaches the top of nearly
                # every well instead of clipping the shallow half.
                tops = [well_top_depth(*cache[n][:3], cx=sd)
                        for n in cache for sd in seeds]
                tops = np.asarray(tops)
                lo = float(np.percentile(tops, args.top_percentile))
                hi = band[1] if band else (depth + args.depth_tol)
                if args.depth_max is not None:
                    hi = min(hi, args.depth_max)
                fixed_z = (lo, hi)
                print(f"Well tops   : median {np.median(tops):.2f} mm, "
                      f"range {tops.min():.2f}-{tops.max():.2f} "
                      f"(spread {tops.ptp():.2f} mm across {len(tops)} wells)")
                print(f"Depth window: {lo:.2f}-{hi:.2f} mm (all wells; top = "
                      f"p{args.top_percentile:g} of well tops"
                      + (f", capped at {args.depth_max:.2f}" if args.depth_max else "")
                      + ")")
                deep = (tops > lo).sum()
                if deep:
                    print(f"              {deep}/{len(tops)} wells start deeper than "
                          f"{lo:.2f} mm — their ROI includes some empty space above "
                          f"the sample.")
        cfg = dict(cfg, signal_band=band, fixed_z=fixed_z)
        print(f"Fill target : {args.min_fill:.0%} of each ROI must be filled\n")

        # ---- pass 2: fit ROIs
        for wf, well_id in wells:
            name = wf.name
            if name not in cache:
                continue
            try:
                roi_data, ref, X, Z, xam, note, diag = run_xam_folder(
                    str(wf), labels, seeds, shape, depth, args.depth_tol, cfg,
                    want_ceiling=(mode == "plate_ge"),
                    prefer_ref=args.reference, search_halfwidth=halfwidth,
                    cached=cache[name])
            except Exception as e:
                print(f"  [SKIP] {name}: {e}")
                continue
            out = roi_dir / f"{name}_rois.json"
            _write(out, roi_data, args.force)
            panels.append((f"{name}  (z={diag[0]['found_z']:.1f})", ref, X, Z, roi_data))
            panels_x.append((f"{name}  (z={diag[0]['found_z']:.1f})", xam, X, Z, roi_data))
            n_ok += 1
            weak = [d for d in diag if d["contrast_db"] < 1.0]
            unfilled = [d for d in diag
                        if d.get("filled_frac") is not None and d["filled_frac"] < args.min_fill]
            flag = ""
            if weak:
                flag += f"   <-- LOW CONTRAST on {len(weak)} well(s)"
            if unfilled:
                flag += f"   <-- UNDER-FILLED on {len(unfilled)} well(s)"
            nsurf=sum(1 for d in diag if d.get("surface_top") is not None)
            if nsurf: flag += f"   [{nsurf} under-filled: ROI top followed the sample surface]"
            print(f"  {name}: " + ", ".join(
                f"x{d['found_x']:+.2f} z{d['found_z']:.2f} ({d['contrast_db']:.1f} dB"
                + (f", fill {d['filled_frac']:.0%}" if d.get("filled_frac") is not None else "")
                + (f", top {d['surface_top']:.2f}" if d.get("surface_top") is not None else "")
                + ")" for d in diag) + flag)

        band_txt = (f"  |  xAM band {band[0]:.2f}-{band[1]:.2f} mm" if band else "")
        sheet = Path(args.review) if args.review else roi_dir / "auto_roi_review_xAM.png"
        sheet_b = sheet.with_name(sheet.stem.replace("_xAM", "") + "_Bmode.png")
        # xAM first: it is the measured channel, and the point of the depth band is
        # that the box must cover the xAM signal, not the full B-mode well.
        save_contact_sheet(sheet, panels_x, zoom_samples=True,
                           subtitle=f" — xAM (brightest frame), zoomed to the sample "
                                    f"ROIs{band_txt}")
        save_contact_sheet(sheet_b, panels, subtitle=" — B-mode reference (ROIs are "
                                                     "located on this)")
        print(f"\n  {n_ok}/{len(wells)} positions written to {roi_dir}/<well>_rois.json")
        print(f"  Review (xAM)    : {sheet}")
        print(f"  Review (B-mode) : {sheet_b}")
        print(f"\n  Then run unattended:\n"
              f"    python Scripts/us_proc_v5_addBURST_colormap.py {mode} "
              f'--data_dir "{plate_dir}" --roi_per_well ...')
        return

    # ================================================== manual
    # Gate on Imgdata_*.mat: a legacy MATLAB "data_<session>.mat" output often
    # sits beside the acquisition folders and would otherwise look like a leaf.
    folders = ([root] if _g(root, "Imgdata_*.mat")
               else sorted(p for p in root.iterdir()
                           if p.is_dir() and _g(p, "Imgdata_*.mat")))
    if not folders:
        sys.exit(f"No acquisition folders under {root}")

    n = args.n_rois or 2
    labels = ([l.strip() for l in args.labels.split(",")] if args.labels
              else [f"sample{i+1}" for i in range(n)])
    depth = args.depth_mm or DEPTH_PRIOR["xAM"]

    for fld in folders:
        ref, X, Z, xam, note = reference_xam(str(fld), args.reference)
        seeds = _seed_positions(X, n)
        rois, diag, _ = detect_samples(ref, X, Z, lateral_seeds=seeds,
                                       depth_mm=depth, depth_tol=args.depth_tol,
                                       shape=shape, cfg=cfg,
                                       search_halfwidth=(X.max() - X.min()) / (2 * n))
        roi_data = {"noise": detect_noise(ref, X, Z, rois, cfg)}
        for lab, r in zip(labels, rois):
            roi_data[lab] = r

        proc = fld.parent / "Processed-Data"
        out = Path(args.out) if args.out else proc / f"{fld.name}_roi" / "rois.json"
        rev = Path(args.review) if args.review else proc / f"{fld.name}_roi" / "auto_roi_review.png"
        _write(out, roi_data, args.force)
        save_review(rev, ref, X, Z, roi_data, note, second=xam,
                    second_title="brightest xAM frame", title=fld.name)
        print(f"  {fld.name}: " + ", ".join(
            f"x{d['found_x']:+.2f} z{d['found_z']:.2f} ({d['contrast_db']:.1f} dB)"
            for d in diag))
        print(f"    ROI    : {out}")
        print(f"    review : {rev}")


def _seed_positions(X, n):
    """Evenly spread seeds across the field of view, avoiding the edges."""
    if n == 1:
        return [0.0]
    lo, hi = X.min(), X.max()
    pad = 0.15 * (hi - lo)
    return list(np.linspace(lo + pad, hi - pad, n))


def _to_burst_bundle(roi_data, shape, note):
    """process_burst_acq.py expects its own RoiBundle schema, not the us_proc one."""
    import datetime as dt
    rois = []
    for label, r in roi_data.items():
        role = "noise" if label == "noise" else "signal"
        if "radius" in r:
            # its mask builder has no circle case — emit a polygon approximation
            t = np.linspace(0, 2 * np.pi, 33)[:-1]
            coords = [[float(r["center_x"] + r["radius"] * np.cos(a)),
                       float(r["center_z"] + r["radius"] * np.sin(a))] for a in t]
            rois.append({"roi_id": label, "role": role,
                         "shape": "polygon", "coords_mm": coords})
        else:
            rois.append({"roi_id": label, "role": role, "shape": "rect",
                         "coords_mm": {"xmin": r["x_min"], "xmax": r["x_max"],
                                       "zmin": r["z_min"], "zmax": r["z_max"]}})
    return {"version": "1", "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "reference_file": note, "reference_mode": "BURST", "rois": rois}


def _write(path: Path, data: dict, force: bool):
    path = Path(path)
    if path.exists() and not force:
        print(f"    [keep] {path} already exists — pass --force to replace it.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
