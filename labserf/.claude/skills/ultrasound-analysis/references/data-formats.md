# Raw data layouts

Three distinct on-disk formats, one per acquisition family. Recognising them is
how you route a folder to a pipeline.

---

## 1. xAM / B-mode voltage ramp — `Imgdata_Vseq*.mat`

Filename template:

```
Imgdata_Vseq<NNN>_<pulseShape>_<code>_<alpha>deg_<Xap>ap_<hv>V_<pers>Pers.mat
Imgdata_Vseq001_axicon_AM_19.5deg_65ap_3.0V_0.0Pers.mat      L22
Imgdata_Vseq001_axicon_AM_20.0deg_35ap_6.0V_0.0Pers.mat      GE
```

In-vivo runs zero-pad wider (`Vseq00001`), so match `Vseq0*(\d+)` not a fixed width.
The Vseq index is 1-based and is the authoritative frame ordinal — **sort by it,
not lexically**, or frame 10 lands before frame 2.

MATLAB v7 (`scipy.io.loadmat` reads it). Two top-level variables:

### `ImgData`
| Field | Shape | Meaning |
|---|---|---|
| `Imb` | `(nZ, nX)` | B-mode image, **linear** scale |
| `Xb`, `Zb` | `(nX,)`, `(nZ,)` | B-mode lateral / depth axes, mm |
| `Imx` | `(nZ, nX)` | xAM image, **linear** scale |
| `Xx`, `Zx` | `(nX,)`, `(nZ,)` | xAM axes, mm |

The xAM and B-mode grids differ (xAM starts deeper — the X-beam crossing point),
so both must be interpolated onto a common grid before ROI statistics are
comparable. `us_proc`'s `compute_common_grid` takes the intersection of the two
ranges and the smaller of the two sample counts.

Typical sizes: L22 plate `Imb (1237, 64)`, `Imx (1137, 64)`;
GE plate `Imb / Imx (1761, 158)`.

An older single-image variant exists with `ImgData.Im` / `.x` / `.z` and no
B-mode; `us_proc.load_mat_frame` handles it by filling `Imb` with zeros
(B-mode metrics then come out NaN).

### `P` — acquisition parameter struct
The whole acquisition state. Fields that matter downstream:

| Field | Use |
|---|---|
| `Vseq` | full voltage sequence, one entry per frame in the folder |
| `seed` | the **pre-collapse** portion; frames with `Vseq_idx > len(seed)` are post-collapse |
| `hv` | voltage of this particular frame (fallback if `Vseq` lookup fails) |
| `pitchSI`, `numEle`, `numRays` | probe fingerprint |
| `txFreq`, `alpha`, `Xap`, `numAccum` | beam configuration |
| `startDepth_mm`, `endDepth_mm` | depth window |
| `notes` | free-text run note (see caveat below) |
| `saveDirName`, `saveDirName1`, `dir_save` | original acquisition paths |
| `wellROI`, `noiseROI` | live-acquisition ROI fractions (not the analysis ROIs) |
| `interfacePos` | GE only — auto-depth interface QC |
| `HP` | legacy pressure struct; **stale on GE data**, ignore it |

`P.notes` is sometimes a MATLAB `char` array (readable) and sometimes a MATLAB
`string` object, which is stored as an opaque MCOS handle that scipy cannot
resolve — it comes back as a `MatlabOpaque` record containing the literal bytes
`b'MCOS'`. Treat that case as "no note" rather than printing the byte soup.

---

## 2. BURST — `image_block_###.mat`

A flat folder of numbered blocks, one image per file, MATLAB **v7.3 (HDF5)** —
`scipy.io.loadmat` raises `NotImplementedError`, use `h5py`.

| Key | Shape | Note |
|---|---|---|
| `RData` | `(nx, nz)` | one frame — **transposed** relative to `Imgdata` convention |
| `x`, `z` | `(nx,)`, `(nz,)` | axes in mm (also mirrored under `P/x`, `P/z`) |
| `P/numPreColFrames` | scalar | frames before collapse |
| `P/numColFrames` | scalar | frames during collapse |
| `P/numPostColFrames` | scalar | frames after collapse |
| `P/nImgFrms` | scalar | total, = number of blocks |
| `P/probe` | char | e.g. `L22-14vX` (uint16 char array in HDF5) |
| `P/saveDirName` | char | the condition-encoding folder name |

Example: 40 blocks = 10 pre + 20 collapse + 10 post, `RData (178, 203)`,
x ∈ [−4.45, 4.45] mm, z ∈ [2, 12] mm.

Reconcile orientation by shape, not by assumption:
`im = RData if RData.shape == (len(z), len(x)) else RData.T`.

Folder names encode the sample layout, e.g.
`{N3,v10+Ca,x2;N3,mAK+Ca,x2,N3,v10,x2,N3,mAK,x2}2023-07-31@16-26-22`
— `N3` = n of 3, `x2` = two ROIs per acquisition, trailing `@` timestamp.

---

## 3. Doppler / fUS — `UF.mat` + `fUS_block_###.bin` (+ `Dop.mat`)

| File | Content |
|---|---|
| `UF.mat` | acquisition parameters (see below) |
| `fUS_block_###.bin` | raw beamformed IQ, flat `double` array |
| `Dop.mat` | **output** of the MATLAB processing step: `Dop (nz, lat_resol, NbOfBlocs)` power |

`.bin` reshape (this is where probe mismatch bites):

```
tmp        = raw doubles                              # nz*2*lat_resol*numFrames
IQ_temp    = reshape(tmp, [nz, 2*lat_resol, numFrames])
IQ_signal  = IQ_temp(:, 1:lat_resol, :) + 1i*IQ_temp(:, lat_resol+1:end, :)
```

`nz` falls out of the total size; `lat_resol` is 128 for L22 and 384 for GE.
An L22 block is 37 683 200 bytes = 4 710 400 doubles = 92 × 2×128 × 200.

`UF` fields: `Probe`, `Depth [start end]` mm, `NbOfBlocs`, `TwFreq`, `RcvFreq`,
`numFrames`, `dopAngle` (15 angles, rad), `dopFrameRate`, `ImgVoltage`,
`Lambda` (mm), `nAccum`, `sampling_mode`, `AntiAliasingFilter`, `TW`, `TX`,
`path_save`, `dir_save`. Newer datasets also store `lat_resol` and `PDelta`.

Processing (`Scripts/Processing/Doppler_processing_JWY_bothProbes.m`):
per block, SVD-filter the space-time IQ matrix, discard the top `n_eig = 20`
eigen-components (tissue clutter), and take
`Dop = mean(|IQ_filtered|², 3)` — power Doppler. Display uses `sqrt(Dop)`.

Folder names carry the imaging plane and state, e.g.
`6V-Doppler-2.0mm_imagingPlane_pre` — voltage, plane offset in mm, and
pre/post-session. The plane labelled `imagingPlane` is the one that matches the
xAM acquisitions and is the correct one to overlay.

---

## Companion CSVs

| File | Header signature | Purpose |
|---|---|---|
| well map | `acoustic_plate_reader_well, well1, well2, well3` | GE scan position → 3 physical wells |
| metadata | `well, sample, condition, ...` | per-well sample annotation, joined into results |
| 384→96 map | `384_id, 384_well, 96_well, 96_plate` | source-plate bookkeeping |

Metadata `well` IDs are normalised by stripping leading zeros
(`A01` → `A1`) before joining. GE results carry `well_id` values that may have a
`_W1`/`_W2` replicate suffix; that suffix is stripped before the metadata join so
all three wells at a scan position map to the same metadata row.
