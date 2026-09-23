"""Primer design for Gibson (NEBuilder HiFi), KLD (NEBaseChanger) and
restriction-enzyme cloning, following this lab's conventions.

House conventions, taken from Protocols/Protocl_ZJ_201006.docx and from the
primers already in Sequences/Sequence_JWY/Primer_All(Sheet1).csv:

* The annealing region is written UPPERCASE, the non-annealing 5' tail
  lowercase. Every primer this module emits follows that, so a glance at a
  sequence tells you where the template binding starts.
* Gibson homology arms are 20 nt (the length used throughout Primer_All).
* KLD primers sit back to back: the forward primer starts at the base
  immediately after the deleted/edited region, the reverse primer runs
  outward from the base immediately before it. "Begin-1 / End+1" in the
  protocol.
* The annealing region should not begin with A or T; G/C is preferred.
* Ta for the pair is the lower primer Tm + 1 C, capped at 72 C (Q5 rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import thermo
from snapgene import Dseq, Feature, rc

MIN_ANNEAL = 14   # the lab goes shorter still on GC-rich KLD junctions
MAX_ANNEAL = 30   # Addgene: avoid primers longer than a 30-mer
DEFAULT_TM = 62.0
HOMOLOGY_LEN = 20


@dataclass
class DesignedPrimer:
    name: str
    tail: str                  # 5' non-annealing part, emitted lowercase
    anneal: str                # template-binding part, emitted uppercase
    template_name: str = ""
    template_len: int = 0
    role: str = ""
    note: str = ""
    warnings: list = field(default_factory=list)

    @property
    def sequence(self) -> str:
        return self.tail.lower() + self.anneal.upper()

    @property
    def tm(self) -> float:
        return thermo.tm(self.anneal)

    @property
    def length(self) -> int:
        return len(self.sequence)

    @property
    def gc(self) -> float:
        return thermo.gc_percent(self.anneal)

    def __repr__(self):
        return "<%s %dnt Tm=%.1f>" % (self.name, self.length, self.tm)


@dataclass
class PrimerPair:
    forward: DesignedPrimer
    reverse: DesignedPrimer
    product_len: int = 0
    template_name: str = ""
    template_len: int = 0
    description: str = ""

    @property
    def ta(self) -> float:
        return thermo.annealing_temperature(self.forward.tm, self.reverse.tm)

    def warnings(self) -> list:
        w = list(self.forward.warnings) + list(self.reverse.warnings)
        # Secondary structure is judged on the WHOLE oligo, tail included. The
        # per-primer warnings above only saw the annealing region, so a hairpin
        # or self-dimer created by a Gibson arm or a restriction tail — which is
        # where long tails usually cause trouble — would otherwise go unseen.
        for p in (self.forward, self.reverse):
            if not p.tail:
                continue
            hp = thermo.hairpin_dg(p.sequence)
            if hp < -3 and hp < thermo.hairpin_dg(p.anneal) - 0.5:
                w.append("%s: the 5' tail creates a hairpin (dG %.1f kcal/mol "
                         "for the full oligo)" % (p.name, hp))
            sd = thermo.self_dimer_dg(p.sequence)
            if sd < -9:
                w.append("%s: self-dimer over the full oligo (dG %.1f kcal/mol)"
                         % (p.name, sd))
        full = thermo.hetero_dimer_dg(self.forward.sequence, self.reverse.sequence)
        if full < -12:
            w.append("forward and reverse anneal to each other over their full "
                     "length (dG %.1f kcal/mol)" % full)
        dtm = abs(self.forward.tm - self.reverse.tm)
        if dtm > 5:
            w.append("Tm mismatch %.1f C between the two primers (>5 C); the "
                     "high-Tm primer will mis-prime at the Ta the low one needs"
                     % dtm)
        dg = thermo.three_prime_dimer_dg(self.forward.sequence, self.reverse.sequence)
        if dg < -6:
            w.append("3' heterodimer dG %.1f kcal/mol between forward and reverse" % dg)
        cross = thermo.hetero_dimer_dg(self.forward.anneal, self.reverse.anneal)
        if cross < -12:
            w.append("forward and reverse share a complementary region "
                     "(dG %.1f kcal/mol); they will prime each other" % cross)
        if self.product_len > 10000:
            w.append("amplicon is %.1f kb; above ~10 kb expect a long extension and "
                     "consider splitting the PCR or using a long-range polymerase"
                     % (self.product_len / 1000.0))
        elif 0 < self.product_len < 100:
            w.append("amplicon is only %d bp; it will be hard to see on a gel and "
                     "hard to purify" % self.product_len)
        return w


# -- picking an annealing region -----------------------------------------


def _anneal_warnings(seq: str) -> list:
    w = []
    s = seq.upper()
    if s[0] in "AT":
        w.append("annealing region starts with %s; the protocol prefers G/C" % s[0])
    if s[-1] not in "GC":
        w.append("no 3' G/C clamp (ends in %s)" % s[-1])
    if s[-3:] in ("GGG", "CCC", "GGC", "CGG", "GCC", "CCG"):
        w.append("3 G/C in the last three bases; risks mis-priming")
    hp = thermo.hairpin_dg(s)
    if hp < -3:
        w.append("hairpin dG %.1f kcal/mol" % hp)
    sd = thermo.three_prime_dimer_dg(s, s)
    if sd < -6:
        w.append("3' self-dimer dG %.1f kcal/mol" % sd)
    for base in "ACGT":
        if base * 5 in s:
            w.append("run of 5+ %s" % base)
            break
    return w


def _score(seq: str, target_tm: float) -> float:
    """Lower is better. Tm dominates; the rest breaks ties between equal Tms."""
    t = thermo.tm(seq)
    if t != t:  # NaN
        return 1e9
    score = abs(t - target_tm) * 4.0
    s = seq.upper()
    if s[-1] not in "GC":
        score += 3.0
    if s[0] in "AT":
        score += 2.5
    gc = thermo.gc_percent(s)
    if gc < 40 or gc > 65:
        score += 2.0
    score -= min(thermo.hairpin_dg(s) + 3.0, 0) * 2.0
    score -= min(thermo.three_prime_dimer_dg(s, s) + 6.0, 0) * 1.5
    if len(s) > 26:
        score += (len(s) - 26) * 0.4
    return score


def pick_anneal(template: str, anchor: int, direction: int, circular: bool = True,
                target_tm: float = DEFAULT_TM) -> str:
    """Choose the annealing region of a primer anchored at a fixed base.

    `anchor` is the 0-based index of the first templated base of the primer.
    direction +1 walks 3' along the top strand (forward primer); direction -1
    walks leftward and the returned sequence is already reverse-complemented
    (reverse primer). The anchored end is the 5' end of the annealing region —
    it is fixed by the junction being built — so only the 3' end is optimised.
    """
    n = len(template)

    def grab(length: int) -> str | None:
        if direction > 0:
            if not circular and anchor + length > n:
                return None
            return "".join(template[(anchor + k) % n] for k in range(length))
        if not circular and anchor - length + 1 < 0:
            return None
        seg = "".join(template[(anchor - length + 1 + k) % n] for k in range(length))
        return rc(seg)

    best, best_score = None, 1e18
    for cand in _candidates(template, anchor, direction, circular):
        sc = _score(cand, target_tm)
        if sc < best_score:
            best, best_score = cand, sc
    return best or grab(MIN_ANNEAL) or ""


def _candidates(template: str, anchor: int, direction: int, circular: bool) -> list:
    """Every allowed annealing region for a primer anchored at `anchor`."""
    n = len(template)
    out = []
    for length in range(MIN_ANNEAL, MAX_ANNEAL + 1):
        if direction > 0:
            if not circular and anchor + length > n:
                break
            cand = "".join(template[(anchor + k) % n] for k in range(length))
        else:
            if not circular and anchor - length + 1 < 0:
                break
            seg = "".join(template[(anchor - length + 1 + k) % n] for k in range(length))
            cand = rc(seg)
        out.append(cand)
    return out


def pick_pair(fwd_template: str, fwd_anchor: int, rev_template: str, rev_anchor: int,
              fwd_circular: bool = True, rev_circular: bool = True,
              target_tm: float = DEFAULT_TM, fwd_dir: int = 1, rev_dir: int = -1) -> tuple:
    """Choose both annealing regions together.

    Picking each primer's best length independently routinely lands them 5-7 C
    apart, because a primer will happily take a worse Tm to gain a 3' G/C clamp.
    A pair is only as good as its lower Tm, so this optimises the two jointly:
    the cost is each primer's own score plus a penalty on the gap between them
    and on how far the pair's usable (lower) Tm sits from the target.
    """
    fwd = _candidates(fwd_template, fwd_anchor, fwd_dir, fwd_circular)
    rev = _candidates(rev_template, rev_anchor, rev_dir, rev_circular)
    if not fwd or not rev:
        return (fwd[0] if fwd else ""), (rev[0] if rev else "")

    ftm = {f: thermo.tm(f) for f in fwd}
    rtm = {r: thermo.tm(r) for r in rev}
    fsc = {f: _score(f, target_tm) for f in fwd}
    rsc = {r: _score(r, target_tm) for r in rev}

    best, best_cost = (fwd[0], rev[0]), 1e18
    for f in fwd:
        tf = ftm[f]
        if tf != tf:
            continue
        for r in rev:
            tr = rtm[r]
            if tr != tr:
                continue
            gap = abs(tf - tr)
            usable = min(tf, tr)
            cost = (fsc[f] + rsc[r]) * 0.5 + gap * 3.0 + abs(usable - target_tm) * 2.0
            dg = thermo.three_prime_dimer_dg(f, r)
            if dg < -6:
                cost += (-6 - dg) * 2.0
            if cost < best_cost:
                best, best_cost = (f, r), cost
    return best


# -- KLD ------------------------------------------------------------------


def design_kld(plasmid: Dseq, start: int, end: int, insert: str = "",
               name: str = "KLD", target_tm: float = DEFAULT_TM,
               split_insert: bool = True) -> PrimerPair:
    """Back-to-back primers that delete `start..end` and put `insert` in its place.

    Coordinates are 1-based inclusive over the plasmid. To make a pure
    insertion with no deletion, pass end = start - 1.

    The product is the whole plasmid minus the deleted window, amplified
    linearly and re-circularised by the KLD mix. The insert rides on the 5'
    tails: split across both primers when long, otherwise carried entirely on
    the forward primer, which is what NEBaseChanger does.
    """
    seq = plasmid.sequence
    n = len(seq)
    fwd_anchor = end % n            # 0-based index of base end+1
    rev_anchor = (start - 2) % n    # 0-based index of base start-1

    f_anneal, r_anneal = pick_pair(seq, fwd_anchor, seq, rev_anchor,
                                   plasmid.circular, plasmid.circular, target_tm)

    ins = (insert or "").upper()
    if ins and split_insert and len(ins) > 18:
        half = len(ins) // 2
        f_tail, r_tail = ins[half:], rc(ins[:half])
    elif ins:
        f_tail, r_tail = ins, ""
    else:
        f_tail, r_tail = "", ""

    deleted = 0 if end < start else (end - start + 1) % (n + 1)
    product = n - deleted

    f = DesignedPrimer(name + "_F", f_tail, f_anneal, plasmid.name, n, "KLD forward",
                       warnings=_anneal_warnings(f_anneal))
    r = DesignedPrimer(name + "_R", r_tail, r_anneal, plasmid.name, n, "KLD reverse",
                       warnings=_anneal_warnings(r_anneal))
    desc = "KLD on %s: " % (plasmid.name or "template")
    if deleted and ins:
        desc += "replace %d..%d (%d bp) with %d bp" % (start, end, deleted, len(ins))
    elif deleted:
        desc += "delete %d..%d (%d bp)" % (start, end, deleted)
    elif ins:
        desc += "insert %d bp after base %d" % (len(ins), start - 1)
    else:
        desc += "re-circularise unchanged"
    return PrimerPair(f, r, product + len(ins), plasmid.name, n, desc)


def apply_kld(plasmid: Dseq, start: int, end: int, insert: str = "",
              new_name: str = "") -> Dseq:
    """The product plasmid of `design_kld` with the same arguments."""
    seq = plasmid.sequence
    n = len(seq)
    if end < start:
        kept = seq[:start - 1] + (insert or "").upper() + seq[start - 1:]
        removed = 0
    elif start <= end:
        kept = seq[:start - 1] + (insert or "").upper() + seq[end:]
        removed = end - start + 1
    out = Dseq(kept, plasmid.circular, new_name or (plasmid.name + "_KLD"),
               description=plasmid.description)
    delta = len(insert or "") - removed
    for f in plasmid.features:
        if f.start >= start and f.end <= end and removed:
            continue                       # feature lived entirely in the cut
        ns, ne = f.start, f.end
        if ns > end:
            ns += delta
        if ne > end:
            ne += delta
        if 1 <= ns <= len(kept) and 1 <= ne <= len(kept) and ns <= ne:
            from snapgene import Feature
            out.features.append(Feature(f.name, ns, ne, f.strand, f.type, f.color,
                                        dict(f.notes)))
    return out


# -- Gibson ---------------------------------------------------------------


def design_gibson_insertion(vector: Dseq, insert_template: Dseq,
                            vector_open_after: int, vector_open_before: int,
                            insert_start: int, insert_end: int,
                            name: str = "Gib", target_tm: float = DEFAULT_TM,
                            homology: int = HOMOLOGY_LEN,
                            insert_strand: int = 1,
                            extra_5: str = "", extra_3: str = "") -> dict:
    """Two primer pairs for a two-fragment HiFi assembly.

    The vector is linearised by PCR so that its ends are
    `vector_open_before` .. `vector_open_after` (1-based; the bases between
    them, going forward, are the ones removed). The insert is amplified from
    `insert_start..insert_end` of `insert_template` and carries 20 nt of
    vector homology on each 5' tail.

    `extra_5` / `extra_3` are sequences spliced in at the two junctions — a
    linker, a 2A peptide, a Kozak — and they become part of the homology, so
    they are added to the insert primer tails rather than to the vector's.

    Returns {"vector": PrimerPair, "insert": PrimerPair, "product": Dseq}.
    """
    vseq = vector.sequence
    vn = len(vseq)
    iseq = insert_template.sequence
    inn = len(iseq)

    insert_body = insert_template.subsequence(insert_start, insert_end)
    if insert_strand == -1:
        insert_body = rc(insert_body)
    insert_full = extra_5.upper() + insert_body.upper() + extra_3.upper()

    # Vector primers: amplify outward from the opening.
    v_f_anchor = vector_open_after % vn          # first base kept, going forward
    v_r_anchor = (vector_open_before - 2) % vn   # last base kept, going backward
    vf, vr = pick_pair(vseq, v_f_anchor, vseq, v_r_anchor,
                       vector.circular, vector.circular, target_tm)

    # Insert primers: anneal to the insert, tails carry vector homology.
    if insert_strand == 1:
        i_f_anchor = insert_start - 1
        i_r_anchor = insert_end - 1
    else:
        i_f_anchor = insert_end - 1
        i_r_anchor = insert_start - 1
    i_f, i_r = pick_pair(iseq, i_f_anchor, iseq, i_r_anchor,
                         insert_template.circular, insert_template.circular, target_tm,
                         fwd_dir=insert_strand, rev_dir=-insert_strand)

    # Left junction: last `homology` bases of the upstream vector arm, which is
    # the sequence ending at vector_open_before - 1.
    left_context = "".join(vseq[(v_r_anchor - homology + 1 + k) % vn]
                           for k in range(homology))
    right_context = "".join(vseq[(v_f_anchor + k) % vn] for k in range(homology))

    i_f_tail = (left_context + extra_5.upper())[-homology:] if extra_5 else left_context
    if extra_5:
        i_f_tail = left_context + extra_5.upper()
    i_r_tail = rc(right_context)
    if extra_3:
        i_r_tail = rc(extra_3.upper() + right_context)

    vec_pair = PrimerPair(
        DesignedPrimer(name + "_vec_F", "", vf, vector.name, vn, "vector forward",
                       warnings=_anneal_warnings(vf)),
        DesignedPrimer(name + "_vec_R", "", vr, vector.name, vn, "vector reverse",
                       warnings=_anneal_warnings(vr)),
        product_len=(v_r_anchor - v_f_anchor) % vn + 1,
        template_name=vector.name, template_len=vn,
        description="Gibson: linearise %s" % (vector.name or "vector"))

    ins_pair = PrimerPair(
        DesignedPrimer(name + "_ins_F", i_f_tail, i_f, insert_template.name, inn,
                       "insert forward", warnings=_anneal_warnings(i_f)),
        DesignedPrimer(name + "_ins_R", i_r_tail, i_r, insert_template.name, inn,
                       "insert reverse", warnings=_anneal_warnings(i_r)),
        product_len=len(insert_full) + len(i_f_tail) + len(i_r_tail),
        template_name=insert_template.name, template_len=inn,
        description="Gibson: amplify insert from %s" % (insert_template.name or "template"))

    backbone = "".join(vseq[(v_f_anchor + k) % vn] for k in range(vec_pair.product_len))
    product = Dseq(backbone + insert_full, True,
                   "%s_%s" % (vector.name or "vec", insert_template.name or "ins"))
    product.features = _gibson_features(
        vector, v_f_anchor, len(backbone), insert_template, insert_start, insert_end,
        insert_strand, len(backbone) + len(extra_5), extra_5, extra_3)
    return {"vector": vec_pair, "insert": ins_pair, "product": product,
            "insert_full": insert_full}


def _gibson_features(vector, v_start: int, backbone_len: int, insert_template,
                     insert_start: int, insert_end: int, insert_strand: int,
                     insert_offset: int, extra_5: str, extra_3: str) -> list:
    """Carry annotation from both parents onto the assembled product.

    The product is backbone + extra_5 + insert body + extra_3. A vector feature
    survives if it lies wholly inside the retained backbone; an insert feature
    survives if it lies wholly inside the amplified region. Anything spanning a
    junction is dropped rather than truncated, because a half-feature on a map
    is worse than no feature — it reads as if the whole element were present.
    """
    out = []
    n = len(vector)

    for f in vector.features:
        ns = (f.start - 1 - v_start) % n
        ne = (f.end - 1 - v_start) % n
        if ns <= ne < backbone_len:
            out.append(Feature(f.name, ns + 1, ne + 1, f.strand, f.type, f.color,
                               dict(f.notes)))

    body_len = (insert_end - insert_start + 1) if insert_end >= insert_start else 0
    for f in insert_template.features:
        if not (insert_start <= f.start and f.end <= insert_end):
            continue
        if insert_strand == 1:
            ns = insert_offset + (f.start - insert_start)
            ne = insert_offset + (f.end - insert_start)
            strand = f.strand
        else:
            ns = insert_offset + (insert_end - f.end)
            ne = insert_offset + (insert_end - f.start)
            strand = -f.strand
        out.append(Feature(f.name, ns + 1, ne + 1, strand, f.type, f.color,
                           dict(f.notes)))

    for seq, start in ((extra_5, backbone_len),
                       (extra_3, insert_offset + body_len)):
        if seq:
            out.append(Feature("junction insert", start + 1, start + len(seq), 1,
                               "misc_feature", "#ffef86"))
    out.sort(key=lambda f: (f.start, f.end))
    return out


# -- restriction enzyme ---------------------------------------------------

ENZYMES = {
    # name: (recognition site, 5' pad recommended by NEB's cleavage-near-end table)
    "EcoRI": ("GAATTC", "aaa"), "BamHI": ("GGATCC", "aaa"), "XhoI": ("CTCGAG", "aaa"),
    "NotI": ("GCGGCCGC", "aaaa"), "XbaI": ("TCTAGA", "aaa"), "HindIII": ("AAGCTT", "aaa"),
    "NheI": ("GCTAGC", "aaa"), "SalI": ("GTCGAC", "aaa"), "NcoI": ("CCATGG", "aaa"),
    "NdeI": ("CATATG", "aaaaa"), "KpnI": ("GGTACC", "aaa"), "SacI": ("GAGCTC", "aaa"),
    "AgeI": ("ACCGGT", "aaa"), "MluI": ("ACGCGT", "aaa"), "SpeI": ("ACTAGT", "aaa"),
    "PstI": ("CTGCAG", "aaaaa"), "EcoRV": ("GATATC", "aaaaa"), "AscI": ("GGCGCGCC", "aaa"),
    "BsaI": ("GGTCTC", "atatat"), "BsmBI": ("CGTCTC", "atatat"), "Esp3I": ("CGTCTC", "atatat"),
}


def design_re(template: Dseq, start: int, end: int, five_enzyme: str, three_enzyme: str,
              name: str = "RE", target_tm: float = DEFAULT_TM,
              spacer_5: str = "", spacer_3: str = "") -> PrimerPair:
    """Amplify `start..end` adding a restriction site to each end.

    Each primer gets: an A-rich pad (so the enzyme can bind near the end of the
    fragment), the recognition site, an optional in-frame spacer, then the
    annealing region.
    """
    for enz in (five_enzyme, three_enzyme):
        if enz not in ENZYMES:
            raise ValueError("unknown enzyme %r; known: %s"
                             % (enz, ", ".join(sorted(ENZYMES))))
    site5, pad5 = ENZYMES[five_enzyme]
    site3, pad3 = ENZYMES[three_enzyme]

    seq = template.sequence
    f_anneal, r_anneal = pick_pair(seq, start - 1, seq, end - 1,
                                   template.circular, template.circular, target_tm)

    f_tail = pad5 + site5.lower() + spacer_5.lower()
    r_tail = pad3 + rc(site3).lower() + rc(spacer_3).lower() if spacer_3 else pad3 + rc(site3).lower()

    body = template.subsequence(start, end)
    warn_f = _anneal_warnings(f_anneal)
    warn_r = _anneal_warnings(r_anneal)
    for enz, site in ((five_enzyme, site5), (three_enzyme, site3)):
        count = body.upper().count(site) + body.upper().count(rc(site))
        if count:
            warn_f.append("%s site occurs %d time(s) inside the amplified region — "
                          "digestion will cut the insert" % (enz, count))

    f = DesignedPrimer(name + "_F", f_tail, f_anneal, template.name, len(seq),
                       "RE forward (%s)" % five_enzyme, warnings=warn_f)
    r = DesignedPrimer(name + "_R", r_tail, r_anneal, template.name, len(seq),
                       "RE reverse (%s)" % three_enzyme, warnings=warn_r)
    return PrimerPair(f, r, len(f_tail) + len(body) + len(r_tail), template.name, len(seq),
                      "RE cloning: %s..%s flanked by %s / %s"
                      % (start, end, five_enzyme, three_enzyme))


def find_sites(seq: str, enzyme: str, circular: bool = True) -> list:
    """1-based positions of an enzyme's recognition site on both strands."""
    site = ENZYMES[enzyme][0].upper()
    s = seq.upper()
    scan = s + s[:len(site) - 1] if circular else s
    hits = []
    for i in range(len(scan) - len(site) + 1):
        if scan[i:i + len(site)] == site:
            hits.append((i % len(s) + 1, "+"))
        elif scan[i:i + len(site)] == rc(site):
            hits.append((i % len(s) + 1, "-"))
    return hits
