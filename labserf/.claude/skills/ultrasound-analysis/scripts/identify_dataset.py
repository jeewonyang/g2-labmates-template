#!/usr/bin/env python3
"""
identify_dataset.py — classify an ultrasound acquisition folder and recommend a pipeline.

Reads only metadata (P struct / UF struct / file naming), never loads full image
stacks, so it is fast even on multi-GB trees.

What it detects
---------------
  acquisition mode : xAM_ramp | xAM_timecourse | BURST | Doppler | mixed | unknown
  probe            : L22-14vX | GE624D | (inferred from P.pitchSI / P.numEle / UF.Probe)
  layout           : plate | flat | session (parent holding many acquisitions)
  collapse scheme  : none | full-match | partial-match
  and prints the us_proc / BURST / Doppler command to run.

Usage
-----
    python identify_dataset.py /path/to/data_folder
    python identify_dataset.py /path/to/data_folder --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- constants

# Probe fingerprints. pitchSI is the single most reliable discriminator:
# L22-14vX = 100 um, GE6-24D = 135 um.
PROBE_BY_PITCH_UM = {100: "L22-14vX", 135: "GE624D"}

AUTO_ROI = str(Path(__file__).resolve().parent / "auto_roi.py")

VSEQ_RE = re.compile(r"Vseq0*(\d+)", re.IGNORECASE)
BLOCK_RE = re.compile(r"image_block_(\d+)\.mat$", re.IGNORECASE)
WELL_DIR_RE = re.compile(r"_([A-Ha-h]\d{1,2})$")
OUTPUT_DIRS = {
    "processed_csv", "fig", "figs", "roi", "images", "videos", "quant",
    "proc", "plot", "heatmaps", "Processed-Data", "output", "overlays",
}


# ---------------------------------------------------------------- mat helpers

def _first(v, default=np.nan):
    """First scalar of a scipy-loaded MATLAB field."""
    try:
        a = np.atleast_1d(v).flatten()
        return a[0] if a.size else default
    except Exception:
        return default


def _mat_str(raw) -> str:
    """MATLAB char / cell / string field -> python str.

    MATLAB `string` objects (as opposed to char arrays) are saved as opaque MCOS
    handles that scipy cannot resolve; those come back as a MatlabOpaque record
    and are reported as empty rather than as their raw byte soup.
    """
    try:
        raw = np.squeeze(raw)
        if raw.dtype.names and "s0" in raw.dtype.names:
            return ""          # MatlabOpaque record: unresolvable MATLAB string object
        if raw.ndim == 0:
            item = raw.item()
            return _mat_str(item) if isinstance(item, np.ndarray) else str(item)
        if raw.dtype.kind in ("U", "S"):
            return "".join(raw.flatten().astype(str))
        if raw.dtype == object and raw.size:
            return _mat_str(raw.flat[0])
        return str(raw)
    except Exception:
        return ""


def read_p_struct(mat_path: str) -> dict:
    """Read the P struct from an Imgdata_*.mat (v7 or v7.3). Returns {} on failure."""
    import scipy.io

    try:
        mat = scipy.io.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
        P = mat.get("P")
        if P is None or not hasattr(P, "_fieldnames"):
            return {}
        out = {f: getattr(P, f) for f in P._fieldnames}
        out["_top_keys"] = [k for k in mat if not k.startswith("__")]
        return out
    except NotImplementedError:
        pass
    except Exception:
        return {}

    # v7.3 / HDF5 (BURST image_block files)
    try:
        import h5py

        with h5py.File(mat_path, "r") as f:
            out = {"_top_keys": [k for k in f.keys() if not k.startswith("#")]}
            if "P" in f:
                for k in f["P"]:
                    try:
                        v = np.array(f["P"][k][()])
                        if v.dtype in (np.uint16, np.uint32) and v.size > 1:
                            out[k] = "".join(chr(int(c)) for c in v.flatten() if int(c))
                        else:
                            out[k] = v
                    except Exception:
                        pass
            return out
    except Exception:
        return {}


def read_uf_struct(uf_path: str) -> dict:
    import scipy.io

    try:
        UF = scipy.io.loadmat(uf_path, squeeze_me=True, struct_as_record=False)["UF"]
        return {f: getattr(UF, f) for f in UF._fieldnames}
    except Exception:
        return {}


# ---------------------------------------------------------------- probe ID

def identify_probe(P: dict) -> tuple[str, str]:
    """Return (probe_name, evidence)."""
    if "probe" in P:
        name = _mat_str(P["probe"]).strip()
        if name:
            return name, "P.probe"

    pitch = _first(P.get("pitchSI"), np.nan)
    if np.isfinite(pitch):
        um = int(round(float(pitch) * 1e6))
        if um in PROBE_BY_PITCH_UM:
            return PROBE_BY_PITCH_UM[um], f"P.pitchSI = {um} um"

    n_ele = _first(P.get("numEle"), np.nan)
    if np.isfinite(n_ele) and int(n_ele) == 192:
        return "GE624D", "P.numEle = 192"

    n_rays = _first(P.get("numRays"), np.nan)
    if np.isfinite(n_rays):
        if int(n_rays) == 64:
            return "L22-14vX", "P.numRays = 64"
        if int(n_rays) > 100:
            return "GE624D", f"P.numRays = {int(n_rays)}"

    return "unknown", "no probe fingerprint found"


# ---------------------------------------------------------------- folder scan

def scan_folder(folder: Path) -> dict:
    """Classify a single leaf acquisition folder."""
    try:
        # Drop macOS AppleDouble sidecars (`._Imgdata_Vseq...mat`): VSEQ_RE
        # searches, so they would otherwise count as acquisitions.
        names = sorted(n for n in os.listdir(folder) if not n.startswith("._"))
    except OSError:
        return {"kind": "unreadable", "path": str(folder)}

    imgdata = [n for n in names if n.lower().endswith(".mat") and VSEQ_RE.search(n)]
    blocks = [n for n in names if BLOCK_RE.search(n)]
    bins = [n for n in names if n.lower().startswith("fus_block_") and n.lower().endswith(".bin")]

    info: dict = {"path": str(folder), "name": folder.name}

    # ---- Doppler / fUS
    if bins or ("Dop.mat" in names and "UF.mat" in names):
        UF = read_uf_struct(str(folder / "UF.mat")) if "UF.mat" in names else {}
        probe = _mat_str(UF.get("Probe", "")).strip() or "unknown"
        n_blocks = int(_first(UF.get("NbOfBlocs"), len(bins) or np.nan)) if UF else len(bins)
        lat = 384 if probe.startswith("GE") else 128 if probe.startswith("L22") else None
        info.update(
            kind="Doppler",
            probe=probe,
            probe_evidence="UF.Probe",
            n_blocks=n_blocks,
            n_frames_per_block=int(_first(UF.get("numFrames"), np.nan)) if UF else None,
            depth_mm=[float(x) for x in np.atleast_1d(UF.get("Depth", []))] if UF else None,
            img_voltage=float(_first(UF.get("ImgVoltage"), np.nan)) if UF else None,
            lambda_mm=float(_first(UF.get("Lambda"), np.nan)) if UF else None,
            lat_resol=lat,
            dop_present="Dop.mat" in names,
            n_bin_files=len(bins),
        )
        return info

    # ---- BURST
    if blocks:
        P = read_p_struct(str(folder / blocks[0]))
        probe, ev = identify_probe(P)
        info.update(
            kind="BURST",
            probe=probe,
            probe_evidence=ev,
            n_frames=len(blocks),
            n_pre=int(_first(P.get("numPreColFrames"), np.nan)),
            n_collapse=int(_first(P.get("numColFrames"), np.nan)),
            n_post=int(_first(P.get("numPostColFrames"), np.nan)),
            tx_freq_MHz=float(_first(P.get("fSI"), np.nan)) / 1e6 if "fSI" in P else None,
            depth_mm=[float(_first(P.get("startDepth_mm"), np.nan)),
                      float(_first(P.get("endDepth_mm"), np.nan))],
            notes=_mat_str(P.get("saveDirName", "")),
        )
        return info

    # ---- xAM / B-mode Imgdata
    if imgdata:
        P = read_p_struct(str(folder / imgdata[0]))
        probe, ev = identify_probe(P)
        seed = np.atleast_1d(P.get("seed", [])).astype(float).flatten()
        vseq = np.atleast_1d(P.get("Vseq", [])).astype(float).flatten()
        n_pre, n_total = len(seed), len(vseq)
        post = vseq[n_pre:] if n_total > n_pre else np.array([])

        pre_v = np.unique(seed) if n_pre else np.array([])
        post_v = np.unique(post)
        if post.size == 0:
            collapse = "none"
        elif set(np.round(pre_v, 3)) <= set(np.round(post_v, 3)):
            collapse = "full-match"
        else:
            collapse = "partial-match"

        reps = (n_pre / len(pre_v)) if len(pre_v) else np.nan
        # Same voltage repeated for every frame => timecourse, not a ramp.
        measurement = "xAM_timecourse" if len(pre_v) <= 1 else "xAM_ramp"

        info.update(
            kind=measurement,
            probe=probe,
            probe_evidence=ev,
            n_files=len(imgdata),
            n_pre=n_pre,
            n_post=n_total - n_pre,
            collapse=collapse,
            voltages=[float(v) for v in pre_v],
            post_voltages=[float(v) for v in np.unique(post)],
            frames_per_voltage=float(reps) if np.isfinite(reps) else None,
            code=_mat_str(P.get("code", "")),
            pulse_shape=_mat_str(P.get("pulseShape", "")),
            tx_freq_MHz=float(_first(P.get("txFreq"), np.nan)),
            angle_deg=float(_first(P.get("alpha"), np.nan)),
            aperture=float(_first(P.get("Xap"), np.nan)),
            num_accum=float(_first(P.get("numAccum"), np.nan)),
            depth_mm=[float(_first(P.get("startDepth_mm"), np.nan)),
                      float(_first(P.get("endDepth_mm"), np.nan))],
            notes=_mat_str(P.get("notes", "")).strip(),
        )
        return info

    info["kind"] = "no-data"
    return info


def find_well_folders(plate_dir: Path) -> list[tuple[Path, str]]:
    """plate/ -> plate_P_X_Y/ -> plate_P_X_Y_A01/*.mat"""
    out = []
    for group in sorted(plate_dir.iterdir()):
        if not group.is_dir() or group.name in OUTPUT_DIRS:
            continue
        for wf in sorted(group.iterdir()):
            if not wf.is_dir():
                continue
            m = WELL_DIR_RE.search(wf.name)
            if m and any(p.suffix.lower() == ".mat" and not p.name.startswith("._")
                         for p in wf.iterdir()):
                out.append((wf, m.group(1).upper()))
    return out


def find_companions(root: Path) -> dict:
    """Locate the metadata CSV, GE well map, and Doppler folder near an acquisition.

    Searches the acquisition root and up to three ancestors, since these files are
    normally kept beside the date/session folder rather than inside the plate tree.
    """
    out: dict = {"metadata_csv": None, "well_map": None, "doppler_dirs": []}
    searched = [root] + list(root.parents)[:3]

    for base in searched:
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_dir() and p.name.lower() == "doppler":
                subs = [d for d in sorted(p.iterdir())
                        if d.is_dir() and (d / "UF.mat").exists()]
                out["doppler_dirs"].extend(str(d) for d in (subs or [p]))
            if p.suffix.lower() != ".csv" or p.name.startswith("._"):
                continue
            head = ""
            try:
                head = p.open(encoding="utf-8-sig", errors="ignore").readline().lower()
            except OSError:
                continue
            cols = [c.strip() for c in head.split(",")]
            if "acoustic_plate_reader_well" in cols and out["well_map"] is None:
                out["well_map"] = str(p)
            elif "well" in cols and "sample" in cols and out["metadata_csv"] is None:
                out["metadata_csv"] = str(p)
        if out["metadata_csv"] and (out["well_map"] or out["doppler_dirs"]):
            break
    return out


def classify(root: Path) -> dict:
    """Classify root: a leaf acquisition, a plate tree, or a session of many folders."""
    root = root.resolve()
    companions = find_companions(root)

    # -- plate tree? (a 'plate' dir here, or root IS the plate dir)
    plate_dir = None
    if (root / "plate").is_dir():
        plate_dir = root / "plate"
    elif root.name.startswith("plate") or any(
        d.is_dir() and d.name.startswith("plate_P_") for d in root.iterdir() if d.is_dir()
    ):
        plate_dir = root

    if plate_dir is not None:
        wells = find_well_folders(plate_dir)
        if wells:
            # P.Vseq / P.seed are per-acquisition and can differ between wells of
            # the same plate (an aborted or re-run position, a changed ramp). Scan
            # every folder rather than trusting the first, and surface the variants
            # so blank correction is never assumed to be uniform.
            per_well = [(wid, scan_folder(wf)) for wf, wid in wells]
            first = per_well[0][1]
            variants = {}
            for wid, rec in per_well:
                key = (rec.get("n_pre"), rec.get("n_post"), rec.get("collapse"),
                       tuple(rec.get("voltages") or ()))
                variants.setdefault(key, []).append(wid)
            probe = first.get("probe", "unknown")
            n_rois = 3 if probe.startswith("GE") else 1
            return {
                "layout": "plate",
                "companions": companions,
                "vseq_variants": [
                    {"n_pre": k[0], "n_post": k[1], "collapse": k[2],
                     "voltages": list(k[3]), "n_wells": len(v),
                     "wells": v if len(v) <= 12 else v[:12] + ["..."]}
                    for k, v in sorted(variants.items(), key=lambda kv: -len(kv[1]))
                ],
                "vseq_uniform": len(variants) == 1,
                "plate_dir": str(plate_dir),
                "probe": probe,
                "probe_evidence": first.get("probe_evidence"),
                "n_scan_positions": len(wells),
                "wells_per_position": n_rois,
                "n_physical_wells": len(wells) * n_rois,
                "scan_ids": [w[1] for w in wells],
                "representative": first,
                "us_proc_mode": "plate_ge" if probe.startswith("GE") else "plate_l22",
            }

    # -- leaf acquisition?
    leaf = scan_folder(root)
    if leaf.get("kind") not in ("no-data", "unreadable"):
        return {"layout": "flat", "companions": companions, "representative": leaf,
                "probe": leaf.get("probe"), "acquisitions": [leaf]}

    # -- session: recurse one or two levels and group
    acqs = []
    for child in sorted(root.rglob("*")):
        if not child.is_dir() or child.name in OUTPUT_DIRS:
            continue
        if any(part in OUTPUT_DIRS for part in child.relative_to(root).parts[:-1]):
            continue
        rec = scan_folder(child)
        if rec.get("kind") not in ("no-data", "unreadable"):
            acqs.append(rec)
    if acqs:
        probes = {a.get("probe") for a in acqs if a.get("probe") not in (None, "unknown")}
        return {
            "layout": "session",
            "companions": companions,
            "probe": probes.pop() if len(probes) == 1 else sorted(probes),
            "n_acquisitions": len(acqs),
            "kinds": {k: sum(1 for a in acqs if a["kind"] == k)
                      for k in sorted({a["kind"] for a in acqs})},
            "acquisitions": acqs,
        }

    # -- legacy MATLAB output only (no raw frames survive in these folders)
    legacy = sorted(root.rglob("data_*.mat")) + sorted(root.rglob("rawSBR*.csv"))
    if legacy:
        return {
            "layout": "legacy-output",
            "companions": companions,
            "path": str(root),
            "files": [str(p.relative_to(root)) for p in legacy[:12]],
            "note": (
                "Output of the legacy MATLAB LiveX pipeline "
                "(DataExactor_LiveX_timecourse_opto_v4.m / RegUSImageProc_ZJ_v3.m). "
                "No raw Imgdata_*.mat here — the quantities are already extracted. "
                "Legacy CNR uses noise_std alone as the denominator, so it is not "
                "comparable to us_proc CNR (see references/metrics.md)."
            ),
        }

    return {"layout": "unknown", "path": str(root)}


# ---------------------------------------------------------------- reporting

def recommend(result: dict, root: Path, scripts_dir: str = "Scripts") -> list[str]:
    """Recommended commands, most specific first."""
    us_proc = f"python {scripts_dir}/us_proc_v5_addBURST_colormap.py"
    comp = result.get("companions", {})
    meta = comp.get("metadata_csv") or "<metadata.csv>"
    wmap = comp.get("well_map") or "<well_map.csv>"
    dops = comp.get("doppler_dirs") or []
    cmds = []

    if result["layout"] == "plate":
        mode = result["us_proc_mode"]
        cmds.append(f'python {AUTO_ROI} "{result["plate_dir"]}" --mode {mode}'
                    '   # infers ROIs + writes roi/auto_roi_review.png — check it')
        line = f'{us_proc} {mode} --data_dir "{result["plate_dir"]}" --roi_per_well'
        if mode == "plate_ge":
            line += f' --well_map "{wmap}"'
        line += f' --metadata_csv "{meta}" --save_images <V> --xlsx'
        cmds.append(line)
        cmds.append(
            f'python {scripts_dir}/run_plate_compile_and_heatmaps.py '
            f'--plate-dir "{result["plate_dir"]}" --metadata "{meta}"'
        )
        return cmds

    if result["layout"] == "legacy-output":
        return [
            "Already processed by the legacy MATLAB pipeline — no raw frames here.",
            f'python {Path(__file__).parent}/to_prism.py '
            '"<rawSBR_processed.csv>" --metric y_signal --group sampleGroup',
        ]

    acqs = result.get("acquisitions") or [result.get("representative")]
    acqs = [a for a in acqs if a]
    kinds = {a["kind"] for a in acqs}

    if kinds & {"xAM_ramp", "xAM_timecourse"}:
        in_vivo = any(
            re.search(r"mouse|vivo|tumor|injection|imagingplane", str(a["path"]), re.I)
            for a in acqs
        )
        mode = "in_vivo" if in_vivo else "manual"
        target = acqs[0]["path"] if result["layout"] == "flat" else "<each acquisition folder>"
        line = f'{us_proc} {mode} --data_dir "{target}"'
        if mode == "in_vivo":
            dop = f'"{dops[0]}"' if dops else "<Doppler/...>"
            line += f' --doppler_dir {dop} --roi_labels tumor,contralateral'
        if any(a["kind"] == "xAM_timecourse" for a in acqs):
            line += " --plot_by_frame"
        line += " --save_images <V> --save_video --xlsx"
        if mode == "manual":
            cmds.append(f'python {AUTO_ROI} "{target}" --mode manual --n-rois 2'
                        '   # infers ROIs + review image')
        else:
            cmds.append("# in vivo: ROIs differ per animal — draw them once by hand, "
                        "then every timepoint reuses Processed-Data/shared_rois.json")
        cmds.append(line)

    if "BURST" in kinds:
        burst_root = next((a["path"] for a in acqs if a["kind"] == "BURST"), "<BURST folder>")
        cmds.append(f'python {AUTO_ROI} "{Path(burst_root).parent}" --mode burst --n-rois 2'
                    '   # infers ROIs + review image')
        cmds.append(
            f'python {scripts_dir}/US_processing/process_burst_acq.py '
            f'"<BURST folder>"  # note: process_burst_acq_v2.py has a syntax error'
        )

    if "Doppler" in kinds:
        cmds.append(
            "Doppler: run Scripts/Processing/Doppler_processing_JWY_bothProbes.m in MATLAB "
            "(writes Dop.mat), then pass the folder to us_proc in_vivo --doppler_dir"
        )

    return cmds or ["No matching pipeline — inspect manually."]


def describe(result: dict, root: Path) -> str:
    L = []
    ap = L.append
    ap(f"Root      : {root}")
    ap(f"Layout    : {result['layout']}")

    if result["layout"] == "plate":
        r = result["representative"]
        ap(f"Probe     : {result['probe']}  ({result['probe_evidence']})")
        ap(f"Positions : {result['n_scan_positions']} scan positions "
           f"x {result['wells_per_position']} well(s) = {result['n_physical_wells']} wells")
        ap(f"Scan IDs  : {result['scan_ids'][0]} .. {result['scan_ids'][-1]}")
        ap(f"Per well  : {r['n_files']} frames | {r['n_pre']} pre + {r['n_post']} post")
        ap(f"Voltages  : {r['voltages']}  ({r['frames_per_voltage']:.0f} frame(s)/V)")
        ap(f"Collapse  : {r['collapse']}   post V = {r['post_voltages']}")
        if result.get("vseq_uniform"):
            ap(f"Vseq      : identical across all {result['n_scan_positions']} positions")
        else:
            ap(f"Vseq      : *** {len(result['vseq_variants'])} DIFFERENT sequences on this plate ***")
            for v in result["vseq_variants"]:
                ap(f"   {v['n_wells']:>3} wells | {v['n_pre']} pre + {v['n_post']} post "
                   f"| {v['collapse']:<13} | {v['wells']}")
            ap("   us_proc reads P.Vseq per folder, so each is corrected on its own")
            ap("   terms — but group these separately before pooling replicates.")
        ap(f"Beam      : {r['pulse_shape']}/{r['code']} @ {r['tx_freq_MHz']} MHz, "
           f"{r['angle_deg']} deg, aperture {r['aperture']}, accum {r['num_accum']:.0f}")
        ap(f"Depth     : {r['depth_mm'][0]}–{r['depth_mm'][1]} mm")
        if r.get("notes"):
            ap(f"Notes     : {r['notes']}")

    elif result["layout"] == "flat":
        r = result["representative"]
        ap(f"Kind      : {r['kind']}")
        for k in ("probe", "n_files", "n_frames", "n_pre", "n_post", "collapse",
                  "voltages", "post_voltages", "frames_per_voltage", "tx_freq_MHz",
                  "angle_deg", "aperture", "num_accum", "depth_mm", "n_blocks",
                  "n_frames_per_block", "img_voltage", "lat_resol", "notes"):
            if r.get(k) not in (None, "", [], np.nan):
                ap(f"{k:<10}: {r[k]}")

    elif result["layout"] == "session":
        ap(f"Probe     : {result['probe']}")
        ap(f"Acquisitions: {result['n_acquisitions']}")
        for k, n in result["kinds"].items():
            ap(f"   {k:<16} {n}")
        for a in result["acquisitions"][:8]:
            extra = (f"{a.get('n_files', a.get('n_frames', a.get('n_blocks', '?')))} frames")
            ap(f"   - [{a['kind']:<15}] {Path(a['path']).name}  ({extra})")
        if result["n_acquisitions"] > 8:
            ap(f"   ... and {result['n_acquisitions'] - 8} more")

    elif result["layout"] == "legacy-output":
        ap(f"Note      : {result['note']}")
        for f in result["files"]:
            ap(f"   {f}")

    ap("")
    ap("Recommended:")
    for c in recommend(result, root):
        ap(f"  {c}")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    root = Path(args.folder)
    if not root.is_dir():
        sys.exit(f"Not a directory: {root}")

    result = classify(root)
    if args.json:
        result["recommended"] = recommend(result, root)
        print(json.dumps(result, indent=2, default=str))
    else:
        print(describe(result, root))


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
