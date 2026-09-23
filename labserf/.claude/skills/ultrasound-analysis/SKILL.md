---
name: ultrasound-analysis
description: Analyze Verasonics ultrasound acquisitions from this lab (L22-14vX and GE6-24D probes) - identify what kind of data a raw folder holds, run the right xAM / B-mode / BURST / Doppler pipeline, and produce plots, images, videos, and GraphPad Prism import tables. Use whenever a folder of Imgdata_Vseq*.mat, image_block_*.mat, or fUS_block_*.bin files is involved, or when asked about probe parameters, pressure calibration, SBR/CNR/BURST metrics, or 96-well acoustic plate reader results.
---

# Ultrasound data analysis

This skill is self-contained: the probe tables, pressure calibrations, folder
layouts, metric definitions and measured depth bands below were all derived from
the lab's example datasets and are written down here. **You never need to open
`ExampleData/` to process a new acquisition** — point the tools at the raw folder
the user names. Values quoted from the example datasets are provenance, marked as
such, not lookups to repeat.

## The LabSerf workflow — three stages, always

Every dataset runs the same arc. Do not stop after stage 1: a processed CSV is
not a result, and a result the user has to interpret alone is half a deliverable.

**1 · Run the pipeline.** Classify the folder, infer ROIs, process, export.
Outputs land beside the data (`processed_csv/`, `fig/`, `images/`, `roi/`, Prism
tables). Show the ROI review image before trusting any number.

**2 · Report the result.** Write into `<run>/AI_analysis/` — see the layout rule
below.
   - `RESULTS.md` — headline, the numbers, your interpretation, and QC. State
     what the data shows *and what it cannot show*.
   - an interactive artifact — publish it and hand over the link.
   Both carry the analysis, not just the figures. Say which effects are real,
   which are noise, and which are limits of the design.

**3 · Suggest the next round.** Write `NEXT_EXPERIMENTS.md`. Each proposal names
the specific observation that motivates it and, where it matters, a decision rule
set in advance. Include an acquisition-settings table of what to change and what
to keep. A finding that implies a design change is only useful if that change is
written down.

**Read the negative-result memory before stage 3, and write to it after any
null or failed run** — a signal that never rose above blank, a voltage ramp
that never reached collapse, a session lost to a bad probe contact:

```bash
N=.claude/skills/scientific-advisor/scripts/negative_results.py
python $N check --tags ultrasound,<probe>,<system> --query "<the idea>"
python $N add --title "..." --outcome below-detection --assay ultrasound \
    --tried "<probe, mode, voltage, dox, plate>" --observation "<dB vs blank, n>" \
    --why "<hypotheses>" --next "..." --run <run> --source <run>/AI_analysis/RESULTS.md
```

Use `technical-failure` — not `no-effect` — when the acquisition itself failed.
Only `no-effect` and `below-detection` say anything about the biology.

## Layout rule: one AI_analysis per acquisition folder

**Every acquisition folder carries its own analysis, in its own
`<run>/AI_analysis/`.** A run folder should be self-describing — someone opening
it a year later gets the data, the ROIs, and the reading of it in one place,
without having to know which other run's folder the write-up ended up in.

    <run>/
      plate/ ...                     pipeline outputs, beside the data
      AI_analysis/
        stats.json                   every number the report quotes
        RESULTS.md                   the analysis for THIS run
        dose_response.png            standard figures
        collapse.png
        qc.png                       (only when there are 2 plate groups)
        assets/                      images the report embeds
        scripts/                     run-specific generators, if any
        cross_run/                   analyses spanning several runs

Start it with the generic generator, which writes `stats.json`, the standard
figures and a `RESULTS.md` scaffold, then fill in the interpretation:

```bash
python .claude/skills/ultrasound-analysis/scripts/make_run_report.py "<run folder>" \
    --group-by <condition column>
```

It never overwrites an existing `RESULTS.md`, so it is safe to re-run after
reprocessing. `--group-by` picks the condition column for the curves and tables
(auto-detected if omitted); `--volt` sets the reference voltage.

**Work that spans several runs** — a synthesis, a comparison figure, a slide, a
collaborator draft — has no single home, so put it in `cross_run/` inside the
**newest run it covers**, with a `README.md` naming the runs. Do not scatter
single-run conclusions into another run's folder.

## Shared code lives in the skill, not in the run folder

Anything reusable belongs in `.claude/skills/ultrasound-analysis/scripts/` so the
next dataset gets it for free. `report_lib.py` is the shared layer:

```python
import sys; sys.path.insert(0, "<...>/.claude/skills/ultrasound-analysis/scripts")
from report_lib import Run, C, DOSE_COLORS, MPL_RC

r = Run("<run folder>")
d = r.pre()                          # pre-collapse rows, ramp voltages only
X, Z, db = r.load_xam(scan, 12.0)    # averaged frame, in dB
mpa = r.pressure(12.0)               # measured calibration, interpolated
crop, extent, roi = r.well_crop(scan, "well1", 12.0)
```

A run-specific script should be a thin file in `<run>/AI_analysis/scripts/` that
imports this and adds only what is unique to that run. If you find yourself
copying a helper between run folders, move it into `report_lib.py` instead.

## Figures follow the lab rules — same as every LabSerf figure

Everything this skill draws uses the `figure-design` skill: 8 pt Arial, 0.5 pt
lines, greys with one orange accent, PDF written beside every PNG. The curated
scripts (`make_run_report.py`, `auto_roi.py`, `view_bmode.py`) do this
themselves, and `report_lib`'s `C` / `DOSE_COLORS` / `MPL_RC` now resolve to
the lab palette and style sheet. The legacy scripts in `Scripts/` are shared
with people outside LabSerf, so they are not edited — **run them through
`run_styled.py`**, as every command in `references/pipelines.md` now does.

Two conventions specific to ultrasound images: ROI outlines use
`fs.OVERLAY` (magenta sample, cyan noise, lime ceiling), because orange
vanishes on the `hot` colormap; and the dose-response plot switches to small
multiples past four groups. Audit with
`.claude/skills/figure-design/scripts/check_figure.py <fig>.pdf`, then have the
`figure-designer` agent look at the PNG.

## Start here: identify the folder before touching it

Never guess the pipeline from a folder name. Run the classifier — it reads only
metadata (never loads image stacks), so it finishes in seconds even on a 6 GB tree:

```bash
python .claude/skills/ultrasound-analysis/scripts/identify_dataset.py "<folder>"
```

It reports probe, acquisition mode, layout, voltage sequence, collapse scheme,
and prints the exact command to run next with the metadata CSV, well map, and
Doppler folder already filled in from disk. Add `--json` for machine-readable
output when driving further steps.

## The four acquisition modes

| Mode | Purpose | On disk |
|---|---|---|
| **B-mode** | background structure / sample loading | never separate — every `Imgdata_*.mat` holds `ImgData.Imb` alongside `ImgData.Imx` |
| **xAM** | nonlinear GV signal; the main measurement | `Imgdata_Vseq*.mat`, voltage ramp or timecourse |
| **BURST** | destructive one-shot, most sensitive | `image_block_###.mat` (v7.3 HDF5) |
| **Doppler** | vasculature background to overlay under xAM | `UF.mat` + `fUS_block_###.bin` → `Dop.mat` |

## Routing table

| What you see in the folder | Layout | Command |
|---|---|---|
| `plate/plate_P_*/plate_P_*_A01/Imgdata_*.mat`, `P.pitchSI = 100 µm` | 96-well, L22, 1 well/position | `us_proc plate_l22` |
| same but `P.pitchSI = 135 µm` | 96-well, GE, **3 wells/position** | `us_proc plate_ge --well_map …` |
| flat `Imgdata_Vseq*.mat`, phantom/slide naming | manual | `us_proc manual --n_rois 2` |
| flat `Imgdata_Vseq*.mat`, mouse/tumor/timepoint naming | in vivo, single imaging plane | `us_proc in_vivo --doppler_dir …` |
| `image_block_###.mat` | BURST | `process_burst_acq.py` |
| `UF.mat` + `fUS_block_*.bin` | Doppler | `Doppler_processing_JWY_bothProbes.m` (MATLAB) first |
| many sibling folders of the above | session | process each, then concatenate |

`us_proc` = `Scripts/us_proc_v5_addBURST_colormap.py`.

Full commands, flags, and the complete output inventory for each:
**`references/pipelines.md`** — read it before running anything, it also lists
the scripts in this repo that are broken and must not be used.

## The two probes

The lab recently moved from **Verasonics L22-14vX** to **GE6-24D**. They differ in
element count, pitch, transmit frequency, aperture, depth window, wells per
field of view, Doppler pixel grid, and pressure calibration — sharing only the
workflow. When a GE case has no worked example, copy the *structure* of the L22
example but never its numbers.

`P.pitchSI` is the reliable fingerprint: 100 µm = L22, 135 µm = GE.

Parameter tables, CNC scan geometry, GE auto-depth interface tracking, and
Doppler grid differences: **`references/probes.md`**.

## Voltage → pressure

Portable calibration CSVs (no MATLAB needed) in `calibration/`:
- `GE624D_pressure_calibration.csv` — MPa, xAM and pAM, aperture 35/45/65/85,
  depths 5–10 mm, 12.5 and 15.625 MHz
- `L22_L10_pressure_calibration.csv` — converted to MPa, four calibration dates

The GE plate operating point is aperture 35, 12.5 MHz, ~5 mm.
**Ignore `P.HP` inside GE `.mat` files** — it still names the old L22 curve.
`scripts/to_prism.py --pressure` does the interpolation for you.

## Metrics

SBR, SNR, CNR, AM/B-mode ratio, BURST, nBURST — and two generations of code that
define CNR differently and mix dB with linear units in the same CSV.
Read **`references/metrics.md`** before interpreting or comparing any number.

The one thing to remember: in `us_proc` output, uncorrected `sbr_x`/`snr_x`/`cnr_x`
are in **dB**, but the blank-corrected `*_corr` versions are **plain ratios**.

## Raw file layouts

`.mat` variable names, array shapes and orientations, the `fUS_block` reshape,
the `P` struct field reference, and companion-CSV conventions:
**`references/data-formats.md`**.

## ROIs: infer them, then review the picture

Do not ask the user to draw ROIs for plate, manual, or BURST data. Generate them:

```bash
python .claude/skills/ultrasound-analysis/scripts/auto_roi.py "<folder>"
```

It infers mode from the folder, fits ROIs using image evidence plus a geometry
prior (xAM ~5 mm deep, BURST ~8 mm or `P.txFocus_mm`; GE = three U-bottom wells
left/middle/right, L22 plate = one centred well, L22 manual = circular
inclusions), writes the ROI JSON where each pipeline already looks for it, and
**always writes a review image**. Surface that image to the user every time —
automating the drawing only works if the checking still happens.

Three corrections matter enough to know about without opening the reference:

- **BURST is detected in linear intensity, not dB.** The BURST reference is a
  background-subtracted difference clipped at zero, so ~30% of its pixels are
  exact zeros. In dB those become −200, the row-wise background suppression
  then flips between ~−200 and ~+100 per row, and the detector ends up
  favouring the *emptier* rows below each disc. Before this was fixed, signal
  ROIs sat anywhere from 1.9 mm above to 1.5 mm below their discs and up to
  1.4 mm off sideways; in linear intensity all 24 phantom ROIs land within
  0.09 mm of the disc centroid. The circles come out slightly inside the disc
  (radius ~0.87 vs ~1.04 mm), which keeps the dimmer rim out of the mean.
  **Any `roi_defs.json` made by `auto_roi` before 2026-09-20 for BURST data
  used the old placement — regenerate it (`--force`) and reprocess.**

- **xAM dies below the transmit focus, B-mode does not.** Sizing a box on B-mode
  alone runs it into a dead zone and costs 2–3 dB. The tool measures the usable
  depth band once per plate from the wells that have signal and clamps every ROI
  to it — measured per dataset, so no stored value is assumed. (It came out at
  GE 3.89–5.52 mm and L22 4.18–6.01 mm on the datasets the skill was built from,
  which is a useful sanity range, not a default.)
- **Under-loaded wells hold a concave meniscus**, so the nominal rectangle
  contains air and a real well reads as weak. Each box is trimmed until at least
  `--min-fill` (80%) of it actually contains sample, and anything still short is
  flagged `UNDER-FILLED` in the console.

For plates it writes two contact sheets: `auto_roi_review_xAM.png` (zoomed to the
sample ROIs — use this to confirm the box covers the signal) and
`auto_roi_review_Bmode.png` (full depth — use this to check noise and ceiling).

Then run the pipeline unattended with `--roi_per_well` and *without*
`--overwrite_roi`, so `us_proc` loads the files instead of opening a window.

**In-vivo is the exception**: tumour and contralateral ROIs differ per animal and
must be drawn by hand. One `shared_rois.json` at the `Processed-Data/` level then
carries them across every timepoint of that session.

Details, priors, tunables, and the hand-vs-auto validation numbers are in
`references/pipelines.md` § Auto-ROI.

## Producing deliverables

Every pipeline writes its own figures, PNGs, MP4s and CSVs — see
`references/pipelines.md` for the per-mode inventory. Two extra steps on top:

**96-well heatmaps and wide pivots**
```bash
python .claude/skills/figure-design/scripts/run_styled.py Scripts/run_plate_compile_and_heatmaps.py --plate-dir <…>/plate --metadata <…>.csv
```

**Quick B-mode look at any folder** (file, scan, plate, run or session)
```bash
python .claude/skills/ultrasound-analysis/scripts/view_bmode.py "<folder>" [--rois] [--overlay-xam] \
    [--voltage 12 | --frame 7 | --all-frames --video] [--depth 2,8] [--show]
```
Writes `<folder>/bmode_view/` with one PNG per scan and a contact sheet on a
common dB scale (default 50 dB range); `--all-frames` gives a per-frame montage
and, with `--video`, an mp4; `--show` opens a window with a frame slider. It
reads ROI JSON from wherever the pipelines left it and never modifies the input.

**GraphPad Prism import tables**
```bash
python .claude/skills/ultrasound-analysis/scripts/to_prism.py <results.csv> \
  --metric cnr_x_corr [--x frame_idx] [--pressure --probe GE624D --aperture 35 --depth 5 --tx-freq 12.5]
```
Emits a replicate-wide table (rows = voltage or frame, columns = `<group>__r1..rN`)
for a Prism *Grouped* table, plus a mean/SEM/n table. Grouping columns are
auto-detected from the metadata join (`sample` + `condition`) and can be
overridden with `--group`.

## Staying self-contained

`scripts/check_self_contained.py` enforces the guarantee above. It scans the tool
sources for any `ExampleData` mention or hardcoded repo path, then runs each tool
against a folder you name under a Python audit hook that records every file
opened — any read under `ExampleData/` fails the check.

```bash
python .claude/skills/ultrasound-analysis/scripts/check_self_contained.py \
  --data_dir "<any real acquisition folder outside ExampleData>"
```

Non-zero exit on failure, so it can gate a commit. Run it after adding a tool or
a calibration file.

## Working rules

- **Classify first, then act.** The classifier's `collapse` field tells you
  whether blank correction will actually happen; `frames_per_voltage` tells you
  whether to average or to plot by frame.
- **Infer ROIs, then show the review image.** `auto_roi.py` removes the manual
  drawing step for plates, manual/phantom and BURST data. Always put the review
  image in front of the user rather than just reporting numbers. A saved
  `rois.json` / `shared_rois.json` is reloaded automatically; re-drawing ROIs
  mid-timecourse invalidates the comparison, so only pass `--overwrite_roi`
  when asked to.
- **`P.Vseq` / `P.seed` are per folder, never per probe.** They can differ
  between wells of one plate. `us_proc` already reads them per acquisition and
  uses post-collapse frames for blank correction whenever any exist; the
  classifier warns when a plate carries more than one sequence. Group differing
  sequences separately before pooling them as replicates.
- **Never re-run a pipeline that would overwrite existing ROIs or processed
  outputs without saying so first.** Raw acquisition folders are irreplaceable.
- **Never write into `ExampleData/`.** It is reference material. Every tool
  writes beside the data folder it was pointed at, so simply do not point them
  there.
- **The ramp is itself destructive — pick the reference voltage, don't inherit
  it.** Collapse is not only the dedicated collapse shot: every step of a
  voltage ramp removes some gas vesicles, and it removes most from the wells
  that have most. Any quantity fitted across conditions at a high ramp voltage
  is therefore biased. Measured on `260904_CRE-PPV_772` (GE plate, 6→20 V): the
  pooled Dox EC50 refitted independently at each voltage holds at
  0.043–0.051 µg/mL over **10–15 V**, then drifts up ~50 % to 0.073 by 20 V.
  So: **refit the quantity at every ramp voltage and report from the window
  where it is flat**, rather than from one voltage chosen up front. A number
  that moves with voltage is an artefact of the ramp, not a property of the
  sample. `--volt` on `make_run_report.py` defaults to 12 — a sane mid-ramp
  value, but confirm it against the stability window for the run in hand.
- **"Still rising at the top of the ramp" does not mean nothing collapsed.**
  `make_run_report.py` writes *"The ramp never reached collapse"* whenever no
  condition turns over. That is a statement about the *net* curve only: pressure
  driving signal up can outrun collapse taking it away, so the signal climbs
  while vesicles are being destroyed underneath. Treat the line as "no collapse
  threshold is measurable here", never as "no collapse occurred".
- **Report units.** Say "CNR (dB)" or "CNR (linear, blank-corrected)", never
  bare "CNR".
- **State n.** GE plates give n = 3 wells per scan position; L22 gives n = 1.
  Voltage-averaging collapses frames-per-voltage into the mean, so the replicate
  count in a figure comes from wells, not frames.
