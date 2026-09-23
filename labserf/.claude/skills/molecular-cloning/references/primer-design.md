# Primer design rules

Three sources, in order of authority when they disagree: the ~250 primers
already ordered in `Sequences/Sequence_JWY/Primer_All(Sheet1).csv` (what
demonstrably worked here), `Protocols/Protocl_ZJ_201006.docx` plus
`Protocols/CloningProtocol_JWY.xlsx` (the lab's own written procedure), and
[Addgene's primer design guide](https://www.addgene.org/protocols/primer-design/)
for anything the first two are silent on. `scripts/design.py` enforces the
result; this file is the reasoning behind it, and what to do when it warns.

## The one convention that matters

**Lowercase = 5' tail that does not touch the template. UPPERCASE = the part
that anneals.**

```
accttagtcgacTTCCTGTCCGAGACTGCG
└── tail ──┘└──── anneals ────┘
```

Tm is computed on the uppercase part only. This is not cosmetic: a 40-mer
Gibson primer with a 20-nt homology arm has the Tm of its 20-nt 3' half, and
running the PCR at the Tm of the whole oligo will fail in the first cycles,
before the tail has anything to bind. Every primer emitted by this skill is
capitalised this way, and so is almost every primer in Primer_All.

## Geometry per method

| | Forward primer starts | Reverse primer starts | Tail carries |
|---|---|---|---|
| **KLD** | base immediately *after* the edited region | base immediately *before* it | the inserted/mutated bases |
| **Gibson, vector** | first base kept, going forward | last base kept, going back | nothing |
| **Gibson, insert** | first base of the insert | last base of the insert | 20 nt of vector homology |
| **RE** | first base of the insert | last base of the insert | pad + recognition site |

The protocol states this as **"Begin-1 / End+1"**: the primers point *away*
from the region being removed, so the PCR product is everything you want to
keep. The anchored end of each annealing region is therefore fixed by the
junction — only the 3' end is free, which is why primer length is the only
tuning knob.

## Numeric targets

| Property | Target | Hard limit | Source |
|---|---|---|---|
| Annealing region Tm | 60–65 °C | 55–72 °C | lab practice — see note |
| Tm difference within a pair | ≤ 2 °C | ≤ 5 °C | Addgene, "within 5 °C" |
| Annealing length | 18–25 nt | 14–30 nt | Addgene 18–24, never >30-mer |
| GC content | 40–60 % | 35–65 % | Addgene |
| Gibson homology arm | 20 nt | 18–25 nt | Primer_All |
| 3' end | G or C | not GGG/CCC | Addgene, "end with 1–2 G/C" |
| 5' end of the annealing region | G or C preferred | never a poly-A/T run | ZJ protocol + Addgene |
| RE clamp 5' of the site | 3–6 bp | — | Addgene |
| Amplicon size | 1–10 kb | warns outside | Addgene |
| Hairpin ΔG | > −3 kcal/mol | > −5 | convention |
| 3' dimer ΔG | > −6 kcal/mol | > −9 | convention |

**Two deliberate divergences from Addgene:**

*Tm 60–65 °C, not Addgene's 50–60 °C.* That guidance is generic, written around
Taq. This lab runs **Q5 Hot Start HiFi** (named in `CloningProtocol_JWY.xlsx`),
and the Tm values actually recorded in Primer_All cluster at **59–72 °C**. Using
50–60 here would contradict every primer the lab has successfully ordered.

*Minimum annealing length 14 nt, not 18.* Back-to-back KLD primers have their 5'
end pinned by the junction, so on a GC-rich junction the only way to avoid a
70 °C primer is to go short. The lab's own primers go to 10–13 nt in exactly
this situation and work.

**Tm match matters more than absolute Tm.** A pair is only as good as its lower
primer: the Ta is set by that one, and the hotter primer then mis-primes. This
is the most common real defect in the existing Primer_All rows — e.g.
`ORF1_kozak_F/R` are 59 °C and 70 °C, an 11 °C gap. `design.pick_pair` picks
both lengths jointly to avoid exactly this, rather than optimising each primer
alone.

**"Should not begin with t or a"** (the protocol's wording) refers to the 5'
base of the annealing region. It is a soft preference and the tool warns rather
than refuses — plenty of shipped lab primers start with A.

## The Tm model, and how far to trust it

`scripts/thermo.py` uses SantaLucia (1998) unified nearest-neighbour parameters
with an Owczarzy salt correction, evaluated at 500 nM primer and an effective
monovalent concentration of 250 mM.

That 250 mM is **fitted, not pipetted.** It was chosen so the module reproduces
the Tm values the lab already recorded from NEB's own calculators. Against 23
pairs from Primer_All with unambiguous annealing regions:

- mean error **−0.4 °C**, sd **2.4 °C**, **18/23 within ±2 °C**

The residual outliers are all NEBaseChanger (KLD) rows whose recorded value sits
*above* the lower primer's Tm, i.e. rows where the number written down was not
the lower-Tm rule. **Treat a computed Ta as ±2 °C.** That is well inside the
tolerance of a Q5 anneal step, but it means you should not argue about one
degree, and for anything precious a gradient PCR still beats a calculation.

Ta for the pair = **lower primer Tm + 1 °C, capped at 72 °C** (the Q5/HiFi
rule). `validate.py` re-checks this against ten recorded pairs every run.

## Secondary structure: what is and is not checked

`scripts/thermo.py` has no folding engine. It scores the most stable stem or
duplex it can find with nearest-neighbour thermodynamics, which catches the
structures that actually break a PCR but will not reproduce mfold or
OligoAnalyzer. Every check below runs on every design:

| Check | Scope | Warns at |
|---|---|---|
| Hairpin | annealing region | dG < −3 |
| Hairpin | **whole oligo, tail included** | dG < −3 and worse than the annealing region alone |
| Self-dimer, 3' end | annealing region | dG < −6 |
| Self-dimer, **full length** | whole oligo | dG < −9 |
| Hetero-dimer, 3' end | forward × reverse, whole oligos | dG < −6 |
| Hetero-dimer, full length | forward × reverse, whole oligos | dG < −12 |
| Cross-complementarity | annealing regions | dG < −12 |

**3' structures are weighted hardest** because a duplex covering the last few
bases blocks extension, whereas a stem in the middle of a primer usually just
costs efficiency. The 3' self-dimer and 3' hetero-dimer terms also feed into
primer *selection*, not just the warnings: `_score` penalises self-dimers when
choosing a length, and `pick_pair` penalises 3' hetero-dimers when choosing the
two lengths together, so a dimer-prone pair is avoided before it is reported.

**Gibson overlaps.** `--homology` sets the arm on each insert primer; the
default is 20 nt, the length used throughout Primer_All, and both junctions get
the same. The vector primers carry no tail — all the homology lives on the
insert, which is why only the insert oligos get long. `validate.py` proves the
overlaps are real rather than nominal: it simulates both PCRs from the primer
sequences alone, finds the longest suffix/prefix match at each junction, joins
them, and compares the result with the designed product. Below about 18 nt the
HiFi mix anneals unreliably; above ~30 you are paying for oligo length without
gaining assembly efficiency.

`--extra5` / `--extra3` splice a linker, a 2A peptide or a Kozak into a
junction. The added bases ride on the insert primer's tail and become part of
the homology, so the arm grows by that much and the vector primers are
untouched.

**Why the tail matters separately.** A Gibson primer is ~20 nt of homology arm
plus ~20 nt of annealing region. Checking only the annealing region misses any
structure the arm creates — and the arm is the half you did not choose, so it
is the more likely culprit. The full-oligo checks exist for exactly that case.

**Limits, stated plainly.** No salt-corrected dG, no loop-penalty tables beyond
a logarithmic term, no multi-branch structures, and dimers are scored from the
longest complementary run rather than a proper alignment. Treat the numbers as
a ranking, not a measurement: a −4 hairpin is worth a second look, a −12
self-dimer is worth redesigning, and a primer that passes here can still fail
at the bench.

## Reading the warnings

`cloning.py` prints a `!` line per problem. They are advisory — the design is
still emitted — but they rank roughly:

- **Tm mismatch > 5 °C** — fix this. Usually means one side of the junction is
  GC-rich; accept a shorter primer there, or move the junction a few bases.
- **Enzyme site inside the amplified region** (RE only) — fatal, pick another
  enzyme.
- **Full-length self-dimer or hetero-dimer** — redesign; the oligos will
  consume each other before they find the template.
- **Hairpin / 3' dimer** — fix if the PCR fails; often survivable.
- **Tail-induced hairpin** — usually means the homology arm or restriction tail
  folds back; shifting the junction a few bases is the cheapest fix.
- **No 3' G/C clamp**, **starts with A/T** — cosmetic unless the PCR is
  misbehaving.

## When the PCR fails anyway

From the protocol and lab practice, in the order worth trying:

1. **Gradient PCR** across Ta ± 6 °C. Cheapest answer to a bad Tm estimate.
2. **Longer extension** — 0.5 min/kb is the floor for Q5; whole-plasmid KLD
   amplicons of 6–10 kb want more.
3. **Add DMSO** (3 %) for GC-rich or structured templates.
4. **Fewer cycles / less template** if you get smears; 1 µL of ~10 ng/µL is the
   protocol's recommendation and more rarely helps.
5. **Redesign with the junction shifted** by 3–6 bases. A junction sitting in a
   repeat or a homopolymer cannot be rescued by thermocycling.
6. **DpnI** the template before KLD if you see parental background — the KLD mix
   includes it, but an old mix may not be working.

## Things the lab's own primer history teaches

- Gibson tails are **20 nt**, essentially without exception.
- Very short annealing regions (10–14 nt) appear in KLD primers where the
  junction is GC-rich; they work. `MIN_ANNEAL` is 14 here for that reason.
- Tails for mutagenesis are frequently split across both primers
  (`2xKTS_F/R`), which is what `design_kld` does for inserts over 18 nt.
- The `ta` column in Primer_All is written **once per pair**, on the forward
  row, as `"63C; 5816 bps (template)"`. `primer_csv.py` reproduces that layout,
  so a block pastes straight into the sheet, with one deliberate change: the
  length beside Ta is the **PCR product**, not the template. That is the number
  the cycling depends on — 30 s per kb of amplicon, and the ~10 kb point where
  you need a long-range protocol. Primer_All itself is inconsistent here
  (vector rows carry the template length, insert rows the product); this is
  consistently the product. The template length remains in the
  `template_len_bp` column to the right.
