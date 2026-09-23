# Probe hardware, acquisition parameters, and pressure calibration

Two transducers appear in this lab's data. The GE6-24D replaced the Verasonics
L22-14vX recently, so most historical data is L22 and most new data is GE. When a
GE case has no example, the L22 example is the template — but the parameters
below are **not** transferable, only the workflow is.

## Hardware

| | L22-14vX | GE6-24D (`GE624D`) |
|---|---|---|
| Elements | 128 | 192 |
| Pitch | 100 µm (`P.pitchSI = 1e-4`) | 135 µm (`P.pitchSI = 1.35e-4`) |
| Lateral aperture | 12.8 mm | 25.9 mm |
| `computeTrans` | Verasonics built-in | custom `Acquisition/computeTrans_GE6_24_v3.m` |
| 6 dB bandwidth | (built-in) | 8.0 – 18.0 MHz |
| Element width | (built-in) | 0.9 × pitch |
| Elevation aperture | (built-in) | 2.0 mm |
| Lens correction | (built-in) | 0.625 |
| `Trans.maxHighVoltage` | 25 V | 40 V (25 V in the fUS script) |
| `Trans.ConnectorES` | 1:128 | 33:224 |
| `Trans.connType` | 1 | 7 |

`P.pitchSI` is the most reliable probe fingerprint — it survives in every saved
`Imgdata_*.mat`. `P.numEle == 192` and `P.numRays > 100` are secondary signals.

## xAM imaging parameters (as actually acquired)

| | L22 plate/manual/in-vivo | GE plate |
|---|---|---|
| `P.txFreq` | 15.625 MHz | 12.5 MHz |
| `P.numRays` | 64 | 158 (`numEle - Pap + 1`) |
| `P.Xap` / `P.numTx` (xAM aperture) | 65 | 35 |
| `P.half_ap` | 32 | 17 |
| `P.alpha` (X-beam angle) | 19.5° | 20° |
| `P.startDepth_mm` – `endDepth_mm` | 0 – 10 (plate), 0 – 15 (in-vivo) | 1 – 9 |
| `P.numAccum` | 15 | 10 |
| `P.TXdelay` | 60 µs | 100 µs |
| `P.cSI` (speed of sound) | 1500 m/s | 1500 m/s |
| Lateral field of view | ±3.2 mm | ±10.67 mm |
| Wells imaged per FOV | 1 | 3 |
| Typical voltage ramp | 3 → 15 V, 0.5 V steps, 1 frame/V | 6 → 20 V, 1 V steps, 3 frames/V, plus 2 V baseline |

`P.pulseShape` = `axicon` and `P.code` = `AM` identify xAM on both probes.
`P.RampMode` at acquisition time selects the beam: 1 = pBmode, 2 = xAM,
3 = xBmode, 4 = pAM.

Every `Imgdata_*.mat` carries **both** the B-mode (`ImgData.Imb`) and the xAM
(`ImgData.Imx`) reconstruction of the same transmit event, so B-mode background
structure is always available without a separate acquisition.

## CNC plate scanning

The stage steps in `xDist` / `zDist` mm increments over an `xLines` × `zLines`
grid, saving one folder per stop as `plate/plate_P_<pRow>_<pCol>/plate_P_..._<A01>/`.

| | L22 | GE |
|---|---|---|
| `P.xLines` × `P.zLines` | 8 × 6 = 48 stops | 6 × 4 = 24 stops |
| `P.xDist`, `P.zDist` | 9 mm, 9 mm | 9 mm, 27 mm (3 wells per z step) |
| Wells covered | 48 (one per stop) | 72 (three per stop) |
| Well ID in folder name | the physical well | the *scan position*, not the well |

For GE the folder-name well ID is a **scan position**. The physical wells come
from a mapping CSV (`acoustic_plate_reader_well, well1, well2, well3`), e.g.
`A1 → A1,A2,A3` and `A2 → A4,A5,A6`. `Scripts/Ishaan/ultrasound_plate_labeling_patch.csv`
is the canonical 24-row map; each dataset usually also ships its own copy.

### Depth targeting

- **L22** uses `P.autoROI` with `P.wellROI` / `P.noiseROI` as fractional image
  coordinates, plus a `P.autoDepth` correction bounded by `P.autoDepthRange`.
- **GE** uses interface tracking (`P.autoDepthSimple = 1`): it averages the image
  over two lateral bands (`P.interfaceSearchX`, percentages of image width),
  finds the brightest depth in a 1–7 mm search window on each side, and moves the
  stage so the mean interface lands at `P.interfaceTargetZ` (3.5 mm). The result
  is written back as `P.interfacePos = [leftZ, rightZ, avgZ]` — a useful QC
  field: if the three values disagree by more than ~0.5 mm the plate was tilted.

## Doppler / fUS

Both probes run the same plane-wave compounding sequence (15 tilted angles
−14°…+14°, `numFrames = 200` per block, `dopFrameRate = 500` Hz,
`NbOfBlocs = 3`, `TwFreq = 15.625 MHz` on **both** probes) but reconstruct onto
different pixel grids:

| | L22-14vX | GE6-24D |
|---|---|---|
| `PData.PDelta` | `[Trans.spacing, 0, 1]` | `[Trans.spacing/2, 0, 0.25]` |
| Lateral pixels (`lat_resol`) | 128 | 384 |
| Axial pixels (1–10 mm) | 92 | 368 |
| Axial mm/px | `UF.Lambda` | `UF.PDelta(3) * UF.Lambda` |
| Lateral mm/px | `UF.Lambda` | `UF.PDelta(1) * UF.Lambda` |

`UF.Lambda = 1540 / (RcvFreq in kHz)` = 0.09856 mm for both.

Display axes (as corrected on 2026-08-28 — see `pipelines.md`):

```
Z_mm = UF.Depth(1)          + (0:Z-1) * axial_px_mm / 2^k
X_mm = -pitch_mm*(numEle-1)/2 + (0:X-1) * lat_px_mm  / 2^k     % k = 2 in interp2(Dop, 2)
```

The lateral pixel is a fraction of the element **pitch**, not of Lambda:
`PDelta(1)` is `Trans.spacing` (L22) or `Trans.spacing/2` (GE) in wavelengths,
and `Trans.spacing = pitch/Lambda`. The lateral origin term is what puts the
Doppler image concentric with the xAM instead of half an aperture to its right.

**`lat_resol` must match the probe or the `.bin` reshape silently produces
garbage.** `Doppler_processing_JWY_bothProbes.m` picks it from `UF.lat_resol` if
present, else from `UF.Probe`, else warns and falls back to 192.

## Voltage → acoustic pressure calibration

The two probes have completely separate calibrations, in **different units**, and
the `P.HP` struct inside GE `.mat` files still carries the stale L22 curve file
name (`hpVoltageCScans_FP126-16t.mat`) — **ignore `P.HP` on GE data**.

Portable copies extracted from the MATLAB sources live in
`../calibration/` and can be read with pandas (no MATLAB needed):

### `GE624D_pressure_calibration.csv`
Extracted from `Scripts/Probe-Calibration/00_Probe_Calibration/GEx2_pressure_organized_zero_phase_260503.mat`
(a hydrophone C-scan, water, 1500 m/s, zero-phase assumption). 1230 rows =
41 conditions × 30 voltages (1.6 – 30 V).

Columns: `probe, Mode, Aperture, TxFrequency_MHz, Location_mm, Focus_mm, Voltage_V, PPP_MPa, PNP_abs_MPa, NumTrials`.
`Mode` is `xAM` (no focus) or `pAM` (focused). Pressures are **MPa**, derived as
max/−min of the averaged pressure waveform.

Available xAM conditions: aperture 35/45/65/85 × depth 5/7/9/10 mm, at
15.625 MHz, plus 12.5 MHz variants for aperture 35 at 5 and 7 mm.
**The GE plate operating point is aperture 35, 12.5 MHz, ~5 mm** → 0.385 MPa PPP
at 5 V, 0.868 MPa at 10 V, 1.806 MPa at 20 V.

The source `.mat` also holds a `summaryTable` (a MATLAB `table` with
`PPP_MPa_mean/std`, `PNP_abs_MPa_mean/std`) which only MATLAB can read directly —
`sunho.m` in that folder shows the query pattern. The CSV above is equivalent for
single-trial lookup.

### `L22_L10_pressure_calibration.csv`
Extracted from `Scripts/Probe-Calibration/00_Probe_Calibration/Calibrations/*/*.mat`.
The MATLAB `IData` (interpolated) and `CData` (raw) arrays are 4-column
`[Voltage_V, PPP, PNP, peak-to-peak]` in **kPa**; the CSV converts to MPa for
consistency with the GE file.

Four calibration sets: `210108-L22-14V`, `220325-L22X`, `220325-L22X-fUSi`
(the probe currently paired with the fUS setup), `220415_L10-4v`. Each has
`xAM` and `Parabolic` beams at 5/6/8 mm. Prefer the most recent set matching the
probe actually used; `220325-L22X-fUSi` xAM at 5 mm gives 0.54 MPa PPP at 5 V.

Legacy MATLAB plotting scripts load a separate `Data_PPP.mat`
(`[Voltage, pBmode_PPP, xAM_PPP]` in MPa, `* 1000` → kPa) from a path outside
this repo. That file is **not present here**; use the CSVs instead.
