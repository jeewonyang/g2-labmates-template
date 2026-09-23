# Shapiro Lab figure rules

The normative source is **"Anatomy of a Manuscript", Mikhail Shapiro, 2020-03-29**
(`FigureMaking/Anatomy of a Manuscript.docx`), section *Properties of good
figures*. Everything in "The rules" below is quoted or directly derived from it.
The palette and layout conventions in "House style" were measured from the lab's
own figures and theme files and are conventions, not doctrine — deviate when the
science calls for it, but say so.

## The rules (from the tutorial, verbatim intent)

1. **The reader can tell 99% of what's going on without looking at the legend
   and without reading the main text.** This is the top-level test. If a panel
   needs prose to be intelligible, it is not finished.
2. **Mix illustrations with results, where appropriate.** A schematic of the
   construct or the assay next to the quantification carries more than either
   alone.
3. **Label axes succinctly but clearly.**
4. **Match colors across sample types/conditions.** A condition keeps its color
   in every panel of every figure in the manuscript.
5. **Add informative labels.** Name the populations, the conditions, the gates —
   on the panel, not in the caption.
6. **The n= and the statistical significance are visible at a glance.**
7. **Visually appealing. Makes you want to look at it. Makes editors want to see
   it in their journals.**
8. **Best practices: 8 pt Arial for everything (not bold), 0.5 pt line widths
   for everything. Crop images to show only the essentials.**
9. **Copy the formatting from a previous successful manuscript** — a Prism,
   Illustrator or Affinity file from the lab.

Canonical external examples cited in the tutorial:
- <https://www.nature.com/articles/nchembio.2233/figures/1>
- <https://www.nature.com/articles/s41563-018-0023-7/figures/5>

Rule 9 in practice — the lab's own template, `FigureMaking/Cell Nature Cell
templates.ai`, is an A4 artboard (210 × 297 mm) and embeds exactly one font,
**ArialMT**. That is measured, not inferred: it is the rule in the tutorial,
enforced in the file the lab actually builds figures in. Icon libraries for
schematics are in `FigureMaking/Inna's Adobe Illustrator Icons/`
(`Biology_Anatomy`, `Cell_shapes`, `Lab_Materials`, `Molecules_Proteins`,
`Graphic_Design_Assets`).

## House style (measured from lab figures)

### Palette

Measured from the lab's schematic figures and `FigureMaking/GV_theme.thmx`.
The lab's visual identity is **greyscale carrying the structure, one orange
accent carrying the message**, with a light blue for a secondary highlight.

| Token | Hex | Use |
|---|---|---|
| `ink` | `#000000` | strokes, text, axes |
| `grey_dark` | `#646464` | secondary text, de-emphasised series |
| `grey` | `#969696` | neutral / control series |
| `grey_light` | `#C8C8C8` | fills, background series |
| `grey_pale` | `#DDDDDD` | panel fills, faint fills |
| `accent` | `#F28A00` | **the point of the figure** — the ON state, the hit, the condition that matters |
| `accent_bright` | `#FF9A00` | same role in illustrations/schematics |
| `blue` | `#5CB2C4` | secondary highlight (strokes) |
| `blue_light` | `#A2D5E0` | secondary highlight (fills) |

Rules of use:
- **Orange is a scarce resource.** One accent per panel. If everything is
  orange, nothing is.
- Controls and negatives are grey. The experimental condition that the panel
  exists to show is orange.
- For an ordered series (a dose, a timecourse), ramp grey → orange rather than
  reaching for a rainbow.
- Fluorescence channels, when a panel is *about* the channel rather than the
  condition, may use channel-identity colors (BFP blue, GFP green, OFP orange,
  iRFP dark red). Never mix the two schemes in one panel.
- **Outlines drawn on image data** (ultrasound, microscopy) use the overlay set
  `figstyle.OVERLAY` — magenta sample, cyan noise, lime ceiling — because
  orange vanishes against `hot`/`inferno` images. Same colours in every image.
- **Unordered categories get one grey**, not a ramp: a ramp implies an order
  and gives the same condition different greys in different groups.
- **Past four groups, small multiples**: one panel per group, that group in
  orange, the rest in pale grey behind it. One crowded panel with a dozen
  near-identical colours and a legend over the data fails rule 1.
- Series drawn without an explicit colour use the default cycle ink, blue,
  grey, light blue, light grey, dark grey — never orange, which is only ever
  assigned deliberately.

### Type and line

- **Arial, 8 pt, never bold.** Panel letters (a, b, c) are the one exception
  the journals impose — those are bold, set by the layout program, not by the
  plotting script.
- **0.5 pt for every line**: axes, ticks, gate outlines, error bars, leaders.
- Title case nowhere. Axis labels are sentence case: "GFP+ cells (%)".
- Units always in parentheses after the quantity: `Median iRFP (a.u.)`.

### Layout

- White background, no grid, no top or right spine.
- Ticks point outward, on the left and bottom only.
- No panel frame, no legend box, no drop shadows, no gradients.
- Legends sit inside the axes with no frame, or become direct labels on the
  series — direct labels are better (rule 1).
- Crop to the essentials: no empty margins, no decorative whitespace.
- Single-column figures are 88 mm wide, double-column 180 mm (Nature).
  Individual panels are usually 30–45 mm.

### Statistics on the panel

- Show every replicate as a point over the summary bar/mean — the lab plots
  `n` rather than hiding it.
- State `n` and what it counts ("n = 3 wells") on the panel or in the axis label.
- Significance as the bracket + asterisks, or better, the p-value printed.
- Say which test in the caption; show the result on the panel.

## Applying this to auto-generated figures

`scripts/shapiro.mplstyle` sets the type, line widths, spines and ticks.
`scripts/figstyle.py` adds the palette, the condition→color assignment, figure
sizing in millimetres, and the `n`/significance annotation helpers.

Every figure must be emitted as **both PDF/SVG and PNG**. The vector file is
what goes into Illustrator/Affinity, and it is the only form
`scripts/check_figure.py` can audit — font family, font size and stroke width
are not recoverable from a PNG.
