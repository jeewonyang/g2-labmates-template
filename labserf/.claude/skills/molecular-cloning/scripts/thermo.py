"""Primer melting temperature, nearest-neighbour thermodynamics.

SantaLucia (1998) unified nearest-neighbour parameters with the Owczarzy (2008)
salt correction, run at NEB Q5 / NEBuilder HiFi reaction conditions. Those are
the tools the lab designs against (NEBaseChanger for KLD, NEBuilder for Gibson),
so matching them is what makes a computed Tm comparable to the numbers already
in Primer_All.

Only the template-annealing part of a primer contributes to Tm. A 5' tail that
does not bind the template (a Gibson homology arm, a BsaI site, a mutagenic
overhang) is excluded — see `anneal_region`.
"""

from __future__ import annotations

import math
import re

R_GAS = 1.9872  # cal/(K*mol)

# SantaLucia 1998 unified parameters: dH (kcal/mol), dS (cal/(mol*K))
NN = {
    "AA": (-7.9, -22.2), "TT": (-7.9, -22.2),
    "AT": (-7.2, -20.4), "TA": (-7.2, -21.3),
    "CA": (-8.5, -22.7), "TG": (-8.5, -22.7),
    "GT": (-8.4, -22.4), "AC": (-8.4, -22.4),
    "CT": (-7.8, -21.0), "AG": (-7.8, -21.0),
    "GA": (-8.2, -22.2), "TC": (-8.2, -22.2),
    "CG": (-10.6, -27.2), "GC": (-9.8, -24.4),
    "GG": (-8.0, -19.9), "CC": (-8.0, -19.9),
}
INIT_GC = (0.1, -2.8)   # initiation with terminal G or C
INIT_AT = (2.3, 4.1)    # initiation with terminal A or T

# NEB Q5 / NEBuilder HiFi reaction.
#
# `na_eff_mM` is the effective monovalent concentration the salt correction is
# evaluated at. It is not a pipetted concentration: it was fitted so that this
# module reproduces the Tm values the lab already recorded from NEB's own
# calculators in Sequences/Sequence_JWY/Primer_All(Sheet1).csv.
#
# This calibrated model is the lab's chosen authority for Tm (decided 2026-09-19)
# in preference to SnapGene's, IDT's or Benchling's, because it keeps new primers
# on the same scale as every primer already in Primer_All.
#
# Calibration, 23 primer pairs from that file with unambiguous annealing
# regions: mean error -0.4 C, sd 2.4 C, 18/23 within +/-2 C. The residual
# outliers are all NEBaseChanger (KLD) rows whose recorded value sits above the
# lower primer's Tm, i.e. where the recorded number was not the lower-Tm rule.
# Treat a computed Ta as accurate to about +/-2 C, which is well inside the
# tolerance of a Q5 anneal step.
Q5 = dict(primer_nM=500.0, na_eff_mM=250.0)


def clean(seq: str) -> str:
    return re.sub(r"[^ACGT]", "", (seq or "").upper())


def gc_percent(seq: str) -> float:
    s = clean(seq)
    if not s:
        return 0.0
    return 100.0 * (s.count("G") + s.count("C")) / len(s)


def _nn_enthalpy_entropy(seq: str):
    dh, ds = 0.0, 0.0
    for i in range(len(seq) - 1):
        pair = seq[i:i + 2]
        if pair not in NN:
            return None
        h, s = NN[pair]
        dh += h
        ds += s
    for end in (seq[0], seq[-1]):
        h, s = INIT_GC if end in "GC" else INIT_AT
        dh += h
        ds += s
    return dh * 1000.0, ds


def _monovalent_equivalent(cond) -> float:
    """Effective [Na+] in mol/L for the salt correction."""
    return max(cond["na_eff_mM"] / 1000.0, 1e-6)


def tm(seq: str, conditions: dict | None = None) -> float:
    """Nearest-neighbour Tm in degrees C for the annealing sequence given."""
    s = clean(seq)
    if len(s) < 8:
        return float("nan")
    cond = dict(Q5)
    if conditions:
        cond.update(conditions)
    hs = _nn_enthalpy_entropy(s)
    if hs is None:
        return float("nan")
    dh, ds = hs
    ct = cond["primer_nM"] * 1e-9
    # Non-self-complementary duplex: CT/4.
    tm_1m = dh / (ds + R_GAS * math.log(ct / 4.0))
    na = _monovalent_equivalent(cond)
    fgc = gc_percent(s) / 100.0
    ln_na = math.log(na)
    # Owczarzy 2004 salt correction (monovalent form).
    inv = (1.0 / tm_1m) + ((4.29 * fgc - 3.95) * ln_na + 0.940 * ln_na ** 2) * 1e-5
    return 1.0 / inv - 273.15


def anneal_region(primer: str) -> str:
    """The part of a primer that binds the template.

    Lab convention, used consistently in Primer_All: the 5' tail that does not
    anneal is written in lowercase and the annealing 3' part in uppercase. When
    a primer is written in a single case there is no tail to strip and the whole
    primer anneals — callers that know the template should instead use
    `anneal_region_vs_template`.
    """
    p = (primer or "").strip()
    if not p:
        return ""
    m = re.match(r"^[acgtn]+", p)
    if m and m.end() < len(p) and re.search(r"[ACGTN]", p[m.end():]):
        return clean(p[m.end():])
    return clean(p)


def anneal_region_vs_template(primer: str, template: str, circular: bool = True,
                              min_match: int = 10) -> str:
    """Longest 3' stretch of `primer` that matches `template` (either strand).

    This is the authoritative way to split tail from annealing region: it does
    not depend on how the primer was capitalised. Returns "" if nothing of at
    least `min_match` bases matches.
    """
    from snapgene import rc
    p = clean(primer)
    t = clean(template)
    if circular and t:
        t = t + t[:max(len(p), 1)]
    both = t + "\x00" + rc(t)
    best = ""
    for start in range(0, len(p) - min_match + 1):
        cand = p[start:]
        if cand in both:
            best = cand
            break
    return best


def hairpin_dg(seq: str) -> float:
    """Crude worst-case hairpin stability, kcal/mol (negative = more stable).

    Not a folding engine: it scores the most stable stem of >=4 bp with a loop
    of >=3 nt, which is enough to catch the hairpins that actually break a PCR.
    """
    from snapgene import rc
    s = clean(seq)
    worst = 0.0
    n = len(s)
    for stem_len in range(4, min(12, n // 2) + 1):
        for i in range(0, n - stem_len):
            stem = s[i:i + stem_len]
            target = rc(stem)
            j = s.find(target, i + stem_len + 3)
            if j == -1:
                continue
            hs = _nn_enthalpy_entropy(stem)
            if hs is None:
                continue
            dh, ds = hs
            loop = j - (i + stem_len)
            dg = (dh - 310.15 * ds) / 1000.0 + 1.75 * math.log(max(loop, 3) / 3.0) + 3.0
            worst = min(worst, dg)
    return worst


def self_dimer_dg(seq: str) -> float:
    """Worst 3'-end self-dimer, kcal/mol."""
    return _dimer_dg(seq, seq)


def hetero_dimer_dg(a: str, b: str) -> float:
    return _dimer_dg(a, b)


def _dimer_dg(a: str, b: str) -> float:
    from snapgene import rc
    A = clean(a)
    B = clean(b)
    if not A or not B:
        return 0.0
    Brc = rc(B)
    worst = 0.0
    for offset in range(-(len(Brc) - 1), len(A)):
        matched = []
        run = []
        for i in range(len(A)):
            j = i - offset
            if 0 <= j < len(Brc) and A[i] == Brc[j]:
                run.append(A[i])
            else:
                if len(run) >= 3:
                    matched.append("".join(run))
                run = []
        if len(run) >= 3:
            matched.append("".join(run))
        for m in matched:
            hs = _nn_enthalpy_entropy(m)
            if hs is None:
                continue
            dh, ds = hs
            dg = (dh - 310.15 * ds) / 1000.0
            # A duplex involving the last 5 bases of either primer blocks
            # extension, so weight it as reported rather than discounted.
            worst = min(worst, dg)
    return worst


def three_prime_dimer_dg(a: str, b: str, window: int = 6) -> float:
    """Dimer stability restricted to the 3' ends, which is what stalls PCR."""
    return _dimer_dg(clean(a)[-window:], clean(b)[-window:])


def annealing_temperature(tm_f: float, tm_r: float, polymerase: str = "Q5") -> float:
    """Recommended Ta from a primer pair's Tm values.

    NEB's rule for Q5 and the HiFi master mix: anneal at the lower of the two
    primer Tm values (+1 C), capped at 72 C. Both KLD (NEBaseChanger) and
    Gibson (NEBuilder) reactions in this lab use Q5-family enzymes.
    """
    lo = min(tm_f, tm_r)
    if polymerase.upper() in ("Q5", "HIFI", "NEBUILDER", "KLD"):
        return min(round(lo + 1.0), 72.0)
    return min(round(lo), 72.0)
