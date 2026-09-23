---
name: molecular-cloning
description: Design cloning strategies and primers for this lab's plasmids - Gibson/NEBuilder HiFi, KLD site-directed mutagenesis and deletion, restriction-enzyme cloning, and MoClo/Golden Gate assembly with the Mammalian Tool Kit (MTK parts into TUs, TUs into final plasmids). Use whenever a SnapGene .dna map is the input and a new construct, a primer order, or an assembly plan is the output, or when asked what MTK parts and TUs are available, how an existing plasmid was built, or what Tm/Ta to run a PCR at.
---

# Molecular cloning

Input is one or more SnapGene `.dna` maps. Output is **a `.dna` map of the
finished construct plus a primer CSV in the lab's Primer_All format** — always
both, written to disk, never a sequence pasted into chat.

Both land in **`Sequences/_designs/`** by default, which is a staging area, not
the collection. `-o` overrides it. Nothing else under `Sequences/` is ever
written to; a design graduates into `MammalianToolKit/` or `Sequence_JWY/` by
hand, once it has actually been built and sequenced.

Everything runs on the standard library. There is no biopython, no primer3, no
network call; `scripts/snapgene.py` reads and writes the `.dna` format directly,
and its output has been confirmed to open in SnapGene.

## Pick the method before touching a tool

| Situation | Method |
|---|---|
| The construct is standard MTK parts or TUs rearranged | **MoClo** — no primers at all |
| Point mutation, small insert, deletion, or domesticating a BsaI/BsmBI site | **KLD** |
| Joining pieces from two different plasmids, or a junction with a linker | **Gibson** |
| The vector and insert already share usable unique sites | **RE** |

**Check MoClo first.** Most requests in this lab are a TU swap, and a TU swap
needs no oligos — an afternoon of Golden Gate instead of a PCR, a gel and a
primer order. Search the catalog before designing a primer:

```bash
python scripts/inventory.py --search jGCaMP8
python scripts/inventory.py --slot 2
python scripts/inventory.py --category "MTK0 backbone"

# Which components carry enzyme sites they should not
python scripts/qc_sites.py
```

## Commands

All of them take and produce real files. `-o` sets the output directory and
defaults to `Sequences/_designs/`.

```bash
# What is this plasmid, and what can it assemble with?
python scripts/cloning.py inspect PLASMID.dna

# How was it built? (SnapGene stores the whole provenance tree)
python scripts/history.py PLASMID.dna --tree

# Build a plasmid, making any missing TU from MTK parts on the way.
# Each intermediate is written as its own named, numbered, history-carrying map.
python scripts/cloning.py build --backbone MTK0.dna \
    --tu1-parts ConLS.dna PROM.dna CDS.dna UTR.dna ConR1.dna \
    --tu2 TU2-19.dna --tu3 TU3-10.dna --tu4 TU4-6.dna

# Which construct IDs are taken, and what comes next
python scripts/cloning.py ids

# A single assembly step, named by hand
python scripts/cloning.py moclo --parts P1.dna P2.dna ... --acceptor ACC.dna -o out
python scripts/cloning.py moclo --tus TU1.dna TU2.dna ... --backbone MTK0.dna

# KLD: delete 500..620, optionally putting something in its place
python scripts/cloning.py kld PLASMID.dna --delete 500-620 --insert ATGGTG -o out

# Gibson: open the vector between two bases, drop in a region of another plasmid
python scripts/cloning.py gibson --vector V.dna --open 1555,1343 \
    --insert I.dna --region 1075-2010 --extra5 GGCAGCGGC -o out

# Restriction cloning: amplify a region with sites added
python scripts/cloning.py re --template T.dna --region 50-800 \
    --five NdeI --three XhoI -o out
```

Coordinates are **1-based and inclusive**, matching what SnapGene displays, and
ranges may wrap the origin on a circular map.

`--open AFTER,BEFORE` is the pair of bases that stay: the vector is kept from
`AFTER+1` forward around to `BEFORE-1`, and everything between them is replaced
by the insert. To open a vector without deleting anything, pass `N,N+1`.

## Naming and IDs

```
mL-<id>_<components>      Lentiviral            mL-88_pLV-TRE-NV-WPRE-mEF1a-BSD
mT-<id>_<components>      Transient             mT-31_pCMV-A-IRES-28a-P2A-emiRFP
mPB-<id>_<components>     piggyBac              mPB-1_pPB-TRE-GvpA
TU<slot>-<id>_<L>_<R>_<components>              TU1-50_LS_R1_TRE-jGCaMP8m-WPRE
<wellID>_pMTK<type>_<desc>   MTK kit part       A1_pMTK1_ConLS,  C5_pMTK2_TRE
mG-<id>_pMTK<type>_<desc>    lab-made part      mG-26_pMTK3-emiRFP670
```

`build` assigns these itself: the backbone decides the prefix, the slot and
connectors come from the assembled TU rather than from what you assumed, and
the ID is the next free one in that series. `--desc`, `--id` and `--kind`
override.

**Three independent series**, one per delivery method. `--kind` is required
when the backbone matches none of the patterns — landing-pad backbones
(`phiC31-attB`, `BxBI-attB`, `hAAVS1`) are the ones that land there.

**`mPB` continues the piggyBac numbering recorded under `mT`**, so the first
one is `mPB-116`. `mT` and `mPB` share one run of numbers — allocating either
advances both — so every piggyBac construct sits on a single sequence whichever
prefix it carries. `mL` numbers independently.

**Reading the old collection:** `mT` was used for most piggyBac work before
this convention settled — 65 of the 80 `mT-*` files carry a `pPB` vector and
only 9 are genuinely transient. Those keep their names. New piggyBac work is
`mPB`.

**MTK part labels.** A well ID (`A1`, `C5`, `G12`) is the part's position in
the original kit plate and cannot be assigned by software, so anything created
here is lab-made and takes an `mG-<id>_pMTK<type>_<desc>` name instead.

**IDs skip outliers.** `TU2-772_L1_R2_IRESv10_m772_WPRE-pA` is the TU for
construct m772, not the 772nd TU; `ids` reports such names and excludes them,
so the series continues at 35 rather than jumping to 773.

**Sequence_JWY numbering is treated as loose.** It grew per-project and was
never consolidated, so it does not advance a series — but its IDs are still
avoided, so a generated name can never collide with a file on disk. Only
`MammalianToolKit/` drives the numbering forward.

**A TU that already exists is reused, not renumbered.** Before writing a new
TU, `build` compares its released insert against every catalogued TU for that
slot; an exact match is used in place of a new ID, and a same-components
near-match is reported with its size difference so you can check you did not
mean the existing one. `--force-new-tu` overrides.

## Build the intermediate, not just the endpoint

When a construct can be reached by making a new TU — or a new MTK part — and
reassembling, **do that rather than editing the finished plasmid**. The TU is
reusable, the assembly needs no primers, and every junction is a known-good
fusion site instead of a fresh PCR product to sequence. `build` writes each
intermediate as its own file so it joins the collection in its own right.

Reach for KLD or Gibson on a final plasmid only when no part-level route
exists — a point mutation inside a CDS, or a junction the MTK grammar cannot
express.

## How to work

**Read the map before designing against it.** Run `inspect` and name the
features you are cutting between. A coordinate the user gives you from memory
is worth checking against the annotation; a coordinate you inferred from a
feature name is worth stating back to them.

**Report the warnings.** Every design prints `!` lines — Tm mismatch, internal
enzyme sites, hairpins. Do not filter them out to make a result look clean.
`references/primer-design.md` says which ones matter and which are cosmetic.

**Say what the product is.** Length, topology, what changed, and what to screen
for. A `.dna` file the user has to open to find out what you did is half a
deliverable.

**Do not invent sequence.** Every base in a product comes from a file on disk or
from sequence the user supplied. If a part does not exist, say so and propose
how to make it, rather than synthesising a plausible one.

## Verify before you hand over

```bash
python scripts/validate.py --sweep
```

This rebuilds the lab's own constructs from the assembly history stored inside
their `.dna` files and compares base for base — currently **231 constructs
rebuilt exactly, 0 wrong** — plus a `.dna` round trip, the KLD geometry, and the
Tm model against recorded values. Run it after changing anything in `scripts/`.

For a one-off design, the check that matters is cheaper: re-open the product
with `inspect` and confirm the length, the topology and that the features you
expected survived.

## Reference

- `references/primer-design.md` — the design rules (Primer_All + the lab protocols + Addgene), the Tm model and its
  measured accuracy (±2 °C), and what to do when a PCR fails.
- `references/moclo-mtk.md` — the MTK grammar: part types, fusion sites,
  connectors, TU slots.
- `Sequences/_domestication/` — the live list of components carrying Type IIS
  sites they should not, split into blocking / latent / informational, with the
  part-to-broken-TU causal chain. Regenerate with
  `python scripts/qc_sites.py --write`; check it before committing to a part
  you have not used before.
- `references/protocols.md` — bench steps, from the lab's own protocol:
  PCR mix and cycling, gel extraction, KLD, Gibson, Golden Gate, transformation,
  miniprep, sequencing.
- `assets/mtk_inventory.csv` — every part, TU and backbone with its measured
  overhangs. Rebuild with `python scripts/inventory.py --refresh` after new
  plasmids land in `Sequences/MammalianToolKit/`.

## What each product carries

Outputs are self-documenting, so a `.dna` handed to someone else explains itself:

- **History.** Every product records a SnapGene History tree. A MoClo product
  nests each input's *own* ancestry inside it, so the finished plasmid shows the
  TUs it came from, the MTK parts those came from, and the gBlocks and Gibson
  steps below that. `history.py PRODUCT.dna --tree` reads it back.
- **Features from every parent.** Annotation is carried onto the product by all
  four paths: a Gibson product keeps the vector's features that survive in the
  retained backbone plus the insert's features from the amplified region, KLD
  remaps them across the edit, MoClo carries each fragment's. A feature
  spanning a junction is dropped rather than truncated — a half-feature reads
  as if the whole element were there. Added restriction sites and junction
  linkers are annotated in their own right.
- **Primers, drawn on the map.** A primer-based design stores the designed
  oligos in the product with their `<BindingSite>` computed, so SnapGene renders
  them on the main display rather than only listing them in the primer panel —
  a `<Primer>` with no binding site is invisible on the sequence view. Tm, Ta
  and any warnings go in each primer's description.

**Never delete or overwrite files already in the output directory.** Other
designs live there. Add, do not tidy.

## Output conventions

Primer CSVs use the lab's column order — `Date, name, sequence, ta, Note` — with
`ta` written once per pair on the forward row, so a block pastes straight into
`Sequences/Sequence_JWY/Primer_All(Sheet1).csv`. Diagnostic columns (Tm,
length, GC, template length, warnings) follow to the right and are ignored by
that paste.

The length beside Ta is the **PCR product**, as `"63C; 2615 bp (template name)"`
— that is what sets the cycling (30 s per kb of amplicon, and the ~10 kb point
where a long-range protocol is needed). The template is named there but its
length lives in the `template_len_bp` column.

Primer sequences are written with the **5' tail in lowercase and the annealing
region in UPPERCASE**, which is the lab's convention throughout Primer_All and
the thing that tells you at a glance what the Tm was computed on.
