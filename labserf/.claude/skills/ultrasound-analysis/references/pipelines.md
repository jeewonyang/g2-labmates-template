# Pipelines: what to run, in what order, and what comes out

Paths below are relative to the repo root. Dataset names appearing in worked
numbers (`260813_CRE-PPV_772`, `251106_Transient_l22nonx_TEVko`, …) record where a
figure came from; they are not inputs to look up.
`us_proc` = `Scripts/us_proc_v5_addBURST_colormap.py` — the current unified
Python entry point, four subcommands: `manual`, `in_vivo`, `plate_l22`, `plate_ge`.

---

## The script landscape

There are ~15 years of overlapping scripts. These are the ones that matter:

| Purpose | Use this | Notes |
|---|---|---|
| xAM ramp — all four layouts | `Scripts/us_proc_v5_addBURST_colormap.py` | current; v1–v4 are its ancestors, don't use them |
| Plate heatmaps + wide pivots | `Scripts/run_plate_compile_and_heatmaps.py` | see integration gap below |
| BURST | `Scripts/US_processing/process_burst_acq.py` | **not** `_v2.py` — that file has a syntax error |
| Doppler reconstruction | `Scripts/Processing/Doppler_processing_JWY_bothProbes.m` | MATLAB; handles both probes |
| Doppler → npz for Python overlay | `Scripts/US_processing/process_doppler_parent.py` | |
| GE xAM acquisition (CNC) | `Scripts/Verasonics_Aquisition/Setup_GE624_CNC_xAM_v11_ID_edits_autoDepth.m` | |
| L22 xAM acquisition (CNC) | `Scripts/Verasonics_Aquisition/SetUpL22_14v_64TX_Ramp_v6_LiveDisp_JWY.m` | |
| GE probe definition | `Scripts/Acquisition/computeTrans_GE6_24_v3.m` | latest of five versions |
| fUS acquisition | `Scripts/Acquisition/fUS_GE_JWY.m` / `L22_fUSloop_JWY.m` | |

Superseded but still the origin of numbers in old figures: the MATLAB chain
`USScripts/AllDatesProc.m` → `RegUSImageProc_ZJ_v3.m` → `data_plotter_for_v5*.m`
(recognisable by its `rawSBR*.csv` / `SBR-Bmode*.csv` / `Voltage_*V/` output
layout), and
`proc_well_xAM_v2.py` (also syntactically broken).

---

## 1. Plate — L22 (one well per scan position)

```bash
python .claude/skills/figure-design/scripts/run_styled.py Scripts/us_proc_v5_addBURST_colormap.py plate_l22 \
  --data_dir <date_folder>/plate \
  --metadata_csv <metadata.csv> \
  --save_images 10.0 --colorscale_min 30 --colorscale_max 80 \
  --xlsx
```

One noise ROI + one sample ROI, drawn interactively on the **first** well and
reused for all the rest (`--roi_per_well` to draw each one). ROIs are saved to
`plate/roi/shared_rois.json` and reloaded on subsequent runs unless
`--overwrite_roi`.

Outputs under `plate/`:
```
processed_csv/  plate_P_1_1_A01_results.csv      per position, voltage-averaged
                all_wells_combined.csv           every position
                all_wells_with_metadata.csv      joined to the metadata CSV
                all_wells_combined.xlsx          (--xlsx)
                run_notes.txt                    P.notes, if readable
fig/            sbr_x, snr_x, cnr_x, sbr_b, snr_b, am_bmode_ratio
                × {, _corr} × {.pdf, .png}       metric vs voltage, mean ± SEM by group
images/         <sample_condition>_R<n>_xAM_<V>V.png
roi/            shared_rois.json
videos/         <well>_xAM.mp4                   (--save_video)
```

## 2. Plate — GE (three wells per scan position)

```bash
python .claude/skills/figure-design/scripts/run_styled.py Scripts/us_proc_v5_addBURST_colormap.py plate_ge \
  --data_dir <date_folder>/plate \
  --well_map <well_map.csv> \
  --metadata_csv <metadata.csv> \
  --save_images 10.0 --colorscale_min 30 --colorscale_max 80 \
  --xlsx
```

Differences from `plate_l22`:
- **Four ROIs per position**: noise + `well1`,`well2`,`well3` + `ceiling`.
- Sample ROIs are drawn on the **B-mode** image (well walls are clearer there),
  not on xAM. The brightest-frame search skips the top 20 % of rows so the
  ceiling echo does not win.
- `--well_map` remaps `well1/2/3` to real 96-well IDs; without it you get
  `A01_w1` style placeholders and the metadata join will not work.
- The metadata join strips a trailing `_W<n>` from `well_id`, so the three wells
  at a position become n = 3 replicates of one metadata row.
- One image PNG is written per scan position (covering all three wells), titled
  with the deduplicated sample/condition labels of the three.

## 3. Manual / phantom (flat folder, 2 sample ROIs)

```bash
python .claude/skills/figure-design/scripts/run_styled.py Scripts/us_proc_v5_addBURST_colormap.py manual \
  --data_dir "<acquisition folder>" \
  --n_rois 2 --roi_labels left,right \
  --save_images 6.0 --save_video --xlsx
```

Outputs go to `<parent>/Processed-Data/<scan_name>_{processed,fig,roi,images,videos}/`.
Run it once per acquisition folder; each gets its own ROI set
(`<scan>_roi/rois.json`).

## 4. In vivo (flat folder, optional Doppler background)

```bash
# 1. reconstruct Doppler first (MATLAB), once per plane
#    edit Path at the top of the script, then run it — writes Dop.mat beside UF.mat
matlab -batch "run('Scripts/Processing/Doppler_processing_JWY_bothProbes.m')"

# 2. then process each xAM acquisition
python .claude/skills/figure-design/scripts/run_styled.py Scripts/us_proc_v5_addBURST_colormap.py in_vivo \
  --data_dir "<t10_postInjection_...>" \
  --doppler_dir "<Doppler/6V-Doppler-2.0mm_imagingPlane_pre>" \
  --roi_labels tumor,contralateral \
  --plot_by_frame \
  --save_images 7.0 --save_video --xlsx
```

- ROI selection and every figure use a composite: B-mode (gray) → Doppler
  (semi-transparent) → xAM (hot). Without `--doppler_dir` it falls back to
  B-mode + xAM.
- By default **one** `shared_rois.json` is written at the `Processed-Data/` level
  and reused across every timepoint folder under the same parent — which is what
  you want for a timecourse, since the ROI must stay fixed. `--roi_per_folder`
  overrides this.
- Use the Doppler folder whose name contains `imagingPlane`; the `0.0mm`…`2.2mm`
  sweep folders are a plane survey, not the imaging plane.
- `--plot_by_frame` puts frame index on x and voltage on a secondary right axis —
  correct for timecourse acquisitions where every frame is the same voltage.

A timecourse session (e.g. `Mouse4_U87/`) is dozens of sibling folders
`t0-5_injection_…`, `t5_postInjection_…`, `t10_…`. Process each, then
concatenate the `*_results_avg.csv` files with a timepoint column parsed from
the folder name to build the timecourse.

## 5. BURST

```bash
python .claude/skills/figure-design/scripts/run_styled.py Scripts/US_processing/process_burst_acq.py "<BURST folder>" \
  --signal-roi-shape rect --noise-roi-shape rect \
  --doppler-npz "<...__doppler_data.npz>"     # optional overlay
```

Interactive: draw one noise ROI, then one or more signal ROIs (it asks after
each). ROIs save to `<output>/roi_defs.json` — pass `--roi-file` pointing at an
existing one to reuse a common ROI set across a batch of sibling folders, which
is the normal case (`BURSTProc.m` used two fixed sample ROIs per acquisition).

Outputs in `<burst folder>/output/`:
`burst_curve_wide.csv` (per-frame ROI means, with a `phase` column of
pre/collapse/post), `burst_summary_wide.csv` and `_long.csv`
(BURST, nBURST, SNR, CNR per ROI), `burst_signal_frame.png`,
`burst_background_mean.png`, `burst_diff.png`, `burst_diff_clean.png`,
`burst_data.npz`, and `overlays/` if a Doppler npz was given.

Loop over sibling folders with a shell loop; there is no batch driver.

## 6. Auto-ROI (skip the manual drawing)

```bash
python .claude/skills/ultrasound-analysis/scripts/auto_roi.py "<folder>" [--mode ...]
```

Infers ROI placement from the image plus a geometry prior, writes the ROI JSON
in the format each pipeline already reads, and **always writes a review image**.
Mode is inferred from the folder when not given.

| Mode | ROIs produced | Shape | Written to |
|---|---|---|---|
| `plate_ge` | noise + well1/2/3 + ceiling | rect | `<plate>/roi/<well>_rois.json` |
| `plate_l22` | noise + sample | rect | `<plate>/roi/<well>_rois.json` |
| `manual` | noise + sampleN | circle | `Processed-Data/<scan>_roi/rois.json` |
| `burst` | noise + signal_NN | polygon | `<burst>/output/roi_defs.json` |

Then run the pipeline unattended — **with `--roi_per_well` and without
`--overwrite_roi`**, so `us_proc` loads the files instead of opening a window:

```bash
MPLBACKEND=Agg python .claude/skills/figure-design/scripts/run_styled.py Scripts/us_proc_v5_addBURST_colormap.py plate_ge \
  --data_dir <…>/plate --roi_per_well --well_map <…>.csv --metadata_csv <…>.csv
```

### The priors it uses

- **Depth**: xAM ≈ 5 mm, BURST ≈ 8 mm (or `P.txFocus_mm` when present).
  `--depth-mm` / `--depth-tol` override.
- **Lateral**: GE plates have three U-bottom wells at −9 / 0 / +9 mm
  (`--well-spacing`); L22 plates have one centred well; manual and BURST
  acquisitions get evenly spread seeds refined onto the actual blobs.
- **Interface floor** (plates): the plate bottom is found as the strongest
  full-width horizontal echo — the same feature the GE acquisition tracks as
  `P.interfacePos` — and no sample ROI is allowed above it. Without this a well
  with weak contents locks onto the interface instead.
- **Reference image**: the mean pre-collapse *B-mode*, not xAM, so an empty well
  is still located. (`--reference xam` to override.) BURST uses the
  burst-minus-background difference image.
- **xAM sensitivity band** (`--signal-band`, plates): xAM signal dies away below
  the transmit focus while B-mode keeps showing the well right down to its far
  wall, so a purely B-mode-fitted box runs into a dead zone and dilutes the mean.
  The band is measured once per plate from the wells that have signal — take each
  well's xAM depth profile, drop the wells whose peak never clears their own floor
  by 3 dB (those are empty and say nothing about the focus), and keep the
  contiguous span of the median profile within `--band-drop-db` (default 6 dB) of
  its peak. Every ROI is then clamped to it, empty wells included, so all wells
  keep comparable geometry. Measured values: **GE 3.89–5.52 mm, L22 4.18–6.01 mm**
  against a B-mode well that runs to ~6.4 mm. Pass `lo,hi` to set it by hand or
  `off` to disable.
- **One depth window per plate** (default; `--no-fixed-depth` to opt out): every
  sample ROI on a plate gets the *same* z range. Wells sit at one stage height
  and the xAM band is a property of the acquisition, so per-well depth fitting
  only adds variation that is not biology.
  - **Top edge** is measured from the wells, not from where the xAM profile
    peaks: the profile peaks mid-column, so a peak-derived top clips the top of
    every well. Each well's top is found as the rising edge of the
    interface-suppressed B-mode, and the shared top is the `--top-percentile`
    (default p10) of those, i.e. it reaches the top of ~90 % of wells. The
    measured spread is printed — it is often larger than expected (1.47 mm on
    `260827_CRE-PPV_772`, from plate tilt), and wells sitting deeper than the
    chosen top are counted so you know how much empty space that costs.
  - **Deep edge** comes from the xAM sensitivity band, capped by `--depth-max`.
    Cap it: the well's specular bottom echo stays bright in B-mode well past
    where xAM still carries signal, and including it inflates the B-mode metrics.
  - `--depth-range LO,HI` overrides both.
- **Fill trim** (`--min-fill`, default 0.80): an under-loaded U-bottom well holds
  a concave-up meniscus, so the nominal rectangle contains air near the walls and
  a real well reports as weak. The box is trimmed from whichever edge is emptiest
  until at least this fraction of it is filled — "filled" meaning within
  `--fill-db` (12 dB) of the box's own 90th percentile on the suppressed B-mode.
  The per-well fill fraction is printed, and any well still under target is
  flagged `UNDER-FILLED`.

  With a fixed depth window the trim switches to a **per-column** rule instead:
  it drops only edge columns that are emptier than the well's own median column.
  Chasing a whole-box fill target while depth is locked would shrink the ROI in
  the wrong axis — the empty space is above the well, and the trim would eat the
  well's width trying to compensate, collapsing ROIs to narrow slivers.

### Verification against hand-drawn ROIs

Same script, same well (GE `plate_P_1_1_A01`), only the ROI differing:

| ROI | well1 (no GVs) | well2 | well3 |
|---|---|---|---|
| shape agreement vs hand (`sbr_x`, r) | — (blank) | 0.996 | 0.997 |
| peak `sbr_x`, hand-drawn | 0.4 dB | 11.8 dB | 14.7 dB |
| peak `sbr_x`, auto | 0.4 dB | 11.7 dB | 14.4 dB |
| peak `sbr_x`, auto *without* the band clamp | 0.4 dB | 10.1 dB | 11.7 dB |

The voltage-response shape is reproduced almost exactly, the empty well is
correctly reported as empty, and absolute SBR now lands within 0.4 dB of a
hand-drawn ROI. The last row is what the same fit gives when the ROI is sized on
B-mode alone: 1.8–3.0 dB low, because the box then extends ~1 mm past the depth
where xAM still carries signal. `--roi-scale` remains available to shrink every
ROI about its centre if a particular dataset needs it.

### Always look at the review image

For a plate it writes two contact sheets, one panel per scan position:

- `<plate>/roi/auto_roi_review_xAM.png` — the brightest xAM frame, zoomed to the
  sample ROIs. **This is the one to check**: the box has to cover the xAM signal,
  and a well with no signal should look empty rather than mislocated.
- `<plate>/roi/auto_roi_review_Bmode.png` — the full-depth B-mode reference the
  ROIs were located on, for checking the noise and ceiling placement.

A single manual or BURST acquisition gets a side-by-side reference/xAM figure at
`auto_roi_review.png` next to its ROI file. Magenta = sample, cyan = noise,
green = ceiling.

The console prints, per ROI, the found x/z, the contrast above background, and
the fill fraction; it flags wells under 1 dB of contrast as `LOW CONTRAST` and
wells below the fill target as `UNDER-FILLED`. It also prints the measured xAM
sensitivity band and how many wells contributed to it.

**In-vivo acquisitions are deliberately not covered.** Tumour and contralateral
ROIs differ per animal and per session and must be drawn by hand; a shared
`shared_rois.json` at the `Processed-Data/` level then carries them across every
timepoint of that session.

## 7. Plate heatmaps and Prism export

```bash
python .claude/skills/figure-design/scripts/run_styled.py Scripts/run_plate_compile_and_heatmaps.py \
  --plate-dir <date_folder>/plate --metadata <metadata.csv>
```
96-well `hot` heatmaps of `cnr_x` and `sbr_x/sbr_b`, per voltage and aggregated
(mean, peak), plus wide well × voltage pivot CSVs, into `<plate>/heatmaps/`.

```bash
python .claude/skills/ultrasound-analysis/scripts/to_prism.py \
  <plate>/processed_csv/all_wells_with_metadata.csv \
  --metric cnr_x_corr --pressure --probe GE624D --aperture 35 --depth 5 --tx-freq 12.5
```
Writes `prism/<metric>_prism_replicates.csv` (rows = voltage or frame,
columns = `<group>__r1..rN` for pasting into a Prism *Grouped* table) and
`prism/<metric>_prism_mean_sem.csv`. `--pressure` adds a peak-positive-pressure
column interpolated from the probe calibration.

---

## 8. Per-run reports (`AI_analysis/`)

**Every acquisition folder carries its own analysis.** The generic report is one
command and covers the parts that are the same for every run:

```bash
python .claude/skills/ultrasound-analysis/scripts/make_run_report.py "<run folder>" \
    --group-by condition --volt 12
```

Writes into `<run>/AI_analysis/`:

| Output | Contents |
|---|---|
| `stats.json` | every number the report quotes — the single source of truth |
| `dose_response.png` | metric vs peak positive pressure, one line per group |
| `collapse.png` | peak signal and median collapse threshold per group |
| `qc.png` | plate-rotation agreement — written only when there are 2 plate groups |
| `assets/strip.png` | the **median** well per group at the reference voltage |
| `RESULTS.md` | scaffold: summary table and QC filled in, interpretation left blank |

Notes that matter:

- **`RESULTS.md` is never overwritten.** Re-running after a reprocess refreshes
  the numbers and figures but leaves your write-up alone. Delete it to regenerate.
- **`--group-by` auto-detects** from `condition`, `short_condition`, `sample`,
  `ppv_variant`, `dox`, `oht`, `well_id` — the first with 2–40 levels. Pass it
  explicitly when the auto pick is not the axis you care about.
- **Collapse threshold is per-well median**, and the table marks
  `(not reached)` when the group is still rising at the top of the ramp. A
  threshold that equals the ramp maximum is a ramp limit, not a measurement.
- **`--probe`** switches the calibration table; the default is `GE624D`
  (xAM, aperture 35, 12.5 MHz, 5 mm). Pressures are interpolated, because a
  *median* voltage across wells can fall between two calibrated steps.

### Shared library — `report_lib.py`

Reusable pieces live in the skill so the next dataset inherits them. Anything you
would otherwise copy between run folders belongs here.

```python
import sys; sys.path.insert(0, "<repo>/.claude/skills/ultrasound-analysis/scripts")
from report_lib import Run, C, DOSE_COLORS, MPL_RC, pressure_table

r = Run("<run folder>")
r.pre()                              # pre-collapse rows, ramp voltages only
r.post()                             # post-collapse frames
r.load_xam(scan, 12.0)               # -> (X_mm, Z_mm, dB image), frames averaged
r.load_rois(scan)                    # per-well JSON, falls back to shared_rois
r.well_crop(scan, "well1", 12.0)     # -> (dB crop, imshow extent, roi dict)
r.pressure(12.0)                     # measured calibration, interpolated
r.median_well(df)                    # honest representative, not the best-looking
r.plate_groups() / r.merged_csv / r.out / r.assets
```

`Run` resolves the standard layout (`plate/`, `processed_csv/`, `roi/`,
`images/`, `AI_analysis/`) from the run folder alone, so nothing downstream
hardcodes a path.

### Cross-run work

A synthesis, comparison figure, slide or collaborator draft that spans several
runs goes in `cross_run/` inside the **newest run it covers**, with a `README.md`
naming the runs it spans. Single-run conclusions never go in another run's folder.

## Known defects — check before trusting a run

1. **`Scripts/proc_well_xAM_v2.py` does not parse.** Line 479,
   `def plot_heatmap(arr, title: str,--save_path: Path, ...)`. Superseded by
   `us_proc`; do not try to run it.
2. **`Scripts/US_processing/process_burst_acq_v2.py` does not parse** — literal
   newlines inside a string literal around line 101. Use `process_burst_acq.py`.
3. **`us_proc_v5_addBURST_colormap.py` has no BURST mode** despite its name; the
   parser exposes only `manual`, `in_vivo`, `plate_l22`, `plate_ge`. BURST is
   still a separate script.
4. **`compile_plate_results.py` looks for `*_results_blank_corrected.csv`**,
   which was the `proc_well_xAM_v2.py` filename. `us_proc_v5` writes
   `*_results.csv`, so the compile step finds nothing. Either point it at
   `all_wells_with_metadata.csv` or rename.
5. **`_corr` ratio columns are linear, uncorrected ones are dB** — see
   `metrics.md`.
6. **`P.HP` on GE files still names the L22 calibration.** Use the CSVs in
   `../calibration/`.
7. Interactive ROI selection needs a GUI matplotlib backend (`TkAgg` /
   `MacOSX`). Headless runs must reuse a saved ROI JSON — see *Auto-ROI* below,
   which generates them without a GUI.
8. **Multi-plate runs collide in the metadata join.** `discover_well_folders()`
   returns only the scan suffix, so `plate_P_1_1_A01` and `plate_P_1_2_A01` both
   become scan id `A1`; `df_all` carries no plate-group column, and the
   `--metadata_csv` merge keys on `well_id` alone. When the two plates hold
   *different* conditions at the same coordinates — a rotated-layout replicate, a
   second construct — half the plate is silently attached to the wrong conditions.
   The per-scan `<scan_name>_results.csv` files *do* keep the plate group in their
   filename, so rebuild the join from those and skip `--metadata_csv`. Worked
   example: `260904_CRE-PPV_772/AI_analysis/scripts/merge.py`.
9. **Blank-corrected ratios are structurally unsound, not just mis-united.**
   `apply_blank_correction` subtracts the post-collapse blank from the signal
   *and* the noise mean, then `_recompute_corrected_ratios` divides by the
   corrected noise. The noise ROI contains only noise in both phases, so that
   denominator is a difference of two identical noise floors (~0.1 out of ~11.5)
   and `sbr_x_corr` / `snr_x_corr` / `cnr_x_corr` swing wildly in sign and
   magnitude — on `260904_CRE-PPV_772`, between −803 and +856 while `sbr_x` rose
   smoothly 0→15 dB. `signal_mean_x_corr` (background-subtracted amplitude) is
   fine; the ratios built from it are not. Report uncorrected dB metrics, and
   check the blank against the true-blank wells instead: when those sit near
   0 dB, blank correction buys nothing anyway.

### Fixed — 2026-08-28

**Doppler display axes were wrong in both directions.** Both
`Doppler_processing_JWY.m` and `Doppler_processing_JWY_bothProbes.m` divided the
pixel spacing by 2 after `interp2(Dop, 2)`, but MATLAB's `interp2(V, k)` refines
*k times*, so k = 2 divides the spacing by 4 — the image was stretched 2× in both
axes. The lateral axis also started at 0 instead of `PData.Origin(1)`, putting
Doppler half an aperture (6.35 mm on L22, 12.89 mm on GE) to the right of the
xAM it was meant to sit under. A third, smaller error: the L22 branch used
`UF.Lambda` as the lateral pixel size where `PDelta(1) = Trans.spacing` makes it
the element *pitch* (0.1 mm vs 0.09856, 1.5 % off).

On the L22 example the corrected axes now land on X = [−6.35, +6.35] mm and
Z = [1.00, 9.97] mm, matching `UF.Depth = [1, 10]` and the ±half-aperture
exactly; before the fix they read 0 → 25.03 mm and 1 → 18.94 mm.

**Any Doppler/xAM overlay figure made before this date is misregistered** and
should be regenerated. The corrected scripts now also print the axis ranges and
save `X_mm` / `Z_mm` into `Dop.mat`; `us_proc`'s `load_doppler` prefers those when
present (resampling the image onto them) and otherwise falls back to deriving
axes from `UF.mat` as before, so older `Dop.mat` files keep working. The Python
fallback was never off by 2× — it produced ±6.31 mm against the correct
±6.35 mm — so only the MATLAB display and anything traced from it were affected.
