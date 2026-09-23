"""Automatic gating for MACSQuant data.

Three gates, in the order this lab draws them:

1. **Live / intact cells** — a density contour on FSC-A x SSC-A (or SSC-H x
   SSC-A where a height channel exists). `auto_scatter_gate`.
2. **Singlets** — area vs height. Only possible when the instrument records a
   height channel; the MACSQuant Analyzer 10 does not, so this step is
   normally skipped and said to be skipped. `auto_singlet_gate`.
3. **Fluorescence positivity** — a threshold per channel, from designated
   negative controls when they exist and from the negative population's own
   upper tail when they do not. `threshold`.

All gate coordinates are in `.fcs` DATA-segment units, the same units FlowJo
writes into a `.wsp`, so gates from either source are interchangeable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from wsp_io import Gate, points_in_polygon

#: Linear width of the asinh display transform, in data units. Fluorescence
#: below this is treated as noise around zero and shown linearly; above it the
#: axis is logarithmic. 2.0 puts the MACSQuant's negative peak (mode ~0.2,
#: sigma ~0.1) comfortably inside the linear region.
ASINH_WIDTH = 2.0

#: How many robust standard deviations above the negative population's mode a
#: cell must sit to count as positive. Calibrated against this lab's own
#: hand-drawn FlowJo thresholds (2026-01-10 and 2026-01-14 workspaces), where
#: the hand-set cut fell at 8.4-9.4 sigma for three of four channel/day
#: combinations.
DEFAULT_K = 9.0

#: Display window for the scatter channels. MACSQuantify scales FSC-A/SSC-A so
#: that the instrument's full scale is 1000; events beyond it are saturated.
SCATTER_MAX = 1000.0

#: Linear width of the asinh transform used to *fit* the scatter gate. Cells
#: occupy roughly one decade of FSC/SSC sitting on top of a debris cloud near
#: zero, so on a linear axis the whole population collapses into the bottom-left
#: corner and a density contour fits the debris boundary instead of the cells.
#: Fitting in asinh space and mapping the polygon back fixes that. Calibrated
#: against this lab's hand-drawn gates: width 20 with the defaults below
#: reproduces them at Jaccard 0.941 (2026-01-10) and 0.964 (2026-01-14).
SCATTER_ASINH_WIDTH = 20.0


def asinh_fwd(v: np.ndarray, width: float = ASINH_WIDTH) -> np.ndarray:
    return np.arcsinh(np.asarray(v, dtype=float) / width)


def asinh_inv(a: np.ndarray, width: float = ASINH_WIDTH) -> np.ndarray:
    return np.sinh(np.asarray(a, dtype=float)) * width


# ------------------------------------------------------------- scatter gating

def _simplify(poly: np.ndarray, max_vertices: int = 24) -> np.ndarray:
    """Reduce a dense contour to at most `max_vertices`, keeping its shape."""
    if len(poly) <= max_vertices:
        return poly
    # Resample at equal arc length — robust and keeps the outline convex-ish,
    # which is what a hand-drawn flow gate looks like.
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(poly, axis=0).T))]
    t = np.linspace(0, d[-1], max_vertices, endpoint=False)
    return np.column_stack([np.interp(t, d, poly[:, 0]), np.interp(t, d, poly[:, 1])])


def _trace(mask: np.ndarray, xc: np.ndarray, yc: np.ndarray) -> np.ndarray:
    """Outline of a boolean bin mask as a closed polygon in data coordinates."""
    import matplotlib
    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    # Pad with an empty border so a blob that reaches the edge of the display
    # window still yields a closed loop. Without this the contour runs off the
    # array and the traced "polygon" is a boundary fragment, which silently
    # collapses the gate.
    padded = np.pad(mask.astype(float), 1)
    dx, dy = xc[1] - xc[0], yc[1] - yc[0]
    xp = np.r_[xc[0] - dx, xc, xc[-1] + dx]
    yp = np.r_[yc[0] - dy, yc, yc[-1] + dy]

    fig = plt.figure()
    try:
        # `mask` is indexed [x, y]; contour expects [row=y, col=x].
        cs = plt.contour(xp, yp, padded.T, levels=[0.5])
        level = cs.allsegs[0]
        # matplotlib 3.8.0 returns a lone contour as the (N, 2) array itself
        # rather than a one-element list; iterating it yields single points,
        # every one too short, and the gate "could not be traced".
        if isinstance(level, np.ndarray) and level.ndim == 2 and level.shape[-1] == 2:
            level = [level]
        segments = [s for s in level if len(s) >= 4]
    finally:
        plt.close(fig)
    if not segments:
        raise ValueError("could not trace a scatter contour")
    return np.asarray(max(segments, key=len), dtype=float)


def _smooth_closed(poly: np.ndarray, passes: int = 2) -> np.ndarray:
    """Round off the kinks a traced contour leaves in a gate outline.

    Where the debris cloud meets the cell population the density contour can
    turn a sharp concave corner. It is an artifact of where the contour level
    fell, not a feature of the data, and drawn on 25 panels it is the first
    thing the eye lands on. A couple of passes of a closed 3-point moving
    average removes it without moving the boundary meaningfully.
    """
    p = poly.copy()
    for _ in range(passes):
        p = (np.roll(p, 1, axis=0) + 2 * p + np.roll(p, -1, axis=0)) / 4
    return p


def _expand(poly: np.ndarray, factor: float) -> np.ndarray:
    """Grow a polygon about its centroid, so the gate does not clip the population."""
    c = poly.mean(axis=0)
    return c + (poly - c) * factor


@dataclass
class ScatterGate:
    gate: Gate
    x_channel: str
    y_channel: str
    fraction: float                 # of all events that fall inside
    method: str
    diagnostics: dict = field(default_factory=dict)


def auto_scatter_gate(x: np.ndarray, y: np.ndarray,
                      x_channel: str, y_channel: str,
                      coverage: float = 0.85,
                      expand: float = 1.02,
                      bins: int = 256,
                      smooth: float = 4.0,
                      width: float = SCATTER_ASINH_WIDTH,
                      name: str = "Live cells") -> ScatterGate:
    """Fit a polygon around the main scatter population.

    Builds a smoothed 2-D density in asinh space over the display window,
    takes the contour of the largest connected region holding `coverage` of
    the windowed events, grows it slightly so the population's edge is not
    clipped, and maps the polygon back to data units. This mirrors how the
    gate is drawn by hand: generously around the body of cells, excluding
    debris near the origin and saturated events at the rails.

    The returned polygon is in data units, so it is interchangeable with a
    gate read from a FlowJo `.wsp`.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    ax, ay = asinh_fwd(x, width), asinh_fwd(y, width)
    limit = float(asinh_fwd(SCATTER_MAX, width))

    win = (ax > 0) & (ax < limit) & (ay > 0) & (ay < limit)
    if win.sum() < 100:
        raise ValueError("too few events inside the scatter display window to gate")

    H, xe, ye = np.histogram2d(ax[win], ay[win], bins=bins,
                               range=[[0, limit], [0, limit]])
    H = ndimage.gaussian_filter(H, smooth)

    # Density threshold such that the retained bins hold `coverage` of events.
    flat = np.sort(H.ravel())[::-1]
    cum = np.cumsum(flat)
    if cum[-1] <= 0:
        raise ValueError("empty scatter density")
    level = flat[np.searchsorted(cum, coverage * cum[-1])]

    mask = H >= level
    # Keep only the largest connected blob: debris forms its own island.
    lab, n = ndimage.label(mask)
    if n > 1:
        sizes = ndimage.sum(H, lab, range(1, n + 1))
        mask = lab == (int(np.argmax(sizes)) + 1)
    mask = ndimage.binary_fill_holes(mask)

    poly = _expand(_smooth_closed(_simplify(
        _trace(mask, (xe[:-1] + xe[1:]) / 2, (ye[:-1] + ye[1:]) / 2))), expand)
    poly = np.column_stack([asinh_inv(poly[:, 0], width),
                            asinh_inv(poly[:, 1], width)])
    poly = np.clip(poly, 0, SCATTER_MAX)

    gate = Gate(name=name, kind="polygon", dims=[x_channel, y_channel], vertices=poly)
    inside = points_in_polygon(x, y, poly)
    return ScatterGate(
        gate=gate, x_channel=x_channel, y_channel=y_channel,
        fraction=float(inside.mean()),
        method=(f"asinh density contour (width={width:g}, coverage={coverage:g}, "
                f"expand={expand:g})"),
        diagnostics={"n_inside": int(inside.sum()), "n_total": int(len(x)),
                     "n_windowed": int(win.sum()), "vertices": len(poly)},
    )


def jaccard(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    """Agreement between two gates, measured on the events they are applied to."""
    inter = np.logical_and(mask_a, mask_b).sum()
    union = np.logical_or(mask_a, mask_b).sum()
    return float(inter / union) if union else float("nan")


# ------------------------------------------------------------- singlet gating

def auto_singlet_gate(area: np.ndarray, height: np.ndarray,
                      a_channel: str, h_channel: str,
                      width: float = 3.0) -> ScatterGate:
    """Gate singlets on area vs height.

    Singlets lie on a straight A-H line; doublets sit above it (more area for
    the same height). Fits the ridge robustly and keeps events within
    `width` robust standard deviations of it.
    """
    a = np.asarray(area, float)
    h = np.asarray(height, float)
    ok = (a > 0) & (h > 0)
    ratio = np.full(a.shape, np.nan)
    ratio[ok] = a[ok] / h[ok]
    med = np.nanmedian(ratio)
    mad = 1.4826 * np.nanmedian(np.abs(ratio - med))
    lo, hi = med - width * mad, med + width * mad

    # Express as a polygon in (height, area) so it can be drawn and stored
    # like any other gate.
    hmax = float(np.nanpercentile(h, 99.9))
    poly = np.array([[0, 0], [hmax, hmax * lo], [hmax, hmax * hi], [0, 0]])
    gate = Gate(name="Singlets", kind="polygon", dims=[h_channel, a_channel], vertices=poly)
    inside = points_in_polygon(h, a, poly)
    return ScatterGate(
        gate=gate, x_channel=h_channel, y_channel=a_channel,
        fraction=float(inside.mean()),
        method=f"A/H ratio within {width:g} robust SD of the median",
        diagnostics={"ratio_median": float(med), "ratio_mad": float(mad),
                     "lo": float(lo), "hi": float(hi)},
    )


# --------------------------------------------------------------- thresholding

@dataclass
class Threshold:
    role: str
    value: float          # in data units
    method: str
    diagnostics: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.role}+ at {self.value:.3g} ({self.method})"


def negative_mode(values: np.ndarray, width: float = ASINH_WIDTH) -> tuple[float, float]:
    """Mode and robust spread of the negative population, in asinh units.

    The spread is measured from the *left* half of the peak only. Positive
    cells sit to the right, so the left half is uncontaminated and reflecting
    it gives an honest width for the negative distribution.
    """
    a = asinh_fwd(values, width)
    a = a[np.isfinite(a)]
    if a.size < 100:
        raise ValueError("too few events to model the negative population")
    lo, hi = np.percentile(a, [0.1, 99.9])
    h, e = np.histogram(a, bins=400, range=(lo, hi))
    centres = (e[:-1] + e[1:]) / 2
    h = ndimage.uniform_filter1d(h.astype(float), 9)
    mode = float(centres[int(np.argmax(h))])

    left = a[a < mode]
    if left.size < 50:
        raise ValueError("negative population has no measurable left tail")
    sigma = float(1.4826 * np.median(np.abs(left - mode)))
    return mode, sigma


def threshold(role: str,
              values: np.ndarray,
              negative_values: np.ndarray | None = None,
              k: float = DEFAULT_K,
              percentile: float = 99.5,
              width: float = ASINH_WIDTH) -> Threshold:
    """Where the positive gate for one fluorescence channel goes.

    With `negative_values` (pooled events from designated negative-control
    wells), the cut is the `percentile` of that control — the standard,
    defensible choice, and the one to prefer whenever a control exists.

    Without a control, the cut is `k` robust standard deviations above the
    mode of the negative population in the data itself.

    How well that matches this lab's hand-drawn cuts, measured on the two
    example workspaces with the auto live gate applied:

        run         channel   auto    FlowJo   difference
        2026-01-10  GFP       2.90    2.43     +19%
        2026-01-10  iRFP      2.78    5.23     -47%
        2026-01-14  GFP       2.53    2.43     +4%
        2026-01-14  iRFP      2.77    2.90     -4%

    The 2026-01-10 iRFP cut was set about 5 sigma more conservatively by eye
    than the same operator set it four days later, which is the variability
    this rule exists to remove — but it also means the rule and the eye can
    disagree by a factor of two on where "positive" starts.

    `k = 9` was chosen on these same two runs, so it is calibrated, not
    independently validated. **Prefer `negative_values` whenever the plate
    carries a real negative control**; it is defensible without reference to
    this calibration, and it is the number a reviewer will expect.
    """
    if negative_values is not None and len(negative_values) >= 100:
        v = float(np.percentile(negative_values, percentile))
        return Threshold(role, v,
                         f"{percentile:g}th percentile of negative control",
                         {"n_control": int(len(negative_values))})

    mode, sigma = negative_mode(values, width)
    a = mode + k * sigma
    v = float(asinh_inv(a, width))
    return Threshold(role, v,
                     f"negative mode + {k:g} robust SD (no control)",
                     {"mode_asinh": mode, "sigma_asinh": sigma,
                      "threshold_asinh": float(a), "n": int(len(values))})


# ----------------------------------------------------------------- statistics

def positive_stats(values: np.ndarray, thr: float) -> dict:
    """Fraction positive and central tendency for one channel in one sample.

    No geometric mean: hyperlog-calibrated MACSQuant data contains genuine
    negative values (roughly 10% of events on a dim channel), so a geometric
    mean is undefined. The median is the robust summary; the arithmetic mean
    is reported alongside because it is what a plate reader would give.
    """
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    pos = v >= thr
    out = {
        "n": int(v.size),
        "n_positive": int(pos.sum()),
        "percent_positive": float(100.0 * pos.mean()) if v.size else float("nan"),
        "median": float(np.median(v)) if v.size else float("nan"),
        "mean": float(np.mean(v)) if v.size else float("nan"),
        "median_positive": float(np.median(v[pos])) if pos.any() else float("nan"),
        "mean_positive": float(np.mean(v[pos])) if pos.any() else float("nan"),
    }
    # Median of the asinh-transformed values, back-transformed: the location
    # of the whole distribution on the axis the data is displayed on.
    out["median_asinh"] = float(asinh_inv(np.median(asinh_fwd(v)))) if v.size else float("nan")
    return out


def quadrant_stats(x: np.ndarray, y: np.ndarray, tx: float, ty: float,
                   x_role: str = "X", y_role: str = "Y") -> dict:
    """Quadrant counts and percentages, in FlowJo's Q1..Q4 convention.

    Q1 = x- y+, Q2 = x+ y+ (the double positive), Q3 = x+ y-, Q4 = x- y-.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    xp, yp = x >= tx, y >= ty
    n = len(x)
    quads = {
        "Q1": (~xp) & yp,
        "Q2": xp & yp,
        "Q3": xp & (~yp),
        "Q4": (~xp) & (~yp),
    }
    labels = {
        "Q1": f"{x_role}- {y_role}+",
        "Q2": f"{x_role}+ {y_role}+",
        "Q3": f"{x_role}+ {y_role}-",
        "Q4": f"{x_role}- {y_role}-",
    }
    out = {"n": n, "threshold_x": float(tx), "threshold_y": float(ty),
           "x_role": x_role, "y_role": y_role}
    for q, m in quads.items():
        out[f"{q}_label"] = labels[q]
        out[f"{q}_n"] = int(m.sum())
        out[f"{q}_percent"] = float(100.0 * m.mean()) if n else float("nan")
    out["double_positive_percent"] = out["Q2_percent"]
    return out
