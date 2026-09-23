"""Run any matplotlib script under the lab figure rules, without editing it.

    python run_styled.py <script.py> [script arguments ...]

For the shared legacy scripts in `Scripts/` that LabSerf routes to. They are
used by people outside LabSerf, so their source stays untouched; this runner
makes their output match every other LabSerf figure instead:

  * applies the lab style sheet before the script runs;
  * at every save, conforms the figure — all text to 8 pt Arial, not bold; all
    strokes to 0.5 pt; a canvas wider than a double column scaled down to fit.
    This is needed on top of the style sheet because these scripts hard-code
    `fontsize=` and `lw=` values that override it;
  * writes a `.pdf` beside every raster it saves, so `check_figure.py` can
    audit the result and the figure can be opened in Illustrator.

Gridlines are removed. matplotlib's stock categorical colours (the default
cycle, `tab10`, `tab20`) are remapped onto the lab cycle; any other colour a
script sets explicitly is left alone — that is content, and the
figure-designer agent is where it gets judged.
Image data (`imshow`, `pcolormesh` fills) is untouched.
"""

from __future__ import annotations

import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import matplotlib  # noqa: E402
import figstyle as fs  # noqa: E402

from matplotlib.collections import Collection  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.text import Text  # noqa: E402

RASTER = {"png", "jpg", "jpeg", "tif", "tiff"}
MAX_WIDTH_IN = (fs.DOUBLE_COLUMN - 2) / 25.4
FONT = ["Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"]


def _positive(v) -> bool:
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


#: Lab categorical cycle (same as `axes.prop_cycle` in shapiro.mplstyle).
LAB_CYCLE = [fs.INK, fs.BLUE, fs.GREY, fs.BLUE_LIGHT, fs.GREY_LIGHT, fs.GREY_DARK]


def _stock_palette_map() -> dict[str, str]:
    """matplotlib's stock categorical colours -> the lab cycle, by index.

    Legacy scripts build series colours from `plt.cm.tab10`/`tab20` or the
    default cycle. Those are matplotlib defaults, never a lab choice, so they
    are remapped; any other explicit colour is left as the script set it.
    """
    from matplotlib import cm, colors as mcolors
    out: dict[str, str] = {}
    for name in ("tab20", "tab10"):          # tab10 last: it wins on overlap
        cmap = cm.get_cmap(name)
        for i in range(cmap.N):
            out[mcolors.to_hex(cmap(i)).lower()] = LAB_CYCLE[i % len(LAB_CYCLE)]
    return out


_STOCK = None


def _remap(c):
    """Lab colour for a stock-palette colour; None if `c` is anything else."""
    from matplotlib import colors as mcolors
    try:
        rgba = mcolors.to_rgba(c)
    except (ValueError, TypeError):
        return None
    lab = _STOCK.get(mcolors.to_hex(rgba).lower())
    return mcolors.to_rgba(lab, rgba[3]) if lab else None


def _recolour(fig: Figure) -> None:
    global _STOCK
    if _STOCK is None:
        _STOCK = _stock_palette_map()
    for ln in fig.findobj(Line2D):
        for get, set_ in ((ln.get_color, ln.set_color),
                          (ln.get_markerfacecolor, ln.set_markerfacecolor),
                          (ln.get_markeredgecolor, ln.set_markeredgecolor)):
            new = _remap(get())
            if new is not None:
                set_(new)
    for p in fig.findobj(Patch):
        for get, set_ in ((p.get_facecolor, p.set_facecolor),
                          (p.get_edgecolor, p.set_edgecolor)):
            new = _remap(get())
            if new is not None:
                set_(new)
    for c in fig.findobj(Collection):
        for get, set_ in ((c.get_facecolors, c.set_facecolors),
                          (c.get_edgecolors, c.set_edgecolors)):
            cols = get()
            if len(cols) == 0:
                continue
            mapped = [_remap(v) for v in cols]
            if any(m is not None for m in mapped):
                set_([m if m is not None else tuple(v) for m, v in zip(mapped, cols)])


def conform(fig: Figure) -> None:
    """Bring one figure to 8 pt Arial / 0.5 pt lines / <= 180 mm wide."""
    w, h = fig.get_size_inches()
    if w > MAX_WIDTH_IN:
        s = MAX_WIDTH_IN / w
        fig.set_size_inches(w * s, h * s)

    for t in fig.findobj(Text):
        t.set_fontsize(8)
        t.set_fontweight("normal")
        t.set_fontfamily(FONT)
    for ln in fig.findobj(Line2D):
        if _positive(ln.get_linewidth()):
            ln.set_linewidth(0.5)
        if _positive(ln.get_markeredgewidth()):
            ln.set_markeredgewidth(0.5)
    for p in fig.findobj(Patch):
        if p is fig.patch:
            continue
        if _positive(p.get_linewidth()):
            p.set_linewidth(0.5)
    for c in fig.findobj(Collection):
        lws = c.get_linewidths()
        if len(lws) and any(_positive(v) for v in lws):
            c.set_linewidths([0.5 if _positive(v) else 0 for v in lws])

    _recolour(fig)

    # No gridlines anywhere (lab layout rule); legacy scripts switch them on.
    for ax in fig.axes:
        ax.grid(False)

    # Re-run tight layout for the new sizes, unless the script chose
    # constrained layout (which re-solves itself at draw time).
    if not fig.get_constrained_layout():
        try:
            fig.tight_layout()
        except Exception:  # an unusual layout is better saved than crashed
            pass


_original_savefig = Figure.savefig


def _styled_savefig(self, fname, *args, **kwargs):
    conform(self)
    result = _original_savefig(self, fname, *args, **kwargs)
    if isinstance(fname, (str, os.PathLike)):
        root, ext = os.path.splitext(os.fspath(fname))
        fmt = (kwargs.get("format") or ext.lstrip(".")).lower()
        if fmt in RASTER:
            vector = {k: v for k, v in kwargs.items() if k not in ("format", "dpi")}
            _original_savefig(self, root + ".pdf", format="pdf", **vector)
    return result


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].endswith(".py"):
        print(__doc__)
        return 2
    script = os.path.abspath(sys.argv[1])
    fs.use()
    Figure.savefig = _styled_savefig
    # The script sees itself as __main__, with its own argv and directory.
    sys.argv = [script] + sys.argv[2:]
    sys.path.insert(0, os.path.dirname(script))
    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    sys.exit(main())
