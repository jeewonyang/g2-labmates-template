---
name: figure-design
description: Render figures the way the Shapiro Lab renders them - 8 pt Arial, 0.5 pt lines, greyscale with a single orange accent - and audit them against the lab's rules before anyone sees them. Use whenever a LabSerf agent or skill is about to draw a chart, plot, gate review or schematic, and whenever a figure needs checking for font size, line width, palette, or the "reader can tell 99% without the legend" standard.
---

# Figure design

Every figure this repo produces is a draft of a manuscript figure. This skill
carries the lab's rules, the matplotlib style that implements the mechanical
ones, and the checker that proves a figure obeys them.

The normative source is **"Anatomy of a Manuscript", M. Shapiro, 2020-03-29**
(`FigureMaking/Anatomy of a Manuscript.docx`), section *Properties of good
figures*. `references/shapiro-figure-rules.md` reproduces those rules and adds
the palette and layout conventions measured from the lab's own figures and
theme files. **Read the rules file before making or judging a figure** — do not
work from memory.

## The rules in one breath

A reader can tell 99% of what is going on **without the legend and without the
main text**. Axes labelled succinctly, with units. A condition keeps its colour
in every panel. `n` and the statistics visible at a glance. 8 pt Arial for
everything, not bold. 0.5 pt lines for everything. Cropped to the essentials.

## Drawing

```python
import sys
sys.path.insert(0, ".claude/skills/figure-design/scripts")
import figstyle as fs

fs.use()                                  # the style sheet
fig, ax = fs.figure(45, 38)               # millimetres, the unit journals use
colors = fs.condition_colors(conditions, highlight="the one that matters")
ax.bar(i, mean, 0.65, color=colors[c], edgecolor=fs.INK)
fs.replicates(ax, i, values)              # show every n
fs.bracket(ax, 0, 2, y, fs.stars(p))      # significance where it is claimed
fs.save(fig, "out/gfp_fraction")          # writes .pdf AND .png
```

`fs.save` always emits a vector file alongside the PNG. The vector is what
goes into Illustrator or Affinity, and it is the only form the checker can
audit — **font size and stroke width are not recoverable from a raster image**.

### The palette

Greys carry the structure; **one orange carries the message**.

`INK` `GREY_DARK` `GREY` `GREY_LIGHT` `GREY_PALE` · `ACCENT` (`#F28A00`) ·
`BLUE` / `BLUE_LIGHT` for a secondary highlight · `CHANNEL_COLORS` for panels
about a fluorophore rather than a condition · `DENSITY_CMAP` (deliberately
greyscale, so the orange stays available for the gate drawn on top).

`condition_colors()` **does not guess the highlight**. Orange means "this is
the point of the figure", which only the person who knows the experiment can
say; with no highlight every condition gets a grey. Ramp grey → orange with
`fs.ramp(n)` for an ordered series rather than reaching for a rainbow.

### Traps that cost real time

- **Mathtext (`$10^3$`) is not Arial and not 8 pt.** matplotlib renders it in
  its own font set and shrinks exponents. The checker fails it. Use plain text.
- **Unicode superscripts are not safe either** — Arial has no U+2070 or
  U+2074, so macOS substitutes the Last Resort font. Write `1k`, `10k`.
- **A log axis emits mathtext tick labels by default.** Set a plain formatter.
- **`tight_layout` shrinks the axes, not the canvas.** Long rotated category
  names will squash a plot to a sliver at a fixed figure height. Measure the
  labels and grow the figure (see `flowplots.grow_for_labels`).
- **A short axis defaults to two ticks.** Set a `MaxNLocator` when the range
  is narrow, or the reader cannot compare bars.

## Every LabSerf figure goes through this skill

There are three routes, and between them they cover everything LabSerf draws:

| Who draws it | How it gets the lab style |
|---|---|
| New code, and the curated skill scripts (`flow-cytometry/*`, `ultrasound-analysis/make_run_report.py`, `auto_roi.py`, `view_bmode.py`) | `import figstyle as fs; fs.use()` and save with `fs.save()` / `fs.save_png()`. The ultrasound `report_lib.py` re-exports `fs`, and its `C`, `DOSE_COLORS` and `MPL_RC` now resolve to this palette and style sheet. |
| Shared legacy scripts in `Scripts/` (`us_proc_v5_addBURST_colormap.py`, `process_burst_acq.py`, `run_plate_compile_and_heatmaps.py`, …) | Run them through the wrapper, which leaves their source untouched: `python .claude/skills/figure-design/scripts/run_styled.py Scripts/<script>.py <args>` |
| Anything else | Load this skill, call `fs.use()`, and save through `fs.save()`. |

`run_styled.py` applies the style sheet, then at every save forces all text to
8 pt Arial (not bold) and all strokes to 0.5 pt, scales a canvas wider than a
double column down to 180 mm, removes gridlines, remaps matplotlib's stock
categorical colours (`tab10`, `tab20`, the default cycle) onto the lab cycle,
and writes a PDF beside every PNG. It has to act at save time because those
scripts hard-code `fontsize=` and `lw=` values that override the style sheet.
Any other colour a script sets deliberately is left alone.

### Two layout rules the migration added

- **Outlines on image data use `fs.OVERLAY`**, not orange: magenta for a
  sample ROI, cyan for noise, lime for a ceiling. Orange disappears against
  `hot`/`inferno` images. The colours are the same in every LabSerf image.
- **Past four groups, use small multiples, not one crowded panel.** One panel
  per group, that group in orange, every other group in pale grey behind it.
  No palette separates a dozen unordered conditions, and the legend ends up
  covering the data. `make_run_report.small_multiples` is the reference.

## Auditing

```bash
python .claude/skills/figure-design/scripts/check_figure.py fig.pdf [fig.svg ...] [--json]
```

Checks font family, font size, stroke width, canvas width against the
180 mm double-column limit, and flags colours outside the lab palette. Exit
status 1 on any violation, so it can gate a pipeline. It counts only line
widths in force when a *non-empty* path is actually stroked, so three things
that draw nothing are ignored: matplotlib's 1 pt reset before each text block,
the colorbar's hidden 0.01 pt background patch, and the bytes of the embedded
Arial font program. Marker XObjects inherit the width of their caller.

**It cannot judge anything that matters most**: whether the figure is readable
without its legend, whether labels overlap, whether the orange is doing one
job, whether a gate encloses the right population. That is the
**`figure-designer` agent**, which looks at the PNG. Run the checker first,
then the agent, then apply fixes **to the generating code** — never to the
output file — and re-render. Two rounds is normally enough; if the agent still
objects after two, tell the user what it objects to rather than looping.

## Files

    references/shapiro-figure-rules.md   the rules, with provenance
    scripts/shapiro.mplstyle             8 pt Arial, 0.5 pt, no top/right spine
    scripts/figstyle.py                  palette, mm sizing, n and stats helpers
    scripts/check_figure.py              the mechanical audit
    scripts/run_styled.py                run a legacy script under the lab style
