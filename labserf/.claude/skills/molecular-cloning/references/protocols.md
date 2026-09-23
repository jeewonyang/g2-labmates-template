# Bench protocols

Condensed from two sources that agree with each other:
`Protocols/Protocl_ZJ_201006.docx` (Zhiyang Jin) and
`Protocols/CloningProtocol_JWY.xlsx`, which is the same workflow laid out as a
step table with a few extra specifics. Where they differ, the JWY sheet wins —
it is the later one. The ZJ document also covers protein expression and
inclusion-body purification, which are out of scope here; read it directly for
those.

**Time budget for one round**, from the JWY sheet: PCR 2–3 h · gel 30 min ·
extraction 1 h · KLD/Gibson 0.5–1 h · transform 0.5–1 h · rescue 0.5 h ·
plating + overnight · colonies + miniprep 2 h + overnight. Two days if nothing
goes wrong.

Quote these numbers when handing a design over, so the bench steps and the
design come out of the same place.

## PCR — ~2.5 h

Dilute primers 10× in water to 10 µM. Add the master mix last.

| | |
|---|---|
| 2× Q5 Hot Start HiFi master mix | 25 µL |
| 10 µM forward primer | 2.5 µL |
| 10 µM reverse primer | 2.5 µL |
| template | 1 µL (~10 ng/µL recommended) |
| water | 19 µL |

```
98 °C   1 min
  98 °C   10 s
  Ta      30 s          ×28 for >2 kb,  ×32 for <2 kb
  72 °C   30 s per kb
72 °C   5 min           (double it for long products)
4–10 °C hold
```

`Ta` is the number in the `ta` column of the primer CSV this skill writes.

## Gel and extraction — ~1 h

1 % agarose in 1× TAE (~15 min to set in the cold room), 5–7 µL of 1000× SYBR
Safe for a small gel. Load 50 µL of DNA + 10 µL Purple 6× dye (SDS or no-SDS
both work); 15 µL ladder. Run 110 V for ~30 min.

Gel extraction: weigh the slice (100 mg ≈ 100 µL). Add 3 volumes QG (or just
600 µL), 50 °C for 10 min at 700 rpm, vortexing every 2–3 min until dissolved.
Add 1 volume isopropanol (or 200 µL). Spin through a QIAquick column at
13 000 rpm 1 min; optional 300 µL QG wash; 750 µL PE wash; spin dry 2 min;
elute in 10 µL water, 5 min, 1 min spin.

## KLD — 5–10 min at room temperature

| | |
|---|---|
| KLD reaction buffer | 2.5 µL |
| PCR product | 2 µL (concentration does not matter) |
| KLD enzyme mix | 0.5 µL |

Mix on ice. Room temperature for 5–10 min; **5:30–6 min** is what ZJ used.

> If no colonies form, run the KLD longer. If you see deletions at the junction
> where KLD joined the two ends, run it shorter.

## Gibson / HiFi — 60 min at 50 °C

Measure vector and insert concentrations and get the ratio from NEBioCalculator.
As much vector mass as practical; **insert:vector ≥ 3:1** by molar ratio (less
can work). In practice the JWY sheet says **4 µL vector + 1 µL insert** is
usually close enough. Make up to 5 µL with water, add 5 µL 2× HiFi master mix.
50 °C for 60 min, hold at 4 °C.

Transform immediately is the official advice; holding at 4 °C or −20 °C before
transforming works fine in practice.

## Golden Gate / MoClo

Not in the ZJ protocol — the standard one-pot cycling for a BsaI or BsmBI
assembly of the kind this skill designs:

```
  37 °C  5 min          ×25–30
  16 °C  5 min
60 °C  5 min            (final digest of any re-ligated parent)
```

Equimolar parts, ~40 fmol each, with T4 ligase and the Type IIS enzyme in T4
ligase buffer. Select on the acceptor's antibiotic and screen by dropout colour
— `G12_pMTK678_mScarlet` goes from red to white, `pPBFRT-cRed` and
`pPBFRT-amilCP` similarly. **Colour screening is the reason to keep using the
chromoprotein acceptors**; it saves a miniprep round.

## Transformation

**Mix & Go (in-house):** thaw on ice ~10 min. 1 µL pure plasmid (>50 ng) /
2.5 µL KLD / 2.5 µL Gibson + ~50 µL cells. Ice >7 min. Into 500 µL SOC.

**Chemically competent (NEB):** thaw on ice 10 min. Same DNA amounts + ~15 µL
cells. **Do not mix during the transformation.** Ice 30 min, 42 °C 30 s, ice
5 min, into 500 µL SOC.

**Electrocompetent:** cuvette on ice. Pipette the DNA onto the cuvette wall and
wash it off with the cells. Electroporate immediately — **setting EC2** — and add
1000 µL SOC into the cuvette right after.

**Rescue:** 37 °C for 1 h in SOC. Ampicillin constructs do not strictly need
it. Plate 100–150 µL. Grow 10–12 h at 37 °C (Turbo, BL21(DE3), BL21-AI) or
16–20 h at 30 °C (Stbl and others).

## Colonies and miniprep

Pick ~3 colonies per sample into 3 mL 2×YT with antibiotic (and 2 % glucose if
needed). Grow to saturation: 10–14 h at 37 °C — **not past 16 h** — or 12–18 h
at 30 °C.

Glycerol stock first: 100 µL 50 % glycerol + 100 µL culture, 96-well plate at
−80 °C.

Miniprep: pellet 13 000 rpm 3 min. 250 µL P1 (4 °C — **check RNase has been
added**), vortex. 250 µL P2 (from the 30 °C incubator), invert only, sit 2–3 min
and **no longer than 5**; there should be *no* precipitate at this stage.
350 µL N3 (also 30 °C), invert — now expect a white precipitate. Spin 10 min. Supernatant onto the column, 1 min. Optional 500 µL PB. 750 µL PE,
1 min. Spin dry 2 min. Elute 50 µL water into the middle of the column, stand
>5 min, spin 1 min.

Check A260/280 ≈ 1.8 and A260/230 ≈ 2.0. Store at −20 °C.

**Sequencing:** 350 ng per reaction (or 5 µL if the concentration is low or
unknown) + 3 µL of 10 µM primer.
