"""Review and result figures for flow cytometry runs.

Every gate the pipeline places gets a review image, because the gates are
drawn automatically and the checking is what makes that safe. All figures go
through the Shapiro Lab style (`figure-design` skill), are emitted as PDF +
PNG, and are auditable by `check_figure.py`.
"""

from __future__ import annotations

import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "figure-design", "scripts"))

import figstyle as fs  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon as MplPolygon  # noqa: E402

import gating  # noqa: E402

SCATTER_W = gating.SCATTER_ASINH_WIDTH


# ------------------------------------------------------------------ primitives

def _decade_label(value: float) -> str:
    """Plain-text decade label: 0, 10, 100, 1k, 10k, 100k.

    Deliberately avoids both mathtext (`$10^3$`, which matplotlib renders in
    its own font set at a reduced size) and Unicode superscripts (Arial has
    no U+2070 or U+2074, so macOS substitutes the Last Resort font). Either
    one breaks "8 pt Arial for everything" and `check_figure.py` fails it.
    """
    if value == 0:
        return "0"
    if value < 1000:
        return f"{value:g}"
    if value < 1_000_000:
        return f"{value / 1000:g}k"
    return f"{value / 1_000_000:g}M"


def _si(n: int) -> str:
    """Compact event count: 75943 -> '75.9k'. Panels are 30 mm wide."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.2f}M"


def _plain_log_formatter():
    """Log-axis tick labels without mathtext: 1e-4, 1e-3, 0.01, 1, 10, ..."""
    from matplotlib.ticker import FuncFormatter

    def fmt(v, _pos):
        if v <= 0:
            return ""
        e = int(np.round(np.log10(v)))
        if -2 <= e <= 4:
            return f"{v:g}"
        return f"1e{e}"

    return FuncFormatter(fmt)


def _asinh_ticks(ax, which: str, width: float, limit: float,
                 min_gap: float = 0.13) -> None:
    """Decade ticks on an asinh axis, labelled in data units.

    Near zero the asinh transform is linear, so 0, 1 and 10 can land almost on
    top of each other and their labels collide. Decades closer than `min_gap`
    of the axis span to an already-placed tick are dropped.
    """
    span = float(gating.asinh_fwd(limit, width))
    pos: list[float] = []
    labels: list[str] = []
    for t in (0, 1, 10, 100, 1_000, 10_000, 100_000):
        if t > limit:
            break
        p = float(gating.asinh_fwd(float(t), width))
        if pos and (p - pos[-1]) < min_gap * span:
            continue  # would collide with the label already placed
        pos.append(p)
        labels.append(_decade_label(float(t)))

    (ax.set_xticks if which == "x" else ax.set_yticks)(pos)
    (ax.set_xticklabels if which == "x" else ax.set_yticklabels)(labels)


def density_scatter(ax, x, y, width_x, width_y, bins=200, limit=None):
    """Pseudocolor density plot in asinh space.

    The counts are log-normalised: flow densities span several orders of
    magnitude, and on a linear norm everything but the core reads as blank
    white, which hides exactly the sparse events a gate has to be judged on.
    """
    from matplotlib.colors import LogNorm

    ax_ = gating.asinh_fwd(x, width_x)
    ay_ = gating.asinh_fwd(y, width_y)
    lim_x = gating.asinh_fwd(limit or np.nanpercentile(x, 99.9), width_x)
    lim_y = gating.asinh_fwd(limit or np.nanpercentile(y, 99.9), width_y)
    # Lower bound from the data, not a fixed -width: on a dim channel the
    # negative population reaches well below it and would be clipped against
    # the spine — exactly the population the threshold is judged against.
    lo_x = min(float(np.nanpercentile(ax_, 0.05)), gating.asinh_fwd(-width_x, width_x))
    lo_y = min(float(np.nanpercentile(ay_, 0.05)), gating.asinh_fwd(-width_y, width_y))
    ok = np.isfinite(ax_) & np.isfinite(ay_)
    ax.hist2d(ax_[ok], ay_[ok], bins=bins,
              range=[[lo_x, lim_x], [lo_y, lim_y]],
              cmap=fs.DENSITY_CMAP, cmin=1, norm=LogNorm(), rasterized=True)
    return ax_, ay_, lim_x, lim_y


def outer_labels(axes_grid, xlabel: str, ylabel: str, n_used: int) -> None:
    """Label only the outer axes of a panel grid — repeating them is noise."""
    nrows, ncols = len(axes_grid), len(axes_grid[0])
    for r, row in enumerate(axes_grid):
        for c, ax in enumerate(row):
            i = r * ncols + c
            if i >= n_used:
                continue
            bottom = (i + ncols >= n_used)  # nothing below it in the grid
            ax.set_xlabel(xlabel if bottom else "")
            ax.set_ylabel(ylabel if c == 0 else "")
            if c != 0:
                ax.set_yticklabels([])
            if not bottom:
                ax.set_xticklabels([])


def grow_for_labels(fig, ax, axes_height_mm: float = 34.0) -> None:
    """Grow the canvas so rotated tick labels do not eat into the axes.

    `tight_layout` keeps the figure size fixed and shrinks the axes to fit the
    labels, so long rotated condition names can squash a plot to a sliver.
    Measuring the labels after a trial draw and resizing the figure keeps the
    plotting area at `axes_height_mm` however long the names are.
    """
    want_in = axes_height_mm * fs.MM
    # tight_layout redistributes space each time, so converge rather than
    # assuming one correction lands exactly.
    for _ in range(4):
        fig.tight_layout()
        fig_w_in, fig_h_in = fig.get_size_inches()
        axes_h_in = ax.get_position().height * fig_h_in
        if axes_h_in <= 0 or abs(axes_h_in - want_in) < 0.01:
            break
        # Labels, title and padding keep their absolute size; only the
        # plotting area needs to change.
        fig.set_size_inches(fig_w_in, max(0.4, fig_h_in - axes_h_in + want_in))
    fig.tight_layout()


def draw_polygon(ax, verts, width_x, width_y, color=fs.ACCENT, label=None, ls="-"):
    p = np.column_stack([gating.asinh_fwd(verts[:, 0], width_x),
                         gating.asinh_fwd(verts[:, 1], width_y)])
    ax.add_patch(MplPolygon(p, closed=True, fill=False, edgecolor=color,
                            lw=0.5, ls=ls, zorder=5, label=label))


# --------------------------------------------------------------- gate reviews

def scatter_gate_review(samples, sgate, out_stem: str,
                        hand_gate=None, max_panels: int = 10**6,
                        title: str = "Live-cell gate"):
    """The scatter gate drawn over the pooled data and over each sample.

    `hand_gate` — a gate read from a FlowJo `.wsp` — is overlaid in grey for
    comparison when one exists.
    """
    fs.use()
    panels = samples[:max_panels]
    xch, ych = sgate.x_channel, sgate.y_channel

    # The pooled view (what the gate was fitted to) is panel 0, then one panel
    # per sample, all the same size so they can be compared at a glance.
    ncols = min(5, max(1, len(panels) + 1))
    nrows = int(np.ceil((len(panels) + 1) / ncols))
    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(ncols * 30 * fs.MM, nrows * 30 * fs.MM),
                             squeeze=False)
    flat = [a for row in axes for a in row]

    def panel(ax, x, y, heading, bins):
        density_scatter(ax, x, y, SCATTER_W, SCATTER_W, bins=bins,
                        limit=gating.SCATTER_MAX)
        draw_polygon(ax, sgate.gate.vertices, SCATTER_W, SCATTER_W, fs.ACCENT)
        ax.set_title(heading, fontsize=8)
        # The event count goes inside the panel: in the title it is wider than
        # a 30 mm panel and collides with the neighbouring title.
        ax.text(0.97, 0.04, f"n = {_si(len(x))}", transform=ax.transAxes,
                fontsize=8, color=fs.GREY_DARK, va="bottom", ha="right")
        _asinh_ticks(ax, "x", SCATTER_W, gating.SCATTER_MAX)
        _asinh_ticks(ax, "y", SCATTER_W, gating.SCATTER_MAX)

    px = np.concatenate([s.col(xch) for s in panels])
    py = np.concatenate([s.col(ych) for s in panels])
    panel(flat[0], px, py, f"Pooled\n{sgate.fraction * 100:.1f}% in gate", 200)

    # Direct labels on the pooled panel beat a legend (rule 1), placed in the
    # empty lower-right rather than over the gate they describe.
    flat[0].text(0.97, 0.34, f"auto {sgate.fraction * 100:.1f}%",
                 transform=flat[0].transAxes, color=fs.ACCENT,
                 fontsize=8, va="bottom", ha="right")
    if hand_gate is not None:
        draw_polygon(flat[0], hand_gate.vertices, SCATTER_W, SCATTER_W,
                     fs.GREY_DARK, ls="--")
        # The whole point of the overlay is to judge the disagreement, which
        # needs both numbers, not one.
        hand_frac = float(hand_gate.mask({xch: px, ych: py}).mean())
        flat[0].text(0.97, 0.18,
                     f"FlowJo {hand_frac * 100:.1f}%\n"
                     f"{(sgate.fraction - hand_frac) * 100:+.1f} pts",
                     transform=flat[0].transAxes, color=fs.GREY_DARK,
                     fontsize=8, va="bottom", ha="right")

    for ax, s in zip(flat[1:], panels):
        x, y = s.col(xch), s.col(ych)
        inside = sgate.gate.mask({xch: x, ych: y})
        panel(ax, x, y, f"{s.well} {s.condition}\n{inside.mean() * 100:.1f}%", 150)
        s.release()
    for ax in flat[len(panels) + 1:]:
        ax.axis("off")
    outer_labels(axes, f"{xch} (a.u.)", f"{ych} (a.u.)", len(panels) + 1)

    sub = f"{sgate.method}; biexponential axes"
    if hand_gate is not None:
        sub += f"; FlowJo '{hand_gate.name}' dashed, pooled panel only"
    fig.suptitle(f"{title}\n{sub}", fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return fs.save(fig, out_stem)


def threshold_review(samples, role: str, thr, sgate, out_stem: str,
                     hand_threshold: float | None = None):
    """Per-channel histograms with the positivity threshold drawn on."""
    fs.use()
    fig, ax = fs.figure(88, 50)

    xch, ych = sgate.x_channel, sgate.y_channel
    pooled = []
    for s in samples:
        m = sgate.gate.mask({xch: s.col(xch), ych: s.col(ych)})
        pooled.append(s.col(role)[m])
        s.release()
    allv = np.concatenate(pooled)

    # Histogram range from the data, not a fixed window: a hard-coded upper
    # edge silently drops the brightest cells, which are exactly the ones the
    # positive gate is about.
    a_all = gating.asinh_fwd(allv)
    lo = float(np.nanpercentile(a_all, 0.01)) - 0.3
    hi = float(np.nanmax(a_all)) + 0.2
    span = (lo, hi)

    for v in pooled:
        ax.hist(gating.asinh_fwd(v), bins=220, range=span, histtype="step",
                lw=0.5, color=fs.GREY_LIGHT, density=True)
    ax.hist(a_all, bins=220, range=span, histtype="step",
            lw=0.5, color=fs.INK, density=True)

    # Log density: the negative peak is 100x the positive shoulder, and the
    # shoulder is the part the threshold has to be judged against.
    ax.set_yscale("log")
    ax.set_ylim(bottom=1e-4)
    ax.yaxis.set_major_formatter(_plain_log_formatter())
    ax.yaxis.set_minor_formatter(_plain_log_formatter())
    ax.tick_params(axis="y", which="minor", labelleft=False)

    # Crop to the data (rule 8) and leave headroom for the annotations.
    ax.set_xlim(*span)
    ylo, yhi = ax.get_ylim()
    ax.set_ylim(ylo, yhi * 8)

    ax.axvline(gating.asinh_fwd(thr.value), color=fs.ACCENT, lw=0.5)
    if hand_threshold is not None:
        ax.axvline(gating.asinh_fwd(hand_threshold), color=fs.GREY_DARK,
                   lw=0.5, ls="--")

    # Both cuts and what each one *costs*, stacked in the corner rather than
    # hung off their own lines: at 8 pt these labels are wider than the gap
    # between the two thresholds and would overlap each other and the peak.
    # The percentage is the number the reader actually has to decide between.
    pct = 100.0 * (allv >= thr.value).mean()
    lines = [(f"auto ≥ {thr.value:.3g}  →  {pct:.1f}% {role}+", fs.ACCENT)]
    if hand_threshold is not None:
        hpct = 100.0 * (allv >= hand_threshold).mean()
        lines.append((f"FlowJo ≥ {hand_threshold:.3g}  →  {hpct:.1f}%",
                      fs.GREY_DARK))
    for i, (text, color) in enumerate(lines):
        ax.text(0.98, 0.97 - 0.10 * i, text, transform=ax.transAxes,
                fontsize=8, color=color, va="top", ha="right")

    # Direct labels instead of a legend in the title (rule 1/5).
    note = f"black: pooled\ngrey: {len(pooled)} wells"
    if "no control" in thr.method:
        note += "\n\nno negative control in this run —\nthreshold is model-based"
    ax.text(0.98, 0.62, note, transform=ax.transAxes, fontsize=8,
            color=fs.GREY_DARK, va="top", ha="right")

    _asinh_ticks(ax, "x", gating.ASINH_WIDTH, 10_000)
    ch = samples[0].by_role(role)
    ax.set_xlabel(f"{role} ({ch.label if ch else role}, a.u., biexponential)")
    ax.set_ylabel("Density (fraction of events)")
    ax.set_title(f"{role}+ threshold — {thr.method}", fontsize=8)
    fig.tight_layout()
    return fs.save(fig, out_stem)


def quadrant_review(samples, role_x: str, role_y: str, tx: float, ty: float,
                    sgate, out_stem: str, max_panels: int = 10**6):
    """Two-channel quadrant plots with the shared thresholds and Q percentages."""
    fs.use()
    panels = samples[:max_panels]
    ncols = min(4, max(1, len(panels)))
    nrows = int(np.ceil(len(panels) / ncols))
    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(ncols * 34 * fs.MM, nrows * 34 * fs.MM),
                             squeeze=False)
    flat = [a for row in axes for a in row]
    xch, ych = sgate.x_channel, sgate.y_channel
    W = gating.ASINH_WIDTH

    for ax, s in zip(flat, panels):
        m = sgate.gate.mask({xch: s.col(xch), ych: s.col(ych)})
        x, y = s.col(role_x)[m], s.col(role_y)[m]
        density_scatter(ax, x, y, W, W, bins=150, limit=10_000)
        ax.axvline(gating.asinh_fwd(tx, W), color=fs.ACCENT, lw=0.5)
        ax.axhline(gating.asinh_fwd(ty, W), color=fs.ACCENT, lw=0.5)
        q = gating.quadrant_stats(x, y, tx, ty, role_x, role_y)
        # Axes-fraction placement, inset from the corners. Data coordinates put
        # the bottom pair exactly on the spine, where the axis line cuts
        # through the glyphs and the negative blob sits behind them.
        for key, (fx, fy, ha, va) in {
            "Q1": (0.04, 0.96, "left", "top"),
            "Q2": (0.96, 0.96, "right", "top"),
            "Q3": (0.96, 0.06, "right", "bottom"),
            "Q4": (0.04, 0.06, "left", "bottom"),
        }.items():
            # Orange is already the thresholds on this panel; one accent per
            # panel, so the quadrant numbers stay black.
            ax.text(fx, fy, f"{q[f'{key}_percent']:.1f}%", transform=ax.transAxes,
                    ha=ha, va=va, fontsize=8, color=fs.INK)
        ax.set_title(f"{s.well} {s.condition}", fontsize=8)
        _asinh_ticks(ax, "x", W, 10_000)
        _asinh_ticks(ax, "y", W, 10_000)
        s.release()
    for ax in flat[len(panels):]:
        ax.axis("off")
    lx = samples[0].by_role(role_x)
    ly = samples[0].by_role(role_y)
    outer_labels(axes, f"{role_x} ({lx.label if lx else role_x}, a.u.)",
                 f"{role_y} ({ly.label if ly else role_y}, a.u.)", len(panels))

    fig.suptitle(
        f"{role_x} vs {role_y} \u2014 % of live-gated cells per quadrant\n"
        f"thresholds (orange): {role_x}+ \u2265 {tx:.3g}, {role_y}+ \u2265 {ty:.3g}   |   "
        f"upper right = {role_x}+{role_y}+ double positive", fontsize=8)
    fig.tight_layout()
    return fs.save(fig, out_stem)


# ------------------------------------------------------------ result figures

def _grouped(rows, key, value):
    out: dict[str, list[float]] = {}
    for r in rows:
        out.setdefault(r[key], []).append(r[value])
    return out


def _annotate_comparisons(ax, conds, groups, comparisons) -> tuple[float, str]:
    """Draw significance annotations; return (top of the highest one, title note).

    Two layouts, because seven stacked brackets is not "visible at a glance":
    when every comparison shares one condition (a vs-reference design) the
    result goes directly above each tested bar; otherwise each pair gets its
    own bracket, stacked shortest-span first.
    """
    usable = [c for c in comparisons if c.ok]
    if not usable:
        return ax.get_ylim()[1], ""

    index = {c: i for i, c in enumerate(conds)}
    tops = {}
    for c in conds:
        v = np.asarray(groups[c], float)
        v = v[np.isfinite(v)]
        tops[c] = (v.mean() + (v.std(ddof=1) if v.size > 1 else 0.0)
                   if v.size else 0.0)
    span = max(tops.values()) or 1.0
    ceiling = ax.get_ylim()[1]

    lefts, rights = {c.a for c in usable}, {c.b for c in usable}
    vs_reference = len(usable) > 1 and (len(lefts) == 1 or len(rights) == 1)

    if vs_reference:
        # Stars only. An exact p-value at 8 pt is ~16 mm wide and the bars are
        # ~9 mm apart, so per-bar p-values collide with their neighbours. This
        # is how Prism shows multiple comparisons against a control; the exact
        # values are in comparisons.csv and RESULTS.md.
        ref = next(iter(lefts)) if len(lefts) == 1 else next(iter(rights))
        for comp in usable:
            other = comp.b if comp.a == ref else comp.a
            if other not in index:
                continue
            y = tops[other] + 0.04 * span
            # Stars over a 2-significant-figure p: ~9 mm, which fits the bar
            # spacing where a full "p = 0.0064" (~16 mm) collided.
            ax.annotate(comp.label(), (index[other], y), xytext=(0, 1.5),
                        textcoords="offset points", ha="center", va="bottom",
                        fontsize=8, color=fs.INK, annotation_clip=False,
                        linespacing=1.0)
            ceiling = max(ceiling, y + 0.22 * span)
        if ref in index:
            # A line at the reference mean makes "every mark is relative to
            # this bar" readable at a glance, not just from the header.
            v = np.asarray(groups[ref], float)
            ax.axhline(np.nanmean(v), color=fs.GREY_DARK, lw=0.5, ls="--", zorder=0)
            ax.annotate("ref", (index[ref], tops[ref] + 0.04 * span), xytext=(0, 1.5),
                        textcoords="offset points", ha="center", va="bottom",
                        fontsize=8, color=fs.GREY_DARK, annotation_clip=False)
        return ceiling, f"vs {ref} (dashed line)"

    # Each bracket sits just above the tallest bar it spans, and only climbs
    # when it would collide with a bracket already placed over the same bars.
    # Stacking every bracket on a global staircase wastes half the axis and
    # suggests the comparisons are nested when they are independent.
    gap = 0.06 * span
    height = 0.24 * span          # bracket + two lines of 8 pt label
    placed: list[tuple[int, int, float]] = []   # (i, j, y) of drawn brackets
    ordered = sorted((c for c in usable if c.a in index and c.b in index),
                     key=lambda c: (abs(index[c.a] - index[c.b]),
                                    min(index[c.a], index[c.b])))
    for comp in ordered:
        i, j = sorted((index[comp.a], index[comp.b]))
        y = max(tops[conds[k]] for k in range(i, j + 1)) + gap
        # Raise past any placed bracket that overlaps horizontally.
        moved = True
        while moved:
            moved = False
            for pi, pj, py in placed:
                if pi <= j and i <= pj and abs(py - y) < height:
                    y = py + height
                    moved = True
        fs.bracket(ax, i, j, y, comp.label(), tick=0.02 * span)
        placed.append((i, j, y))
        ceiling = max(ceiling, y + height)
    return ceiling, ""


def condition_bars(rows, value_key: str, ylabel: str, out_stem: str,
                   highlight: str | None = None, title: str | None = None,
                   colors: dict[str, str] | None = None,
                   comparisons=None):
    """Mean +/- SD per condition with every replicate shown over the bar.

    `comparisons` is the list of `stats_tests.Comparison` for this metric;
    significant ones are annotated on the panel, because the lab's rules want
    the statistics visible at a glance rather than in a caption.
    """
    fs.use()
    groups = _grouped(rows, "condition", value_key)
    conds = list(groups)
    colors = colors or fs.condition_colors(conds, highlight=highlight)

    width_mm = max(45.0, 9.0 * len(conds) + 20.0)
    fig, ax = fs.figure(min(width_mm, fs.DOUBLE_COLUMN), 45)

    ns = set()
    for i, c in enumerate(conds):
        v = np.array(groups[c], float)
        ns.add(len(v))
        ax.bar(i, v.mean(), 0.65, color=colors[c], edgecolor=fs.INK, lw=0.5, zorder=1)
        if len(v) > 1:
            ax.errorbar(i, v.mean(), yerr=v.std(ddof=1), color=fs.INK,
                        lw=0.5, capsize=1.5, capthick=0.5, zorder=2)
        fs.replicates(ax, i, v)

    from matplotlib.ticker import MaxNLocator

    ax.set_xticks(range(len(conds)))
    ax.set_xticklabels(conds, rotation=45, ha="right")
    ax.set_ylabel(ylabel)
    # A short axis defaults to two ticks, which throws away the resolution the
    # reader needs to compare bars.
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10]))

    # Headroom so the n statement never sits on top of a bar or an error bar.
    top = ax.get_ylim()[1]
    ax.set_ylim(0, top * 1.22)

    # Significance goes on the panel (rule 6). The y-limit is recomputed
    # *after* placing it — a fixed headroom factor cannot hold brackets.
    tested = ""
    if comparisons:
        ceiling, note = _annotate_comparisons(ax, conds, groups, comparisons)
        ax.set_ylim(0, max(ax.get_ylim()[1], ceiling * 1.02))
        if any(c.ok for c in comparisons):
            # Say the printed p is the adjusted one — it differs from the raw
            # p, sometimes several-fold, and nothing else on the panel says so.
            tested = "\nWelch t-test, Holm–Šidák adjusted p" + (f", {note}" if note else "")

    n_text = (f"n = {sorted(ns)[0]} wells" if len(ns) == 1
              else f"n = {min(ns)}–{max(ns)} wells")
    heading = f"{n_text}; mean ± s.d.{tested}"
    if title:
        heading = f"{title}\n{heading}"
    ax.set_title(heading, fontsize=8)
    grow_for_labels(fig, ax, axes_height_mm=45.0)
    return fs.save(fig, out_stem)
