"""report_lib.py — shared loaders for LabSerf per-run reports.

Every acquisition folder gets its own `AI_analysis/`. This module holds the
parts that are the same for all of them — path layout, result loading, pressure
calibration, image access, palette — so a run-specific report script only has to
carry the narrative and the figures that are actually unique to that run.

Nothing here hardcodes a run folder, and nothing here reads the reference
datasets — every path is derived from the run folder passed in.

    from report_lib import Run
    r = Run("/path/to/260827_CRE-PPV_772")
    d = r.pre()                       # pre-collapse rows, ramp voltages only
    X, Z, db = r.load_xam(scan, 12.0) # one averaged xAM frame, in dB
    mpa = r.pressure(12.0)            # peak positive pressure at that voltage
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

import numpy as np
import pandas as pd

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIB = os.path.join(SKILL, "calibration")

# Shared palette and matplotlib style. Both come from the figure-design skill so
# that every LabSerf figure — ultrasound, flow, anything added later — is drawn
# to the same lab rules (8 pt Arial, 0.5 pt lines, greys + one orange accent).
# The keys below are kept for any run-specific script that imports `C`; their
# values now resolve to the lab palette rather than a separate ultrasound one.
sys.path.insert(0, os.path.join(SKILL, "..", "figure-design", "scripts"))
import figstyle as fs  # noqa: E402

_ramp4 = fs.ramp(4)
C = {
    "dose0": _ramp4[0], "dose1": _ramp4[1], "dose2": _ramp4[2], "dose3": _ramp4[3],
    "red": fs.ACCENT, "green": fs.BLUE, "grey": fs.GREY, "blue": fs.BLUE,
    "violet": fs.GREY_DARK, "pink": fs.ACCENT_BRIGHT, "amber": fs.ACCENT,
    "teal": fs.BLUE, "ink": fs.INK, "mute": fs.GREY_DARK,
}
DOSE_COLORS = [C["dose0"], C["dose1"], C["dose2"], C["dose3"]]

# The lab style sheet as an rc dict, for callers that do
# `plt.rcParams.update(MPL_RC)`. New code should call `fs.use()` instead.
import matplotlib as _mpl  # noqa: E402
MPL_RC = dict(_mpl.rc_params_from_file(fs.STYLE, use_default_template=False))


# --------------------------------------------------------------- calibration
def pressure_table(probe="GE624D", mode="xAM", aperture=35,
                   freq_mhz=12.5, location_mm=5.0, metric="PPP_MPa"):
    """Voltage -> pressure lookup from the measured hydrophone calibrations.

    `location_mm` is numeric for the GE table and a string like "5mm" for the
    L22 table; both forms are accepted and matched loosely.
    """
    name = "GE624D_pressure_calibration.csv" if "GE" in probe.upper() \
        else "L22_L10_pressure_calibration.csv"
    d = pd.read_csv(os.path.join(CALIB, name))
    d = d[d.probe.astype(str).str.contains(str(probe), case=False, na=False)]
    if mode is not None:
        d = d[d.Mode.astype(str).str.fullmatch(str(mode), case=False, na=False)]
    for col, val in (("Aperture", aperture), ("TxFrequency_MHz", freq_mhz)):
        if val is not None and col in d and d[col].notna().any():
            d = d[np.isclose(d[col].astype(float), float(val))]
    if location_mm is not None and "Location_mm" in d:
        want = re.sub(r"[^0-9.]", "", str(location_mm))
        d = d[d.Location_mm.astype(str).str.replace(r"[^0-9.]", "", regex=True) == want]
    if d.empty:
        raise LookupError(f"no calibration rows for {probe}/{mode}/ap{aperture}/"
                          f"{freq_mhz}MHz/{location_mm}")
    return dict(zip(d.Voltage_V.astype(float), d[metric].astype(float)))


# --------------------------------------------------------------------- run
class Run:
    """One acquisition folder, with its standard sub-paths and loaders."""

    def __init__(self, run_dir, plate_sub="plate", ramp_min_v=6.0, calib=None):
        self.dir = os.path.abspath(os.path.expanduser(run_dir))
        if not os.path.isdir(self.dir):
            raise FileNotFoundError(self.dir)
        self.name = os.path.basename(self.dir)
        self.plate = os.path.join(self.dir, plate_sub)
        self.csv_dir = os.path.join(self.plate, "processed_csv")
        self.roi_dir = os.path.join(self.plate, "roi")
        self.img_dir = os.path.join(self.plate, "images")
        self.out = os.path.join(self.dir, "AI_analysis")
        self.assets = os.path.join(self.out, "assets")
        self.ramp_min_v = ramp_min_v
        self._lut = None
        self._calib = calib or {}

    # -- paths -------------------------------------------------------------
    def mkout(self):
        os.makedirs(self.assets, exist_ok=True)
        return self.out

    @property
    def merged_csv(self):
        p = os.path.join(self.csv_dir, "all_wells_with_metadata.csv")
        return p if os.path.exists(p) else os.path.join(self.csv_dir,
                                                        "all_wells_combined.csv")

    def plate_groups(self):
        return sorted(os.path.basename(p) for p in glob.glob(f"{self.plate}/plate_*")
                      if os.path.isdir(p))

    # -- results -----------------------------------------------------------
    def results(self):
        return pd.read_csv(self.merged_csv)

    def pre(self, ramp_only=True):
        """Pre-collapse rows. `ramp_only` drops the low-voltage blank frames the
        acquisition interleaves, which are not part of the voltage ramp."""
        d = self.results()
        d = d[d.is_post == False]  # noqa: E712
        return d[d.voltage >= self.ramp_min_v] if ramp_only else d

    def post(self):
        d = self.results()
        return d[d.is_post == True]  # noqa: E712

    # -- pressure ----------------------------------------------------------
    def pressure(self, v=None):
        """Peak positive pressure at transmit voltage `v`.

        Linearly interpolated, because a *median* voltage across wells can land
        between two calibrated steps (e.g. 12.5 V) even though every measured
        voltage is on the grid.
        """
        if self._lut is None:
            self._lut = pressure_table(**self._calib) if self._calib \
                else pressure_table()
        if v is None:
            return self._lut
        v = float(v)
        if v in self._lut:
            return float(self._lut[v])
        xs = np.array(sorted(self._lut))
        return float(np.interp(v, xs, [self._lut[x] for x in xs]))

    def mpa(self, volts):
        return np.array([self.pressure(v) for v in volts], dtype=float)

    # -- images ------------------------------------------------------------
    def scan_dir(self, scan_name):
        for g in self.plate_groups():
            p = os.path.join(self.plate, g, scan_name)
            if os.path.isdir(p):
                return p
        p = os.path.join(self.plate, scan_name)
        if os.path.isdir(p):
            return p
        raise FileNotFoundError(f"{scan_name} not found under {self.plate}")

    def load_xam(self, scan_name, voltage, field="Imx"):
        """Mean frame at one voltage -> (X_mm, Z_mm, dB image)."""
        import scipy.io as sio
        pat = re.compile(rf"_{float(voltage):.1f}V_")
        files = sorted(f for f in glob.glob(f"{self.scan_dir(scan_name)}/Imgdata_*.mat")
                       if pat.search(os.path.basename(f)))
        if not files:
            raise FileNotFoundError(f"no {voltage} V frames in {scan_name}")
        acc = X = Z = None
        ax = ("Xx", "Zx") if field == "Imx" else ("Xb", "Zb")
        for f in files:
            I = sio.loadmat(f, squeeze_me=True, struct_as_record=False)["ImgData"]
            im = np.asarray(getattr(I, field), dtype=float)
            acc = im if acc is None else acc + im
            X, Z = np.asarray(getattr(I, ax[0])), np.asarray(getattr(I, ax[1]))
        return X, Z, 20 * np.log10(np.maximum(acc / len(files), 1e-9))

    def load_rois(self, scan_name):
        p = os.path.join(self.roi_dir, f"{scan_name}_rois.json")
        if not os.path.exists(p):
            p = os.path.join(self.roi_dir, "shared_rois.json")
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)

    def well_crop(self, scan_name, roi_label, voltage,
                  pad_x=2.2, z0=2.8, z1=6.2, field="Imx"):
        """Crop around one well. Returns (dB image, imshow extent, roi dict)."""
        X, Z, db = self.load_xam(scan_name, voltage, field=field)
        r = self.load_rois(scan_name)[roi_label]
        xs = np.where((X >= r["x_min"] - pad_x) & (X <= r["x_max"] + pad_x))[0]
        zs = np.where((Z >= z0) & (Z <= z1))[0]
        return db[np.ix_(zs, xs)], (X[xs[0]], X[xs[-1]], Z[zs[-1]], Z[zs[0]]), r

    # -- helpers -----------------------------------------------------------
    def median_well(self, df):
        """The well whose value is closest to the group median — the honest
        choice for a representative image, unlike the best-looking one."""
        m = df.sbr_x.median()
        r = df.iloc[(df.sbr_x - m).abs().argsort().iloc[0]]
        return {"scan_name": r.scan_name, "roi_label": r.roi_label,
                "sbr_x": round(float(r.sbr_x), 2)}

    def save_json(self, obj, name="stats.json"):
        self.mkout()
        p = os.path.join(self.out, name)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1, default=float)
        return p

    def load_json(self, name="stats.json"):
        with open(os.path.join(self.out, name), encoding="utf-8") as fh:
            return json.load(fh)
