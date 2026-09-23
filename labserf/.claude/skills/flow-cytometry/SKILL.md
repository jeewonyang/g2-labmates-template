---
name: flow-cytometry
description: Auto-analyze MACSQuant flow cytometry runs - read .fcs and .mqd files and FlowJo .wsp workspaces, gate live cells and singlets, set per-channel positivity thresholds for BFP/GFP/OFP/iRFP, compute percent-positive, median fluorescence and double-positive fractions per condition, and produce gate review images, result figures and GraphPad Prism tables. Use whenever a folder of .fcs or .mqd files is involved, a .wsp workspace is mentioned, or the question is about flow gating, percent positive, MFI, double positives, or comparing fluorescence between conditions.
---

# Flow cytometry analysis

This skill is self-contained. The file-format rules, channel-resolution table
and gate calibrations below were derived from this lab's own MACSQuant runs
and FlowJo workspaces and are written down here — **you never need to open
`ExampleData/`**. Point the tools at the run folder the user names. Numbers
quoted from the example runs are provenance, marked as such, not lookups to
repeat.

Run the scripts with the user's conda base interpreter,
`python` (numpy / scipy / matplotlib only; verified to give
byte-identical results to a modern Python 3.12 environment). `requirements.txt`
lists the dependencies for any other machine.

## The three stages, always

A processed CSV is not a result, and a result the user has to interpret alone
is half a deliverable.

**1 · Run the pipeline.** Classify the folder, gate, threshold, export.
**Show the gate review images before quoting any number.**
**2 · Report the result.** `<run>/AI_analysis/RESULTS.md`, carrying your
interpretation — which differences are real, which are noise, and what the
data cannot show.
**3 · Suggest the next round.** `NEXT_EXPERIMENTS.md`, each proposal tied to
the observation that motivates it.

**Read the negative-result memory before stage 3, and write to it after any
null or failed run** — a construct that never expressed, a condition
indistinguishable from the negative control, a run lost to a clog:

```bash
N=.claude/skills/scientific-advisor/scripts/negative_results.py
python $N check --tags flow,<system> --query "<the idea>"
python $N add --title "..." --outcome did-not-express \
    --assay flow --tried "<channels, conditions>" --observation "<% pos, MFI, n>" \
    --why "<hypotheses>" --next "..." --run <run> --source <run>/AI_analysis/RESULTS.md
```

`did-not-express` and `technical-failure` leave the biological question open;
only `no-effect` and `below-detection` are evidence about the biology. Low
event counts or a skipped singlet gate make a run `inconclusive`, not negative.

## Start here

```bash
# what is in this folder?
python .claude/skills/flow-cytometry/scripts/fcs_io.py "<run folder>"

# the whole analysis
python .claude/skills/flow-cytometry/scripts/analyze_flow.py "<run folder>"
```

`analyze_flow.py` writes everything into `<run>/AI_analysis/` and touches
nothing else in the raw folder. Useful options:

| Option | Why |
|---|---|
| `--negative-control <substring>` | **Use this whenever an untransfected/no-fluorophore well exists.** Thresholds then come from the control's 99.5th percentile, which is defensible without reference to any calibration. |
| `--use-wsp-gates` | Apply the user's FlowJo gates *and* their quadrant thresholds verbatim instead of fitting new ones. |
| `--highlight <substring>` | The one condition to draw in the lab orange. Left unset every bar is grey — orange asserts "this is the point", and only the user can say which condition that is. |
| `--compare "A,B"` | Test condition A against B. Repeat for every pair the experiment was designed to test. Each side is an exact name or a substring matching exactly one condition. |
| `--reference <condition>` | Test every other condition against this one. Use only when that really is the design — see "Statistics between conditions". |
| `--k <float>` | Robust SDs above the negative mode for positivity. Default 9. |
| `--max-panels <n>` | Cap the panels per review figure. Default shows every well — a review image that hides wells is not a review. |
| `--out <dir>` | Write elsewhere, e.g. when the raw folder is read-only. |

## The file formats

**`.fcs` and `.mqd` hold the same events.** MACSQuantify writes a native
`.mqd` and exports a `.fcs`; a run folder usually contains both, plus
hand-renamed copies of some wells.

- **`.mqd` stores every channel as a fraction of its `$PnD` full scale.**
  Multiplying by the `$PnD` range max reproduces the `.fcs` export exactly.
  `fcs_io.read_events` does this, so both formats come back on one scale and
  FlowJo gate coordinates apply to either. *(Verified channel-by-channel on
  the example runs; an `.mqd`-only analysis reproduces the `.fcs` analysis to
  6 x 10^-8, i.e. float32 rounding.)*
- The MQD header packs its offsets as whitespace-separated fields, not the
  fixed 8-character fields of FCS3.x.

**Dedupe on `$FIL`.** Every copy of one acquisition — `.mqd`, `.fcs`, and any
renamed export — carries the same `$FIL`, `$WELLID` and `$BTIM`. `discover()`
groups on those and keeps one, preferring `.fcs`.

**`$CELLS` is the condition label**, typed at acquisition. Filenames are not
trustworthy: in the example runs the same well appears as
`ABC2026-01-10SA.0003.mqd` and `No SA_ctrl.fcs` — a different naming
scheme *and* a typo. Prefer `$CELLS`; let the user override.

**Setup and flush runs** have no `$CELLS` label and far fewer events than the
run median. `discover()` drops them and says so.

**A file named `live (...)` is usually not pre-gated.** In both example runs
its event count matched the parent `.mqd` exactly. `discover()` compares
counts rather than trusting the name, and only treats a copy as a subset when
it genuinely has fewer events.

## Channel resolution — never key on `$PnN`

The detector names differ between the two formats for the *same* detector:

| Fluorophore | `$PnS` | `.fcs` `$PnN` | `.mqd` `$PnN` | Laser | Filter |
|---|---|---|---|---|---|
| BFP | `EBFP2-A` | `FL1-A` | `V1-A` | 405 nm | 450 |
| GFP | `Emerald-A` | `FL3-A` | `B1-A` | 488 nm | 525 |
| iRFP | `APC-A` | `FL7-A` | `R1-A` | 640 nm | 655–730 |

So `fcs_io.channels()` resolves roles from **`$PnS` first, then the optics
(`$PnL` laser + `$PnF` emission band)** — never from `$PnN`. OFP (488 or 561
excitation, ~585 emission) is supported but absent from the example runs.
Access channels by role: `sample.col("GFP")`, not by detector name.

## Gating

### 1. Live cells — scatter

The lab's preference is SSC-H × SSC-A, falling back to FSC-A × SSC-A. **The
MACSQuant Analyzer 10 records no height or width channels at all**, so on this
instrument it is always FSC-A × SSC-A, and the pipeline says so.

The gate is fitted **in asinh space (width 20), not linear**. On a linear
0–1000 axis the whole cell population collapses into the bottom-left corner
sitting on the debris cloud, and a density contour fits the debris boundary
instead of the cells. Fitting in asinh space and mapping the polygon back to
data units fixes it.

Defaults `coverage=0.85, expand=1.02, smooth=4` reproduce this lab's
hand-drawn gates at **Jaccard 0.941 (2026-01-10) and 0.964 (2026-01-14)**,
with the keep-fraction within ~2 points of the hand gate (72.3% vs 74.3%,
80.6% vs 83.2%). The fitted outline is lightly smoothed before use, which
costs ~0.01 Jaccard and removes a contour kink that would otherwise appear on
every panel. *(Provenance: the two example workspaces.)*

One gate is fitted per run from the pooled events and applied to every sample,
which is what the lab does in FlowJo.

### 2. Singlets — area vs height

Needs a height channel. Where one exists the A/H ridge is fitted and events
within 3 robust SD are kept. **On the MACSQuant there is none, so this step is
skipped and the reason is recorded in `stats.json` and `RESULTS.md`.** Say this
to the user rather than letting them assume singlets were gated.

### 3. Fluorescence positivity

Two methods, and the pipeline always prints which one it used:

- **With a negative control** (`--negative-control`): the 99.5th percentile of
  the pooled control events. Prefer this.
- **Without one**: `mode + 9 x robust SD` of the negative population, measured
  in asinh space, with the SD taken from the **left half of the peak only** —
  positives sit to the right, so the left half is uncontaminated.

How the no-control rule compares with this lab's hand-set cuts:

| Run | Channel | Auto | FlowJo | Difference |
|---|---|---|---|---|
| 2026-01-10 | GFP | 2.90 | 2.43 | +19% |
| 2026-01-10 | iRFP | 2.78 | 5.23 | −47% |
| 2026-01-14 | GFP | 2.53 | 2.43 | +4% |
| 2026-01-14 | iRFP | 2.77 | 2.90 | −4% |

The same operator set the iRFP cut at 5.23 one day and 2.90 four days later —
the variability the rule exists to remove — but it also shows the rule and the
eye can disagree by a factor of two on where "positive" starts. **`k = 9` was
chosen on these two runs, so it is calibrated, not independently validated.**
Always show `threshold_*.png` and say which method set the cut.

## Reading a FlowJo workspace

`wsp_io.py` reads the Gating-ML gates out of a `.wsp`. **Gate coordinates are
in the same units as the `.fcs` DATA segment**, so they apply directly to the
arrays `fcs_io` returns.

```bash
# replicate the workspace's own population counts
python .claude/skills/flow-cytometry/scripts/wsp_io.py <file.wsp> <run folder>
```

Across both example workspaces this reproduces all 240 FlowJo population
counts to **within 0.46%** (the residual is FlowJo's polygon edge handling).
Treat >0.5% as a bug, not as noise.

`consensus_gate()` returns the scatter gate shared by every sample in the
workspace, or `None` when the samples disagree — the pipeline warns rather
than silently picking one.

### A caveat these example runs make concrete

In both example runs the iRFP distribution is a **negative mode with a
continuous plateau** running out to ~5000 a.u. — there is no separable
positive population. The automatic cut (2.78) and the hand-drawn FlowJo cut
(5.23) give 28.6% and 24.2% iRFP+ **on the same events**. GFP behaves the same
way, less severely.

When a channel looks like that, "% positive" is a threshold convention, not a
measurement of two populations, and the number moves with the cut. Say so, and
report the median fluorescence of the whole gated population alongside — it
does not depend on a threshold at all. A single-colour or untransfected
control well is what settles it; recommend one for the next plate.

## Statistics between conditions

Nothing is tested unless asked. Ask for the comparisons the experiment was
designed to answer:

```bash
# pairs, e.g. each construct with and without PPV
analyze_flow.py <run> --compare "GvpC,GvpC+PPV" --compare "772,772+PPV"

# everything against one control
analyze_flow.py <run> --reference "772-rtTA"
```

**Do not default to `--reference`.** This lab's plates are usually paired
designs — construct ± PPV, strain ± Dox — and testing every condition against
one reference asks questions nobody posed (is `772+PPV` different from `SA`?)
while each extra comparison makes the correction stricter for the ones that
matter. Read the condition names, propose the pairs, and confirm them with the
user before running.

**The test** is Welch's unpaired t-test with Holm–Šidák correction, applied
*within each metric* across that metric's comparisons. That is exactly
Prism's "multiple unpaired t-tests" analysis, so every number reproduces from
the tables in `prism/`. Welch rather than Student because replicate CVs in
this lab's runs span ~1–12% between conditions on one plate; the lab's own
writing reports Welch (the *Anatomy of a Manuscript* example quotes
"d.f. = 12.73"). With n = 3 vs 3, d.f. can be as low as 2 — that is correct,
and it is reported.

Tested metrics: `percent_positive` and `median` per channel, and every
double-positive fraction. Outputs: `comparisons.csv` (difference with 95% CI,
t, d.f., raw and adjusted p), a `comparisons` block in `stats.json`, a table
per metric in `RESULTS.md`, and annotations on the result figures — brackets
with the adjusted p for explicit pairs, stars only for a vs-reference design
(an 8 pt p-value is wider than the bar spacing).

**What the p-value can mean — say both of these whenever tests are reported:**

- **n = 3 wells.** Whether those are biological replicates (separate
  transfections) or technical ones (one transfection split across wells) is a
  fact about the plate setup that the files do not record, and it decides what
  p means. With technical replicates, p measures pipetting and reading noise,
  not whether the effect reproduces. Ask.
- **Percent-positive tests inherit the threshold.** Moving the cut shifts every
  well of a metric together; the s.d. across wells does not capture that, so
  the p-value is conditional on the cut. The `*_median` tests do not depend on
  any threshold. When a `% positive` test and the matching median test
  disagree, report the disagreement rather than the smaller p.

Both caveats are written into `RESULTS.md` automatically.

*Provenance (2026-01-10, four construct ± PPV pairs):* BFP+ rose 18–22 points
with PPV in every pair (adjusted p ≈ 0.001) — BFP marks the PPV plasmid, so
this is effectively a positive control for the test. GFP and iRFP mostly did
not survive correction; the one iRFP % positive that did (`v9772` vs
`v9772+PPV`, p_adj = 0.03) was not significant on the threshold-free iRFP
median (p_adj = 0.17) — the second caveat above, in real data.

Skipped comparisons (fewer than 2 values per side, or zero variance in both)
are listed with the reason rather than dropped.

## Statistics

**No geometric means.** Hyperlog-calibrated MACSQuant data contains genuine
negative values (~10% of events on a dim channel), so a geometric mean is
undefined and a log axis silently drops those events. The pipeline reports the
median (robust summary) and the arithmetic mean, and plots on an asinh axis.

Per well: `percent_live`, and per channel `percent_positive`, `median`,
`mean`, `median_positive`. Per channel pair: all four quadrants, with Q2 the
double positive. Per condition: mean ± s.d. across replicate wells, with `n`
stated. In the example runs a condition is 3 wells (one plate column).

Always say what a mean is over — "n = 3 wells", not "n = 3".

## Outputs

    <run>/AI_analysis/
      RESULTS.md              scaffold carrying every number; fill in the interpretation
      stats.json              gate coordinates, thresholds, methods, warnings, figure audit
      per_well.csv            one row per acquisition
      per_condition.csv       mean and s.d. across replicates
      figures/                PDF + PNG, both auditable and publication-styled
        gate_live.*           THE review image - show this first, every time
        threshold_<role>.*    where each positivity cut landed, vs FlowJo's
        quadrant_<a>_<b>.*    double positives per sample
        result_*.*            per-condition bar charts with replicates
      prism/                  GraphPad Prism import tables, one per metric

## Figures

All figures go through the `figure-design` skill (8 pt Arial, 0.5 pt lines,
greys + one orange accent). `analyze_flow.py` audits its own PDFs with
`check_figure.py` at the end and records violations in `stats.json`.

**After generating figures, have the `figure-designer` agent review them**, apply
its fixes to the *generating code* (never to the output file), and re-render.
The mechanical checker cannot see overlapping labels, a squashed plot, or a
gate that clips a real population; the agent can.

Worked examples (review images with FlowJo comparison numbers) are not shipped
with this template, because they were one person's experimental data; add your
own under `references/gate_examples/` if you want them.

## Not done yet

- **No compensation/spillover.** `$SPILLOVER` is `0` in the example runs. If a
  run carries a spillover matrix, the pipeline ignores it — check and say so.
- **OFP is supported but untested**; no example run used it.
- Singlet gating code exists but has never run on real data, for want of an
  instrument with height channels.

## Keeping it self-contained

```bash
python .claude/skills/flow-cytometry/scripts/check_self_contained.py \
    --data_dir "<a real run folder>"
```

Fails if any script reaches back into `ExampleData/`, and runs the pipeline
end to end to confirm the expected outputs appear. Run it after adding a tool
or a reference.
