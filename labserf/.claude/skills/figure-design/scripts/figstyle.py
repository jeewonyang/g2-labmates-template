"""Shapiro Lab figure style for matplotlib.

Import this before plotting anything that a person will look at:

    import sys; sys.path.insert(0, "<repo>/.claude/skills/figure-design/scripts")
    import figstyle as fs

    fs.use()
    fig, ax = fs.figure(45, 38)           # millimetres, the unit journals use
    ...
    fs.save(fig, "out/gfp_fraction")      # writes .pdf and .png

The rules this encodes are in `../references/shapiro-figure-rules.md`.
"""

from __future__ import annotations

import os
import warnings

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
STYLE = os.path.join(_HERE, "shapiro.mplstyle")

MM = 1 / 25.4  # millimetres -> inches

# Journal column widths (Nature), in millimetres.
SINGLE_COLUMN = 88.0
DOUBLE_COLUMN = 180.0

# --------------------------------------------------------------------- colors

INK = "#000000"
GREY_DARK = "#646464"
GREY = "#969696"
GREY_LIGHT = "#C8C8C8"
GREY_PALE = "#DDDDDD"
ACCENT = "#F28A00"        # the lab orange (GV_theme.thmx)
ACCENT_BRIGHT = "#FF9A00"  # the orange used in lab schematics
BLUE = "#5CB2C4"
BLUE_LIGHT = "#A2D5E0"

#: Greys first, orange last: build a series so the accent lands on the
#: condition the panel is about.
SERIES = [GREY_LIGHT, GREY, GREY_DARK, INK, ACCENT]

#: Channel-identity colors, for panels that are about the fluorophore rather
#: than the condition. Never mix these with the condition palette in one panel.
CHANNEL_COLORS = {
    "BFP": "#3B6FB6",
    "GFP": "#3E9B52",
    "OFP": "#F28A00",
    "IRFP": "#9E2B25",
}

#: Outline colours for ROIs and gates drawn *on top of image data* (B-mode,
#: xAM, BURST, microscopy). The lab orange disappears against `hot`/`inferno`
#: colormaps, which run black -> red -> orange -> white, so image overlays use
#: this fixed set instead. It is the one sanctioned exception to the palette,
#: and it is the same everywhere: a sample ROI is magenta in every image any
#: LabSerf tool draws.
OVERLAY = {
    "sample": "#FF00FF",   # magenta: reads against every part of the hot ramp
    "noise": "#00FFFF",    # cyan
    "ceiling": "#00FF00",  # lime
    "reference": "#FFFFFF",
}

#: Density colormap for pseudocolor dot plots. Deliberately greyscale: the
#: orange is reserved for the gate drawn on top, which is the thing the reader
#: is being asked to check.
DENSITY_CMAP = mpl.colors.LinearSegmentedColormap.from_list(
    "shapiro_density",
    ["#EDEDED", "#C8C8C8", "#969696", "#4D4D4D", "#000000"],
)


def use() -> None:
    """Apply the style sheet. Warns once if Arial is genuinely unavailable."""
    plt.style.use(STYLE)
    from matplotlib import font_manager as fm
    try:
        fm.findfont("Arial", fallback_to_default=False)
    except Exception:
        warnings.warn(
            "Arial not found; matplotlib will fall back to Helvetica or "
            "DejaVu Sans. The lab standard is Arial — install it before "
            "producing final figures.",
            stacklevel=2,
        )


def ramp(n: int, end: str = ACCENT, start: str = GREY_LIGHT) -> list[str]:
    """`n` colors ramping grey -> orange, for an ordered series (dose, time)."""
    cmap = mpl.colors.LinearSegmentedColormap.from_list("ramp", [start, end])
    if n == 1:
        return [end]
    return [mpl.colors.to_hex(cmap(i / (n - 1))) for i in range(n)]


def condition_colors(conditions, highlight=None) -> dict[str, str]:
    """Assign a stable color per condition: greys, with `highlight` in orange.

    Rule 4 of the lab rules — a condition keeps its color across every panel —
    so build this once per run and pass it everywhere.

    `highlight` is **not** guessed. Orange means "this is the point of the
    figure", and only the person who knows the experiment can say which
    condition that is; picking one automatically would assert a claim the
    data has not made. With no highlight every condition gets a grey.
    """
    conditions = list(dict.fromkeys(conditions))
    # One neutral grey for every non-highlighted condition, deliberately not a
    # ramp. A ramp across unordered categories implies an ordering that is not
    # there, and — worse — it gives the *same* condition a different grey in
    # different groups (strain A "+Dox" light, strain B "+Dox" dark), which is
    # exactly what rule 4 forbids. Use `ramp()` explicitly when the series
    # really is ordered, such as a dose or a timecourse.
    out = {c: GREY for c in conditions}
    if highlight is not None:
        out[highlight] = ACCENT
    return out


# --------------------------------------------------------------------- canvas

def figure(width_mm: float, height_mm: float, **kw):
    """A figure sized in millimetres, with one axes."""
    fig, ax = plt.subplots(figsize=(width_mm * MM, height_mm * MM), **kw)
    return fig, ax


def grid(nrows: int, ncols: int, width_mm: float, height_mm: float, **kw):
    """A grid of panels sized in millimetres."""
    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(width_mm * MM, height_mm * MM), **kw)
    return fig, axes


def save_png(fig, png_path: str, dpi: float | None = None) -> list[str]:
    """Save to an existing `.png` path *and* a `.pdf` beside it.

    For callers whose interface is a PNG filename (review images, viewers).
    The vector copy is what `check_figure.py` audits and what goes into
    Illustrator; image data inside it is embedded as a raster, as it should be.
    """
    stem = os.path.splitext(png_path)[0]
    os.makedirs(os.path.dirname(os.path.abspath(stem)) or ".", exist_ok=True)
    fig.savefig(stem + ".pdf", format="pdf")
    fig.savefig(stem + ".png", format="png", **({"dpi": dpi} if dpi else {}))
    plt.close(fig)
    return [stem + ".pdf", stem + ".png"]


def save(fig, stem: str, formats=("pdf", "png")) -> list[str]:
    """Write the figure to `<stem>.<fmt>` for each format.

    Always writes a vector format as well as the PNG: the vector file is what
    goes into Illustrator, and it is the only form `check_figure.py` can audit.
    """
    os.makedirs(os.path.dirname(os.path.abspath(stem)) or ".", exist_ok=True)
    out = []
    for fmt in formats:
        path = f"{stem}.{fmt}"
        fig.savefig(path, format=fmt)
        out.append(path)
    plt.close(fig)
    return out


# ----------------------------------------------------------------- annotation

def replicates(ax, x, values, color=INK, jitter=0.10, **kw):
    """Scatter the individual replicates over a summary — the lab shows its n."""
    # Seed from the position, not from hash(): Python randomises string
    # hashing per process, so a hash-derived seed would move the points every
    # time the figure is regenerated.
    rng = np.random.default_rng(int(round(float(x) * 1000)) & 0xFFFFFFFF)
    xs = np.full(len(values), float(x)) + rng.uniform(-jitter, jitter, len(values))
    kw.setdefault("s", 5)
    kw.setdefault("zorder", 3)
    kw.setdefault("linewidths", 0.5)
    return ax.scatter(xs, values, facecolors="white", edgecolors=color, **kw)


def n_label(ax, text: str, loc: str = "upper left") -> None:
    """Put the `n =` statement on the panel, where rule 6 wants it."""
    x, y, ha, va = {
        "upper left": (0.02, 0.98, "left", "top"),
        "upper right": (0.98, 0.98, "right", "top"),
        "lower left": (0.02, 0.02, "left", "bottom"),
        "lower right": (0.98, 0.02, "right", "bottom"),
    }[loc]
    ax.text(x, y, text, transform=ax.transAxes, ha=ha, va=va,
            fontsize=8, color=GREY_DARK)


def stars(p: float) -> str:
    """Significance marker. Print the p-value too wherever there is room."""
    if p < 1e-4:
        return "****"
    if p < 1e-3:
        return "***"
    if p < 1e-2:
        return "**"
    if p < 0.05:
        return "*"
    return "n.s."


def bracket(ax, x1: float, x2: float, y: float, label: str,
            tick: float | None = None, color=INK) -> None:
    """A significance bracket from x1 to x2 at height y, labelled `label`."""
    span = ax.get_ylim()[1] - ax.get_ylim()[0]
    tick = tick if tick is not None else 0.015 * span
    ax.plot([x1, x1, x2, x2], [y, y + tick, y + tick, y],
            lw=0.5, c=color, clip_on=False)
    # Offset in points, not data units: anchored exactly on the line, the
    # descender of "p" drops onto the bracket and the line reads as striking
    # through the text. A fixed physical gap holds at any axis scale.
    ax.annotate(label, ((x1 + x2) / 2, y + tick), xytext=(0, 1.5),
                textcoords="offset points", ha="center", va="bottom",
                fontsize=8, color=color, annotation_clip=False)


def asinh_axis(ax, which: str = "y", linthresh: float = 10.0) -> None:
    """Set a fluorescence axis to asinh scale.

    Hyperlog-calibrated MACSQuant data contains genuine negative values (about
    10% of events on a dim channel), so a log axis silently drops them. asinh
    is linear near zero and logarithmic beyond `linthresh`, which is what
    FlowJo's biexponential display does.
    """
    getattr(ax, f"set_{which}scale")("asinh", linear_width=linthresh)
