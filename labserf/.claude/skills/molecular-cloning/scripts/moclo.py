"""Golden Gate / MoClo assembly for the Mammalian Tool Kit (MTK).

Two levels, and the enzyme tells you which one you are on:

    MTK parts  --BsaI-->  TU  (a transcription unit, in the pMTK678 acceptor)
    TUs        --BsmBI--> final plasmid (in an MTK0 backbone)

Both enzymes are Type IIS cutting one base past their recognition site and
leaving a 4-nt 5' overhang, so a cut is fully described by the position of the
top-strand nick; the overhang is always the four bases starting there.

A digested plasmid yields exactly one fragment with no recognition site left in
it. That is the piece that ends up in the product — for a part plasmid it is
the part, for an acceptor it is the backbone — which is why the same rule finds
both and why the product can never be re-cut.

Fusion sites are fixed by the MTK grammar, not chosen per assembly; see
references/moclo-mtk.md for the tables this module enforces.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from snapgene import Dseq, Feature, rc

ENZYME_SPEC = {
    # name: (site, spacer between site and top-strand cut, overhang length)
    "BsaI": ("GGTCTC", 1, 4),
    "BsmBI": ("CGTCTC", 1, 4),
    "Esp3I": ("CGTCTC", 1, 4),
}

# MTK part-type fusion sites: (upstream overhang, downstream overhang).
MTK_PART_OVERHANGS = {
    "0": ("CTGA", "AGCA"),     # backbone
    "1": ("CCCT", "AACG"),     # 5' connector
    "2": ("AACG", "TATG"),     # promoter
    "3": ("TATG", "ATCC"),     # CDS
    "4": ("ATCC", "GCTG"),     # 3' UTR
    "5": ("GCTG", "TACA"),     # 3' connector
    "12": ("CCCT", "TATG"),    # fused connector+promoter (e.g. ConL1-IRES2)
    "678": ("CCCT", "TACA"),   # acceptor: the span a whole TU occupies
}

# TU-level connector overhangs, read off the lab's own TUs.
MTK_CONNECTORS = {
    "ConLS": "CTGA", "ConL1": "CCAA", "ConL2": "GATG", "ConL3": "GTTC",
    "ConR1": "CCAA", "ConR2": "GATG", "ConR3": "GTTC", "ConRE": "AGCA",
}
# A TU named "TU<n>" spans connector n-1 to connector n; position 1 starts at
# ConLS (CTGA) and the last TU in a plasmid ends at ConRE (AGCA), which is
# where the MTK0 backbone picks it up again.
TU_SLOTS = [("ConLS", "ConR1"), ("ConL1", "ConR2"), ("ConL2", "ConR3"),
            ("ConL3", "ConRE")]


@dataclass
class Fragment:
    """A double-stranded piece with a 4-nt 5' overhang at each end.

    `top` is the top strand from the left nick up to (not including) the right
    overhang, so `left_overhang` is its first four bases and concatenating the
    tops of a closed cycle reconstructs the circular product exactly once.
    """
    top: str
    left_overhang: str
    right_overhang: str
    source: str = ""
    features: list = None

    def __post_init__(self):
        if self.features is None:
            self.features = []
        # Overhangs are compared across files whose sequences differ in case.
        self.left_overhang = self.left_overhang.upper()
        self.right_overhang = self.right_overhang.upper()

    def __len__(self):
        return len(self.top)

    def __repr__(self):
        return "<Fragment %s %dbp %s..%s>" % (self.source, len(self.top),
                                              self.left_overhang, self.right_overhang)

    def reverse_complement(self) -> "Fragment":
        """The same physical fragment, flipped.

        A fragment with a 5' overhang at each end ligates in whichever
        orientation its overhangs fit, so a part stored reverse-complemented in
        SnapGene still assembles — several in this collection are (TU4-4, for
        one, which SnapGene's own history records being used with a `flip`).

        Top strand runs p..q, bottom strand is complementary to p+4..q+4, so
        flipping makes the old bottom strand the new top: rc(top[4:] + right).
        """
        ovh = len(self.left_overhang)
        new_top = rc(self.top[ovh:] + self.right_overhang)
        out = Fragment(new_top, rc(self.right_overhang), rc(self.left_overhang),
                       self.source)
        n = len(new_top)
        for ft in self.features:
            # base at old index i lands at new index (n + ovh - 1) - i
            ns = (n + ovh - 1) - (ft.end - 1)
            ne = (n + ovh - 1) - (ft.start - 1)
            ns, ne = max(ns, 0), min(ne, n - 1)
            if ns <= ne:
                out.features.append(Feature(ft.name, ns + 1, ne + 1, -ft.strand,
                                            ft.type, ft.color, dict(ft.notes)))
        return out


def cut_positions(seq: str, enzyme: str, circular: bool = True) -> list:
    """Top-strand nick positions (0-based) for one enzyme."""
    site, spacer, ovh = ENZYME_SPEC[enzyme]
    n = len(seq)
    s = seq.upper()
    scan = s + s[:len(site) + spacer + ovh] if circular else s
    cuts = []
    for m in re.finditer("(?=%s)" % site, scan):
        p = m.start() + len(site) + spacer
        if circular or p + ovh <= n:
            cuts.append(p % n if circular else p)
    for m in re.finditer("(?=%s)" % rc(site), scan):
        p = m.start() - spacer - ovh
        if p < 0 and not circular:
            continue
        cuts.append(p % n if circular else p)
    return sorted(set(cuts))


def digest(plasmid: Dseq, enzyme: str) -> list:
    """All fragments from a complete digest."""
    site, spacer, ovh = ENZYME_SPEC[enzyme]
    seq = plasmid.sequence
    n = len(seq)
    cuts = cut_positions(seq, enzyme, plasmid.circular)
    if not cuts:
        return []

    def span(a, b):
        return "".join(seq[(a + k) % n] for k in range((b - a) % n or n))

    frags = []
    if plasmid.circular:
        for i, p in enumerate(cuts):
            q = cuts[(i + 1) % len(cuts)]
            top = span(p, q)
            frags.append(Fragment(top, top[:ovh],
                                  "".join(seq[(q + k) % n] for k in range(ovh)),
                                  plasmid.name))
    else:
        bounds = [0] + cuts + [n]
        for a, b in zip(bounds, bounds[1:]):
            top = seq[a:b]
            frags.append(Fragment(top, top[:ovh], seq[b:b + ovh], plasmid.name))
    return frags


def released_fragment(plasmid: Dseq, enzyme: str) -> Fragment:
    """The one fragment with no recognition site left in it.

    For a part plasmid that is the part; for an acceptor it is the backbone.
    Raises if the digest is not a clean two-site digest.
    """
    site = ENZYME_SPEC[enzyme][0]
    frags = digest(plasmid, enzyme)
    if not frags:
        raise ValueError("%s has no %s site" % (plasmid.name or "plasmid", enzyme))
    clean = []
    for f in frags:
        body = (f.top + f.right_overhang).upper()
        if site not in body and rc(site) not in body:
            clean.append(f)
    if len(clean) != 1:
        raise ValueError("%s: expected exactly one %s-free fragment, got %d "
                         "(%d cut sites) — check the part for internal sites"
                         % (plasmid.name or "plasmid", enzyme, len(clean), len(frags)))
    frag = clean[0]
    frag.features = _features_for_fragment(plasmid, frag, enzyme)
    return frag


def _features_for_fragment(plasmid: Dseq, frag: Fragment, enzyme: str) -> list:
    """Features of `plasmid` that fall inside `frag`, re-based to the fragment."""
    seq = plasmid.sequence
    n = len(seq)
    start = seq.find(frag.top) if len(frag.top) < n else 0
    if start < 0:
        doubled = seq + seq
        start = doubled.find(frag.top)
        if start < 0:
            return []
        start %= n
    out = []
    for f in plasmid.features:
        fs = (f.start - 1 - start) % n
        fe = (f.end - 1 - start) % n
        if fs <= fe and fe < len(frag.top):
            out.append(Feature(f.name, fs + 1, fe + 1, f.strand, f.type, f.color,
                               dict(f.notes)))
    return out


def assemble(fragments: list, name: str = "assembly") -> Dseq:
    """Circularise fragments by matching 5' overhangs.

    Greedy chaining: every overhang in a valid MoClo reaction is unique, so
    there is exactly one cycle. Anything else is a design error and is reported
    as one rather than silently producing a plausible-looking plasmid.
    """
    if not fragments:
        raise ValueError("nothing to assemble")

    # Each fragment may go in either way round; index both orientations and let
    # the overhangs decide. In a valid reaction only one of the two fits.
    by_left = {}
    for f in fragments:
        for cand in (f, f.reverse_complement()):
            prev = by_left.get(cand.left_overhang)
            if prev is not None and prev.source != cand.source:
                raise ValueError(
                    "two fragments start with the same overhang %s (%s and %s); "
                    "the assembly is ambiguous"
                    % (cand.left_overhang, prev.source, cand.source))
            by_left.setdefault(cand.left_overhang, cand)

    first = fragments[0]
    chain = [first]
    seen = {first.left_overhang}
    cur = first
    used = {first.source}
    while True:
        nxt = by_left.get(cur.right_overhang)
        if nxt is None:
            raise ValueError(
                "overhang %s from %s has no partner; fragments present start with %s"
                % (cur.right_overhang, cur.source, sorted(by_left)))
        if nxt.left_overhang == chain[0].left_overhang:
            break
        if nxt.left_overhang in seen or nxt.source in used:
            raise ValueError("fragments form more than one cycle")
        chain.append(nxt)
        seen.add(nxt.left_overhang)
        used.add(nxt.source)
        cur = nxt
        if len(chain) > len(fragments):
            raise ValueError("assembly did not close")
    if len(chain) != len(fragments):
        missing = [f.source for f in fragments if f.source not in used]
        raise ValueError("only %d of %d fragments formed a circle; left out: %s"
                         % (len(chain), len(fragments), ", ".join(missing)))

    seq = "".join(f.top for f in chain)
    out = Dseq(seq, True, name)
    offset = 0
    for f in chain:
        for ft in f.features:
            out.features.append(Feature(ft.name, ft.start + offset, ft.end + offset,
                                        ft.strand, ft.type, ft.color, dict(ft.notes)))
        offset += len(f.top)
    return out


def golden_gate(plasmids: list, enzyme: str, name: str = "assembly",
                keep_history: bool = True) -> Dseq:
    """Digest every plasmid, keep the site-free fragment, circularise.

    With `keep_history`, the product carries a SnapGene History tree recording
    every input *and each input's own ancestry* — so a finished plasmid shows
    the TUs it came from, the MTK parts those TUs came from, and so on, exactly
    as the lab's own files do.
    """
    frags = []
    for p in plasmids:
        f = released_fragment(p, enzyme)
        f.source = p.name or f.source
        frags.append(f)
    product = assemble(frags, name)
    if keep_history:
        product.history_xml = build_history(product, plasmids, enzyme)
    return product


def build_history(product: Dseq, inputs: list, enzyme: str | None = None,
                  operation: str = "insertFragments") -> str:
    """A SnapGene History tree for a Golden Gate product.

    Each input contributes its own recorded history subtree when it has one, so
    provenance is preserved all the way down rather than flattened to a list of
    immediate parents. IDs are renumbered across the whole tree because the
    inputs' trees were numbered independently and would otherwise collide.
    """
    import xml.etree.ElementTree as ET

    root = ET.Element("Node", {
        "name": (product.name or "assembly") + ".dna",
        "type": "DNA",
        "seqLen": str(len(product)),
        "ID": "1",
        "circular": "1" if product.circular else "0",
        "operation": operation,
    })
    # SnapGene shows the enzyme used for the join here.
    if enzyme:
        ET.SubElement(root, "InputSummary", {
            "manipulation": "replace", "name1": enzyme, "name2": enzyme,
            "siteCount1": "2", "siteCount2": "2",
        })

    for src in inputs:
        child = None
        if getattr(src, "history_xml", ""):
            try:
                child = ET.fromstring(src.history_xml).find("Node")
            except ET.ParseError:
                child = None
        if child is None:
            child = ET.Element("Node", {
                "name": (src.name or "input") + ".dna",
                "type": "DNA",
                "seqLen": str(len(src)),
                "ID": "0",
                "circular": "1" if src.circular else "0",
                "operation": "invalid",
            })
        root.append(child)

    counter = [1]

    def renumber(node):
        counter[0] += 1
        node.set("ID", str(counter[0]))
        for kid in node.findall("Node"):
            renumber(kid)

    for kid in root.findall("Node"):
        renumber(kid)

    tree = ET.Element("HistoryTree")
    tree.append(root)
    return '<?xml version="1.0"?>' + ET.tostring(tree, encoding="unicode")


def build_tu(parts: list, acceptor: Dseq, name: str = "TU") -> Dseq:
    """Assemble MTK parts into a transcription unit (BsaI)."""
    return golden_gate(list(parts) + [acceptor], "BsaI", name)


def build_plasmid(tus: list, backbone: Dseq, name: str = "construct") -> Dseq:
    """Assemble TUs into a final plasmid in an MTK0 backbone (BsmBI)."""
    return golden_gate(list(tus) + [backbone], "BsmBI", name)


# -- inspection -----------------------------------------------------------


def part_overhangs(plasmid: Dseq, enzyme: str) -> tuple:
    f = released_fragment(plasmid, enzyme)
    return f.left_overhang, f.right_overhang


def classify_part(plasmid: Dseq) -> dict:
    """What MTK slot does this plasmid occupy?"""
    info = {"name": plasmid.name, "length": len(plasmid)}
    for enzyme in ("BsaI", "BsmBI"):
        try:
            lo, ro = part_overhangs(plasmid, enzyme)
        except ValueError:
            continue
        info[enzyme] = (lo, ro)
        if enzyme == "BsaI":
            for t, (a, b) in MTK_PART_OVERHANGS.items():
                if (a, b) == (lo, ro):
                    info["part_type"] = t
        else:
            left = [k for k, v in MTK_CONNECTORS.items() if v == lo and k.startswith("ConL")]
            right = [k for k, v in MTK_CONNECTORS.items() if v == ro and k.startswith("ConR")]
            if lo == "CTGA":
                left = ["ConLS"]
            if left and right:
                info["tu_slot"] = (left[0], right[0])
                for i, (a, b) in enumerate(TU_SLOTS, start=1):
                    if (a, b) == (left[0], right[0]):
                        info["tu_position"] = i
            elif ro == "CTGA" or lo == "AGCA":
                info["role"] = "MTK0 backbone"
    return info


def load(path: str) -> Dseq:
    d = Dseq.read(path)
    if not d.name:
        d.name = os.path.splitext(os.path.basename(path))[0]
    return d
