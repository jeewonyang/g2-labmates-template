# Metric definitions

Two generations of code compute overlapping metrics with **different formulas
and different units**. Never compare a number from the MATLAB pipeline against a
number from `us_proc.py` without checking which definition produced it.

All statistics are computed on **linear-scale** images inside boolean ROI masks;
the dB conversion happens at the end (or at display time), never before averaging.

---

## `us_proc_v5` (current Python pipeline) — `compute_metrics()`

Per frame × per sample ROI, computed once for xAM (`_x`) and once for B-mode (`_b`):

```
SBR = 20·log10( mean(signal) / mean(noise) )                        dB
SNR = 20·log10( mean(signal) / std(noise) )                         dB
CNR = 20·log10( |mean(signal) − mean(noise)| / sqrt(σ²_sig + σ²_noise) )   dB
AM/Bmode ratio = mean(xAM signal) / mean(Bmode signal)              linear
```

Raw columns also retained: `signal_mean_x/b`, `noise_mean_x/b`,
`signal_std_x/b`, `noise_std_x/b`.

### Blank correction (`_corr` columns)

The post-collapse frames are the collapsed-GV background: subtract them and what
remains is GV-specific signal. **Whenever post-collapse frames exist they are
used** — `us_proc` picks a tier automatically from `P.Vseq` / `P.seed`.

`P.Vseq` and `P.seed` are read **per acquisition folder**, from the first `.mat`
in that folder, and are never assumed to be uniform across a plate or a session:
two wells of the same plate can carry different ramps if a position was re-run.
`identify_dataset.py` scans every folder and prints a warning listing the
variants when they disagree. Each folder is corrected on its own terms, but
group differing sequences separately before pooling them as replicates.

| Tier | Condition | Behaviour |
|---|---|---|
| **full-match** | every pre-collapse voltage also appears post-collapse | subtract the post-collapse value at the *matching voltage* |
| **partial-match** | only some voltages have a post-collapse counterpart | subtract the match where it exists; elsewhere subtract the mean of the **lowest** post-collapse voltage |
| **none** | `len(seed) == len(Vseq)` | copy raw values into `_corr` unchanged (identity) |

Correction arithmetic:

```
mean_corr = mean_pre − mean_post
std_corr  = sqrt(std_pre² + std_post²)          # variance propagation
```

then SBR/SNR/CNR/ratio are **recomputed from the corrected means and stds** —
and here is the trap: the recomputed `_corr` ratios are emitted as **plain
ratios, not dB**, while the uncorrected `sbr_x` / `snr_x` / `cnr_x` are in dB.
A `cnr_x` of −14 and a `cnr_x_corr` of 0.02 are the same kind of quantity in
different units. Convert before plotting them on one axis.

Post-collapse subtraction can also drive a corrected mean negative (noise floor
overshoot), which makes the corresponding ratio meaningless. Filter or flag rows
where `signal_mean_x_corr <= 0`.

---

## Legacy MATLAB (`RegUSImageProc_ZJ_v3.m`, `BURSTProc.m`)

```
sampROI(i,j)   = mean(Im{i,j}(zSampROI, xSampROI))      j: 1 = xAM, 2 = B-mode
noiseROI(i,j)  = mean(Im{i,j}(zNoiseROI, xNoiseROI))
noiseROI(i,j+2)= std2(Im{i,j}(zNoiseROI, xNoiseROI))

CNR = 20·log10( |sampROI − noise_mean| / noise_std )    dB
SBR = 20·log10( sampROI / noise_mean )                  dB
```

**The CNR denominator differs**: legacy uses the noise standard deviation alone,
`us_proc` uses `sqrt(σ²_signal + σ²_noise)`. Legacy CNR is therefore
systematically higher whenever the sample ROI is heterogeneous. This is the
single most likely source of "the numbers changed when we switched scripts".

Display images are normalised to the frame max with a noise-derived floor:
`ImDisp = Im_dB − max(Im_dB)`, colour limits `[noise_dB − max_dB, 0]`.

---

## BURST

BURST fires a destructive collapse and measures the transient. The signal is the
**peak minus the settled post-collapse plateau** — one number per ROI per
acquisition, not a curve.

### `BURSTProc.m` (MATLAB, original)
```
BURST  = max(sampROI)            − mean(sampROI(plathreshold:end))
nBURST = BURST / mean(sampROI(plathreshold:end))
```
with `plathreshold = 20` (frame index) hard-coded, and the displayed difference
image hard-coded as `Im{11} − Im{45}`. Output: `<name>_BURST.mat` holding
`BURST`, `nBURST`, `AllSamples` — one entry per sample per ROI (2 ROIs per
acquisition, so a 12-folder run yields 24 values).

### `process_burst_acq.py` (Python, current)
Same quantities, but the frame windows come from `P` instead of being hard-coded:

```
burst_frame = argmax of the ROI-mean curve (or --burst-frame)
background  = frames [numPre + numCol : end]        # the explicit post-collapse block
diff_img    = burst_frame − mean(background)

BURST  = mean(burst_frame[ROI]) − mean(background[ROI])
nBURST = BURST / mean(background[ROI])
SNR    = BURST / std(diff_img[noise_ROI])
CNR    = (BURST − mean(diff_img[noise_ROI])) / std(diff_img[noise_ROI])
```

If `P` has no post-collapse block it falls back to "start `--bg-gap` frames
after the burst, at least `--bg-min-frames` frames".

Prefer the Python version: the MATLAB `plathreshold = 20` sits *inside* the
collapse window for a 10/20/10 acquisition, so it averages collapsing frames
into the "plateau" and under-reports BURST.

---

## Doppler

Power Doppler, no ROI statistics by default — it is a background layer, not a
quantified channel:

```
Dop = mean( |IQ − SVD_tissue(IQ, rank 20)|², over the 200-frame ensemble )
```

Displayed as `sqrt(Dop)`, `hot` colormap, per block and as a block mean.
Used to show vasculature under the xAM overlay so tumour/tissue ROIs can be
placed on anatomy rather than on the AM signal itself.

---

## Which metric to report

| Question | Metric |
|---|---|
| Does this construct produce GV signal above background? | `cnr_x_corr` (blank-corrected xAM CNR) |
| How bright is the sample relative to noise? | `sbr_x` / `sbr_x_corr` |
| Is signal nonlinear (GV) or just echogenic? | `am_bmode_ratio` |
| At what pressure does collapse onset occur? | `sbr_x` vs voltage, converted to MPa |
| Single most sensitive detection | BURST / nBURST |
| Sample amount independent of GV state | `sbr_b` (B-mode) |

Plate screens are usually reported as `cnr_x_corr` heatmaps plus
`sbr_x / sbr_b` (B-mode-normalised) to divide out well-to-well loading
differences.

## At which voltage? — the ramp biases anything fitted at its top

Every metric above is read at *some* transmit voltage, and that choice is not
free. A voltage ramp is progressively destructive: each step collapses some gas
vesicles, and takes most from the wells that have most. The top of the curve
therefore flattens faster than the bottom as the ramp climbs, which drags any
fitted midpoint to the right.

Measured on `260904_CRE-PPV_772` (GE 96-well plate, xAM, 6→20 V, collapse shot at
14 V), refitting the pooled doxycycline EC50 independently at every ramp voltage:

| V | 8–9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 |
|---|:--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| EC50 (µg/mL) | no fit | 0.050 | 0.045 | 0.043 | 0.044 | 0.047 | 0.051 | 0.060 | 0.067 | 0.070 | 0.076 | 0.073 |

Three things follow, and they generalise beyond EC50 to any cross-condition
quantity (fold-change, ratio between arms, rank order of a screen):

1. **Refit at every voltage and report from the flat window.** Here that is
   10–15 V, a ±9 % band. Stability across many voltages *and* several
   independent groups is much stronger evidence than a tight CI at one voltage.
2. **A value that moves with voltage is an artefact of the ramp**, not a
   property of the sample — so plot the quantity against voltage before quoting
   it, the same way an ROI is reviewed before its numbers are trusted.
3. **Below the noise floor, refuse to fit.** Under 10 V here the ladder had not
   cleared background and the optimiser still returned confident-looking
   nonsense (one group fitted at 6.6 µg/mL). Guard on dynamic range, on fit
   quality, and on the midpoint falling *inside* the doses actually tested — an
   EC50 outside the tested range is an extrapolation, not a measurement.

Note that this bias is invisible in the usual QC line. `make_run_report.py`
reports *"The ramp never reached collapse"* when no condition turns over, but
that only says the **net** curve is still rising: pressure driving signal up can
outrun collapse taking it away. On this run nothing turned over, and collapse
was nonetheless biasing the EC50 by 50 % over the top four steps.

**Practical fix at acquisition**: end the ramp shortly above the stability
window (16 V here) rather than at 20 V. The extra steps cost information rather
than adding it.
