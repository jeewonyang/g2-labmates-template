#!/usr/bin/env python3
"""
view_bmode.py — quick B-mode viewer for Verasonics `Imgdata_Vseq*.mat` data.

B-mode is never saved on its own: every Imgdata file carries `ImgData.Imb`
next to the xAM image. This tool pulls it out, converts to dB, and renders it
with a consistent dynamic range so wells / scans / frames can be compared by
eye. It works on any of:

  * one `Imgdata_*.mat` file                       -> one PNG
  * a scan folder of `Imgdata_*.mat` files          -> one PNG (frames averaged
                                                      at one voltage, or a
                                                      per-frame montage / video)
  * a plate folder (`plate/`, or the run folder     -> one PNG per position plus
    that contains it)                                 a contact sheet
  * a session folder of several scan folders        -> one PNG per scan plus a
    (in-vivo timepoints, manual phantom runs)         contact sheet

Examples
--------
  # whole plate, frames at the starting voltage averaged, wells on a common grey scale
  python view_bmode.py "<run>/plate"

  # one well at 12 V with the analysis ROIs drawn on top, and the xAM overlaid
  python view_bmode.py "<run>/plate/plate_P_1_1/plate_P_1_1_A01" --voltage 12 --rois --overlay-xam

  # every frame of a timecourse as a montage, and as an mp4
  python view_bmode.py "<scan folder>" --all-frames --video

  # interactive window with a frame slider
  python view_bmode.py "<scan folder>" --show

Outputs land in `<input>/bmode_view/` unless `--out` is given. Nothing in the
input folder is modified.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import scipy.io as sio
except ImportError:  # pragma: no cover
    sys.exit("scipy is required: pip install scipy")

import matplotlib

# Use a non-interactive backend unless --show is requested (set in main()).
import matplotlib.pyplot as plt  # noqa: E402  (backend chosen in main)
from matplotlib.patches import Circle, Rectangle  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "figure-design", "scripts"))
import figstyle as fs  # noqa: E402  (lab figure rules: 8 pt Arial, 0.5 pt lines)

FLOOR = 1e-9  # linear floor before log so empty pixels do not blow up
XAM_ABOVE_FLOOR_DB = 8.0  # xAM overlay shows only pixels this far above the median floor


# --------------------------------------------------------------------------- IO
@dataclass
class Frame:
    path: str
    vseq_idx: int
    voltage: float
    Imb: np.ndarray            # linear B-mode, (nZ, nX)
    Xb: np.ndarray             # mm
    Zb: np.ndarray             # mm
    Imx: Optional[np.ndarray]  # linear xAM, may be None
    Xx: Optional[np.ndarray]
    Zx: Optional[np.ndarray]
    post_collapse: bool = False
    probe: str = "?"


def _vseq_index(fname: str) -> int:
    m = re.search(r"Vseq0*(\d+)", os.path.basename(fname))
    return int(m.group(1)) if m else -1


def _voltage_from_name(fname: str) -> float:
    m = re.search(r"_(\d+(?:\.\d+)?)V_", os.path.basename(fname))
    return float(m.group(1)) if m else float("nan")


def load_frame(path: str) -> Frame:
    """Read one Imgdata .mat file. Raises if it has no B-mode image."""
    mat = sio.loadmat(path, squeeze_me=True, struct_as_record=False)
    I = mat["ImgData"]
    P = mat.get("P")
    names = set(I._fieldnames)

    if "Imb" not in names:
        raise KeyError(f"{os.path.basename(path)} has no ImgData.Imb "
                       f"(fields: {sorted(names)}); this is an xAM-only file")

    Imb = np.asarray(I.Imb, dtype=float)
    Xb = np.asarray(I.Xb, dtype=float).ravel()
    Zb = np.asarray(I.Zb, dtype=float).ravel()
    Imx = Xx = Zx = None
    if "Imx" in names:
        Imx = np.asarray(I.Imx, dtype=float)
        Xx = np.asarray(I.Xx, dtype=float).ravel()
        Zx = np.asarray(I.Zx, dtype=float).ravel()

    idx = _vseq_index(path)
    volt = float("nan")
    post = False
    probe = "?"
    if P is not None:
        vseq = np.atleast_1d(np.asarray(getattr(P, "Vseq", []), dtype=float)).ravel()
        seed = np.atleast_1d(np.asarray(getattr(P, "seed", []), dtype=float)).ravel()
        if 1 <= idx <= len(vseq):
            volt = float(vseq[idx - 1])
        elif hasattr(P, "hv"):
            volt = float(np.asarray(P.hv).ravel()[0])
        post = len(seed) > 0 and idx > len(seed)
        pitch = getattr(P, "pitchSI", None)
        if pitch is not None:
            pitch = float(np.asarray(pitch).ravel()[0])
            probe = "L22" if abs(pitch - 100e-6) < 5e-6 else \
                    "GE" if abs(pitch - 135e-6) < 5e-6 else f"pitch {pitch*1e6:.0f}um"
    if math.isnan(volt):
        volt = _voltage_from_name(path)

    return Frame(path, idx, volt, Imb, Xb, Zb, Imx, Xx, Zx, post, probe)


def frame_files(folder: str) -> List[str]:
    files = glob.glob(os.path.join(folder, "Imgdata_*.mat"))
    return sorted(files, key=_vseq_index)


def to_db(im: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(np.abs(im), FLOOR))


# ------------------------------------------------------------------ discovery
@dataclass
class Scan:
    name: str
    folder: str
    files: List[str]
    roi_path: Optional[str] = None


def _scan_name(folder: str) -> str:
    base = os.path.basename(folder.rstrip(os.sep))
    # plate_P_1_1_A01 -> A01 ; otherwise keep the folder name
    m = re.match(r"plate_P_\d+_\d+_([A-H]\d{2})$", base)
    return m.group(1) if m else base


def _roi_for(scan_folder: str, scan_base: str) -> Optional[str]:
    """Find the ROI JSON the pipelines would have written for this scan."""
    parent = os.path.dirname(scan_folder.rstrip(os.sep))
    candidates = []
    # plate layouts: <plate>/roi/<scan>_rois.json, <plate>/roi/shared_rois.json
    for up in (parent, os.path.dirname(parent)):
        candidates.append(os.path.join(up, "roi", f"{scan_base}_rois.json"))
        candidates.append(os.path.join(up, "roi", "shared_rois.json"))
    # manual / in-vivo layouts: <run>/Processed-Data/<scan>_roi/rois.json,
    # <run>/Processed-Data/shared_rois.json (and the sibling Processed-Data
    # folder that lives next to the raw run folder)
    for up in (parent, os.path.dirname(parent)):
        pd_dirs = [os.path.join(up, "Processed-Data")]
        pd_dirs += glob.glob(os.path.join(up, "Processed-Data", "*"))
        for pdd in pd_dirs:
            candidates.append(os.path.join(pdd, f"{scan_base}_roi", "rois.json"))
            candidates.append(os.path.join(pdd, "shared_rois.json"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def discover(path: str) -> Tuple[str, List[Scan]]:
    """Return (kind, scans). kind in {file, scan, plate, session}."""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(path):
        return "file", [Scan(os.path.splitext(os.path.basename(path))[0],
                             os.path.dirname(path), [path],
                             _roi_for(os.path.dirname(path),
                                      os.path.basename(os.path.dirname(path))))]
    if not os.path.isdir(path):
        sys.exit(f"not found: {path}")

    files = frame_files(path)
    if files:
        base = os.path.basename(path.rstrip(os.sep))
        return "scan", [Scan(_scan_name(path), path, files, _roi_for(path, base))]

    # run folder that contains plate/
    if os.path.isdir(os.path.join(path, "plate")) and \
            glob.glob(os.path.join(path, "plate", "plate_P_*")):
        path = os.path.join(path, "plate")

    scans: List[Scan] = []
    plate_groups = sorted(glob.glob(os.path.join(path, "plate_P_*")))
    if plate_groups:
        for g in plate_groups:
            for d in sorted(glob.glob(os.path.join(g, "plate_P_*_*"))):
                f = frame_files(d)
                if f:
                    scans.append(Scan(_scan_name(d), d, f,
                                      _roi_for(d, os.path.basename(d))))
        return "plate", scans

    # session: any depth-1 subfolder with Imgdata files
    for d in sorted(glob.glob(os.path.join(path, "*"))):
        if os.path.isdir(d):
            f = frame_files(d)
            if f:
                scans.append(Scan(_scan_name(d), d, f,
                                  _roi_for(d, os.path.basename(d))))
    if not scans:
        sys.exit(f"no Imgdata_*.mat files found under {path}")
    return "session", scans


# ------------------------------------------------------------------ selection
def pick_frames(files: Sequence[str], voltage: Optional[float],
                frame: Optional[int], all_frames: bool,
                include_post: bool) -> List[Frame]:
    """Load the frames the user asked for.

    Default: every pre-collapse frame acquired at the same voltage as the
    first frame, averaged -- the sample as it looked at the start of the run.
    """
    if frame is not None:
        for f in files:
            if _vseq_index(f) == frame:
                return [load_frame(f)]
        sys.exit(f"no frame with Vseq index {frame} in {os.path.dirname(files[0])}")

    frames = [load_frame(f) for f in files]
    if not include_post:
        pre = [fr for fr in frames if not fr.post_collapse]
        frames = pre or frames
    if all_frames:
        return frames

    volts = sorted({fr.voltage for fr in frames if not math.isnan(fr.voltage)})
    if voltage is None:
        voltage = frames[0].voltage
    sel = [fr for fr in frames if abs(fr.voltage - voltage) < 0.051]
    if not sel:
        sys.exit(f"no frames at {voltage} V; voltages present: {volts}")
    return sel


def mean_frame(frames: Sequence[Frame]) -> Frame:
    """Average the linear images of several frames on the same grid."""
    if len(frames) == 1:
        return frames[0]
    f0 = frames[0]
    Imb = np.mean([fr.Imb for fr in frames], axis=0)
    Imx = None
    if all(fr.Imx is not None for fr in frames):
        Imx = np.mean([fr.Imx for fr in frames], axis=0)
    return Frame(f0.path, f0.vseq_idx, f0.voltage, Imb, f0.Xb, f0.Zb,
                 Imx, f0.Xx, f0.Zx, f0.post_collapse, f0.probe)


# ------------------------------------------------------------------ rendering
def _extent(X: np.ndarray, Z: np.ndarray) -> Tuple[float, float, float, float]:
    return (float(X[0]), float(X[-1]), float(Z[-1]), float(Z[0]))


def draw_rois(ax, roi_path: str, color=fs.OVERLAY["sample"]):
    with open(roi_path, encoding="utf-8") as fh:
        rois = json.load(fh)
    for label, r in rois.items():
        if not isinstance(r, dict):
            continue
        # figstyle.OVERLAY — the same outline colours as every LabSerf image.
        c = fs.OVERLAY.get(label.lower(), color) if label.lower() in ("noise", "ceiling") else color
        if {"x_min", "x_max", "z_min", "z_max"} <= set(r):
            ax.add_patch(Rectangle((r["x_min"], r["z_min"]),
                                   r["x_max"] - r["x_min"], r["z_max"] - r["z_min"],
                                   fill=False, ec=c, lw=0.5))
            ax.text(r["x_min"], r["z_min"] - 0.15, label, color=c, fontsize=8,
                    va="bottom", ha="left", clip_on=True)
        elif {"x", "z", "r"} <= set(r) or {"cx", "cz", "radius"} <= set(r):
            cx = r.get("x", r.get("cx")); cz = r.get("z", r.get("cz"))
            rad = r.get("r", r.get("radius"))
            ax.add_patch(Circle((cx, cz), rad, fill=False, ec=c, lw=0.5))
            ax.text(cx, cz - rad - 0.15, label, color=c, fontsize=8,
                    va="bottom", ha="center", clip_on=True)


def render(ax, fr: Frame, vmax: float, dr: float, depth: Optional[Tuple[float, float]],
           overlay_xam: bool, xam_dr: float, roi_path: Optional[str],
           title: str, cmap: str = "gray"):
    db = to_db(fr.Imb)
    im = ax.imshow(db, extent=_extent(fr.Xb, fr.Zb), cmap=cmap,
                   vmin=vmax - dr, vmax=vmax, aspect="equal",
                   interpolation="nearest")
    if overlay_xam and fr.Imx is not None:
        xdb = to_db(fr.Imx)
        xmax = float(np.nanpercentile(xdb, 99.5))
        # most xAM pixels are noise floor; only show what clears it clearly
        xfloor = float(np.nanmedian(xdb))
        xmin = max(xmax - xam_dr, xfloor + XAM_ABOVE_FLOOR_DB)
        masked = np.ma.masked_less(xdb, xmin)
        ax.imshow(masked, extent=_extent(fr.Xx, fr.Zx), cmap="hot",
                  vmin=xmin, vmax=xmax, alpha=0.8,
                  aspect="equal", interpolation="nearest")
    if roi_path:
        draw_rois(ax, roi_path)
    if depth:
        ax.set_ylim(depth[1], depth[0])
    else:
        ax.set_ylim(float(fr.Zb[-1]), float(fr.Zb[0]))
    ax.set_xlim(float(fr.Xb[0]), float(fr.Xb[-1]))
    ax.set_xlabel("Lateral (mm)")
    ax.set_ylabel("Depth (mm)")
    ax.set_title(title, fontsize=8)
    ax.grid(False)
    return im


def frame_label(fr: Frame, n_avg: int = 1) -> str:
    v = f"{fr.voltage:g} V" if not math.isnan(fr.voltage) else "? V"
    s = f"{v}"
    if n_avg > 1:
        s += f", mean of {n_avg}"
    else:
        s += f", frame {fr.vseq_idx}"
    if fr.post_collapse:
        s += " (post-collapse)"
    return s


def global_vmax(frames: Sequence[Frame], pct: float) -> float:
    return float(max(np.nanpercentile(to_db(fr.Imb), pct) for fr in frames))


# -------------------------------------------------------------------- outputs
def save_single(fr: Frame, out_png: str, **kw):
    fig, ax = fs.figure(88, 95)
    im = render(ax, fr, **kw)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03, label="B-mode (dB)")
    fs.save_png(fig, out_png)


def save_montage(items: List[Tuple[str, Frame]], out_png: str, ncols: int,
                 suptitle: str, **kw):
    n = len(items)
    ncols = max(1, min(ncols, n))
    nrows = math.ceil(n / ncols)
    pw = (fs.DOUBLE_COLUMN - 12) / ncols          # fit a double column
    fig, axes = fs.grid(nrows, ncols, pw * ncols, pw * 1.2 * nrows + 12,
                        squeeze=False, constrained_layout=True)
    im = None
    for k, ax in enumerate(axes.ravel()):
        if k >= n:
            ax.axis("off")
            continue
        title, fr = items[k]
        # long scan names (in-vivo timepoints) are wrapped so panels don't collide
        title = "\n".join(textwrap.fill(t, 30) for t in title.split("\n"))
        im = render(ax, fr, title=title, **kw)
        if k % ncols:
            ax.set_ylabel("")
        if k < n - ncols:
            ax.set_xlabel("")
    if im is not None:
        fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.5, pad=0.01,
                     label="B-mode (dB)")
    fig.suptitle(suptitle, fontsize=8)
    fs.save_png(fig, out_png)


def save_video(frames: List[Frame], out_path: str, fps: int, **kw):
    from matplotlib import animation
    fig, ax = fs.figure(88, 95)
    im = render(ax, frames[0], title=frame_label(frames[0]), **kw)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03, label="B-mode (dB)")
    fig.tight_layout()

    def update(i):
        im.set_data(to_db(frames[i].Imb))
        ax.set_title(frame_label(frames[i]), fontsize=8)
        return [im]

    anim = animation.FuncAnimation(fig, update, frames=len(frames), blit=False)
    if animation.writers.is_available("ffmpeg"):
        anim.save(out_path, writer="ffmpeg", fps=fps, dpi=150)
    else:
        out_path = os.path.splitext(out_path)[0] + ".gif"
        anim.save(out_path, writer="pillow", fps=fps, dpi=110)
        print("  ffmpeg not found; wrote GIF instead")
    plt.close(fig)
    return out_path


def show_interactive(frames: List[Frame], roi_path: Optional[str], title: str, **kw):
    from matplotlib.widgets import Slider
    fig, ax = fs.figure(150, 170)   # on-screen viewer, not a print figure
    fig.subplots_adjust(bottom=0.16)
    im = render(ax, frames[0], roi_path=roi_path,
                title=f"{title}\n{frame_label(frames[0])}", **kw)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03, label="B-mode (dB)")
    if len(frames) > 1:
        sax = fig.add_axes([0.15, 0.05, 0.7, 0.03])
        sl = Slider(sax, "frame", 0, len(frames) - 1, valinit=0, valstep=1)

        def on_change(val):
            i = int(val)
            im.set_data(to_db(frames[i].Imb))
            ax.set_title(f"{title}\n{frame_label(frames[i])}", fontsize=8)
            fig.canvas.draw_idle()
        sl.on_changed(on_change)
    plt.show()


# ----------------------------------------------------------------------- main
def parse_depth(s: Optional[str]) -> Optional[Tuple[float, float]]:
    if not s:
        return None
    a, b = (float(v) for v in s.split(","))
    return (min(a, b), max(a, b))


def main(argv: Optional[Sequence[str]] = None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="Imgdata .mat file, scan folder, plate folder, "
                                 "run folder, or session folder")
    sel = ap.add_argument_group("frame selection (default: average the pre-collapse "
                                "frames at the same voltage as frame 1)")
    sel.add_argument("--voltage", type=float, help="use frames at this voltage (V)")
    sel.add_argument("--frame", type=int, help="use one frame by its Vseq index (1-based)")
    sel.add_argument("--all-frames", action="store_true",
                     help="render every frame (montage per scan; enables --video)")
    sel.add_argument("--include-post", action="store_true",
                     help="also consider post-collapse frames")
    sel.add_argument("--wells", help="comma list of scan/well names to keep, e.g. A01,B03")

    disp = ap.add_argument_group("display")
    disp.add_argument("--dr", type=float, default=50.0, help="dynamic range in dB (default 50)")
    disp.add_argument("--vmax", type=float,
                      help="fix the top of the grey scale in dB (default: percentile of data)")
    disp.add_argument("--vmax-pct", type=float, default=99.7,
                      help="percentile used for the automatic top of scale (default 99.7)")
    disp.add_argument("--norm", choices=["global", "frame"], default="global",
                      help="global: one grey scale for every image in this call "
                           "(comparable); frame: each image scaled to itself")
    disp.add_argument("--depth", help="depth window to show, mm, e.g. 2,8")
    disp.add_argument("--cmap", default="gray")
    disp.add_argument("--rois", action="store_true",
                      help="draw the saved analysis ROIs if a rois.json is found")
    disp.add_argument("--overlay-xam", action="store_true",
                      help="overlay the xAM image (hot) on the B-mode")
    disp.add_argument("--xam-dr", type=float, default=25.0,
                      help="dynamic range of the xAM overlay in dB (default 25)")
    disp.add_argument("--ncols", type=int, default=6, help="columns in contact sheets")

    outg = ap.add_argument_group("output")
    outg.add_argument("--out", help="output folder (default <input>/bmode_view)")
    outg.add_argument("--video", action="store_true",
                      help="with --all-frames: also write an mp4 per scan")
    outg.add_argument("--fps", type=int, default=5)
    outg.add_argument("--show", action="store_true",
                      help="open an interactive window (single scan; frame slider)")
    a = ap.parse_args(argv)

    if not a.show:
        matplotlib.use("Agg")
    fs.use()

    kind, scans = discover(a.path)
    if a.wells:
        keep = {w.strip() for w in a.wells.split(",") if w.strip()}
        scans = [s for s in scans if s.name in keep or
                 os.path.basename(s.folder) in keep]
        if not scans:
            sys.exit(f"none of {sorted(keep)} found")

    root = os.path.abspath(os.path.expanduser(a.path))
    if kind == "file":
        root = os.path.dirname(root)
    elif kind == "plate" and os.path.basename(root) != "plate" and \
            os.path.isdir(os.path.join(root, "plate")):
        root = os.path.join(root, "plate")
    out = a.out or os.path.join(root, "bmode_view")
    depth = parse_depth(a.depth)

    print(f"{kind}: {len(scans)} scan(s) under {root}")

    # load everything first so a global grey scale can be computed
    loaded: List[Tuple[Scan, List[Frame]]] = []
    for s in scans:
        frs = pick_frames(s.files, a.voltage, a.frame, a.all_frames, a.include_post)
        loaded.append((s, frs))
    probe = loaded[0][1][0].probe
    n_files = sum(len(s.files) for s in scans)
    print(f"probe {probe}; {n_files} frames on disk; "
          f"{sum(len(f) for _, f in loaded)} selected")

    if a.show:
        s, frs = loaded[0]
        if len(loaded) > 1:
            print(f"--show uses the first scan only ({s.name}); "
                  f"use --wells to pick another")
        vmax = a.vmax if a.vmax is not None else global_vmax(frs, a.vmax_pct)
        if not a.all_frames and a.frame is None:
            frs = [mean_frame(frs)]
        show_interactive(frs, s.roi_path if a.rois else None, s.name,
                         vmax=vmax, dr=a.dr, depth=depth, overlay_xam=a.overlay_xam,
                         xam_dr=a.xam_dr, cmap=a.cmap)
        return

    os.makedirs(out, exist_ok=True)
    render_frames: List[Tuple[Scan, Frame, int]] = []   # (scan, frame, n_avg)
    for s, frs in loaded:
        if a.all_frames:
            for fr in frs:
                render_frames.append((s, fr, 1))
        else:
            render_frames.append((s, mean_frame(frs), len(frs)))

    if a.vmax is not None:
        vmax_global = a.vmax
    else:
        vmax_global = global_vmax([fr for _, fr, _ in render_frames], a.vmax_pct)

    def vmax_for(fr: Frame) -> float:
        return vmax_global if a.norm == "global" else \
            float(np.nanpercentile(to_db(fr.Imb), a.vmax_pct))

    common = dict(dr=a.dr, depth=depth, overlay_xam=a.overlay_xam,
                  xam_dr=a.xam_dr, cmap=a.cmap)

    written: List[str] = []
    if a.all_frames:
        for s, frs in loaded:
            items = [(frame_label(fr), fr) for fr in frs]
            png = os.path.join(out, f"{s.name}_frames.png")
            save_montage(items, png, a.ncols, f"{s.name} — B-mode, all frames",
                         vmax=vmax_for(frs[0]), roi_path=s.roi_path if a.rois else None,
                         **common)
            written.append(png)
            if a.video:
                vid = save_video(frs, os.path.join(out, f"{s.name}_bmode.mp4"),
                                 a.fps, vmax=vmax_for(frs[0]),
                                 roi_path=s.roi_path if a.rois else None,
                                 depth=depth, overlay_xam=False, xam_dr=a.xam_dr,
                                 dr=a.dr, cmap=a.cmap)
                written.append(vid)
    else:
        items = []
        for s, fr, n in render_frames:
            title = f"{s.name}\n{frame_label(fr, n)}"
            png = os.path.join(out, f"{s.name}_bmode.png")
            save_single(fr, png, vmax=vmax_for(fr), title=title,
                        roi_path=s.roi_path if a.rois else None, **common)
            written.append(png)
            items.append((title, fr))
        if len(items) > 1:
            sheet = os.path.join(out, "bmode_contact_sheet.png")
            # contact sheet uses the global scale so panels are comparable
            save_montage(items, sheet, a.ncols,
                         f"{os.path.basename(root)} — B-mode ({probe}, "
                         f"{a.dr:g} dB range, top {vmax_global:.1f} dB)",
                         vmax=vmax_global, roi_path=None, **common)
            written.append(sheet)

    print(f"wrote {len(written)} file(s) to {out}")
    for w in written[-3:]:
        print("  " + os.path.relpath(w, os.getcwd()))
    rois_found = sum(1 for s in scans if s.roi_path)
    if a.rois and rois_found < len(scans):
        print(f"note: ROI json found for {rois_found}/{len(scans)} scans")


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
