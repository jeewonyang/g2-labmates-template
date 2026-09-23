#!/usr/bin/env python3
"""Self-test: rebuild plasmids the lab actually made and compare base for base.

    python validate.py            # everything
    python validate.py --quick    # skip the broad part sweep

The assembly cases below were read out of the SnapGene History tree embedded in
each assembled plasmid, so they are what was really built, not a guess. A pass
means the Golden Gate engine reproduces the recorded product exactly, allowing
for a rotation of the origin.

Run this after touching moclo.py or snapgene.py.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design
import thermo
from moclo import build_plasmid, build_tu, classify_part, load
from snapgene import Dseq

ROOT = None


def repo_root() -> str:
    global ROOT
    if ROOT:
        return ROOT
    d = os.path.dirname(os.path.abspath(__file__))
    while d != "/":
        if os.path.isdir(os.path.join(d, "Sequences")):
            ROOT = d
            return d
        d = os.path.dirname(d)
    raise SystemExit("repo root not found")


def P(rel: str) -> str:
    return os.path.join(repo_root(), "Sequences", "MammalianToolKit", rel)


def rotation_match(a: str, b: str) -> bool:
    a, b = a.upper(), b.upper()
    return len(a) == len(b) and a in (b + b)


PARTS = "MTK_Parts/"

TU_CASES = [
    # (reference TU, [parts], acceptor)
    ("TUs/TU1-5_LS_R1_TRE-GvpA.dna",
     [PARTS + "Type 1_5' Connectors_ccct-aacg/A1_pMTK1_ConLS.dna",
      PARTS + "Type 2_Promoters_aacg-tatg/C5_pMTK2_TRE.dna",
      PARTS + "Type 3_CDSs_tatg-atcc/mG-4_pMTK3-GvpA(withstopcodon).dna",
      PARTS + "Type 4_3' UTR_atcc-gctg/E6_pMTK4_spacer-poly.dna",
      PARTS + "Type 5_3' Connectors_gctg-taca/F1_pMTK5_ConR1.dna"],
     PARTS + "Type 678_acceptor_ccct-taca/G12_pMTK678_mScarlet.dna"),
    ("TUs/TU1-1_LS_R1_EF1a-rtTA.dna",
     [PARTS + "Type 1_5' Connectors_ccct-aacg/A1_pMTK1_ConLS.dna",
      PARTS + "Type 2_Promoters_aacg-tatg/B3_pMTK2_EF1a.dna",
      PARTS + "Type 3_CDSs_tatg-atcc/D11_pMTK3_rtTA.dna",
      PARTS + "Type 4_3' UTR_atcc-gctg/E6_pMTK4_spacer-poly.dna",
      PARTS + "Type 5_3' Connectors_gctg-taca/F1_pMTK5_ConR1.dna"],
     PARTS + "Type 678_acceptor_ccct-taca/G12_pMTK678_mScarlet.dna"),
    ("TUs/TU2-7_L1_R2_IRES_emiRFP.dna",
     [PARTS + "Type 1_5' Connectors_ccct-aacg/A5_pMTK12_ConL1_IRES2.dna",
      PARTS + "Type 3_CDSs_tatg-atcc/mG-26_pMTK3-emiRFP670.dna",
      PARTS + "Type 4_3' UTR_atcc-gctg/E1_pMTK4_spacer-mono.dna",
      PARTS + "Type 5_3' Connectors_gctg-taca/F2_pYTK068_pMTK5_ConR2.dna"],
     PARTS + "Type 678_acceptor_ccct-taca/G12_pMTK678_mScarlet.dna"),
]

PLASMID_CASES = [
    # (reference assembly, [TUs], MTK0 backbone)
    ("Assemblies/mT-21_pPB-TRE-A-IRES-emiRFP-WPRE.dna",
     ["TUs/TU1-5_LS_R1_TRE-GvpA.dna",
      "TUs/TU2-9_L1_R2_IRES_emiRFP_WPRE.dna",
      "TUs/TU3-9_L2_RE_EmptyConnector.dna"],
     PARTS + "Type 0_BB_ctga-agca/mG-31_MTK0_piggyBac_noHygoR.dna"),
    ("Assemblies/mT-52_pPB-TRE-A-IRES-381RK-WPRE-mEF1a-HygR.dna",
     ["TUs/TU1-5_LS_R1_TRE-GvpA.dna",
      "TUs/TU2-5_L1_R2_IRES-381RK-WPRE.dna",
      "TUs/TU3-10_L2_R3_EmptyConnector.dna",
      "TUs/TU4-6_L3_RE_mEF1a_HygR.dna"],
     PARTS + "Type 0_BB_ctga-agca/mG-31_MTK0_piggyBac_noHygoR.dna"),
    ("Assemblies/mT-61_pPB-TRE-A-WPRE-bGH.dna",
     ["TUs/TU1-27_LS_R1_TRE-GvpA-WPRE.dna",
      "TUs/TU2-20_L1_RE_EmptyConnector.dna"],
     PARTS + "Type 0_BB_ctga-agca/mG-31_MTK0_piggyBac_noHygoR.dna"),
    ("Assemblies/mT-69_pPB-TRE-A-WPRE-mEF1a-rtTA-T2A-HygR.dna",
     ["TUs/TU1-27_LS_R1_TRE-GvpA-WPRE.dna",
      "TUs/TU2-19_L1_R2_EmptyConnector.dna",
      "TUs/TU3-16_L2_R3_mEF1a_rtTA.dna",
      "TUs/TU4-7_L3_RE_T2A-HygR.dna"],
     PARTS + "Type 0_BB_ctga-agca/mG-31_MTK0_piggyBac_noHygoR.dna"),
]

# Tm spot checks: (forward anneal, reverse anneal, Ta recorded in Primer_All)
TM_CASES = [
    ("AGCCTCGAGCATCACCA", "ATGTATATCTCCTTCTTAAAGTTAAACAAAATTATTTCTAG", 64),
    ("AAGCTTGCGGCCGCACTC", "CAGGGGCCCCTGGAACAG", 72),
    ("CGTCAGGATCTGTTTGTGT", "GAACGCGAGCAATTCTTG", 63),
    ("AGCCTCGAGCATCACC", "GCCAAAAATAGACACAAACAGATCC", 65),
    ("TCCGAGACTGCGCAAG", "CAAATCTTTGTAGAATGCCTG", 60),
    ("TACAAGCTCATCCTGAACG", "AGCTTCGGTGACGGTG", 62),
    ("ATGGCCGTGGAAAAG", "GGGGAAGGGTACTGGATCCG", 60),
    ("AGCCTCGAGCATCAC", "GAACGCGAGCAATTC", 59),
    ("GCGCAAGCCCGTA", "CGTTTCCTGCAAATCTTTGT", 62),
    ("ATCTCATTAATGGCTAAAATTCGCC", "GCTGCTGCCCATGGT", 64),
]


def check(label, ok, detail=""):
    print("  %s %s%s" % ("PASS" if ok else "FAIL", label, ("  " + detail) if detail else ""))
    return bool(ok)


def run_tu_cases():
    print("TU assembly (BsaI, MTK parts -> transcription unit)")
    ok = True
    for ref_rel, parts, acceptor in TU_CASES:
        ref = load(P(ref_rel))
        try:
            built = build_tu([load(P(p)) for p in parts], load(P(acceptor)), "built")
            good = rotation_match(built.sequence, ref.sequence)
            ok &= check(os.path.basename(ref_rel), good,
                        "%d bp vs %d bp" % (len(built), len(ref)))
        except Exception as exc:                          # noqa: BLE001
            ok &= check(os.path.basename(ref_rel), False, str(exc))
    return ok


def run_plasmid_cases():
    print("Plasmid assembly (BsmBI, TUs -> final construct)")
    ok = True
    for ref_rel, tus, bb in PLASMID_CASES:
        ref = load(P(ref_rel))
        try:
            built = build_plasmid([load(P(t)) for t in tus], load(P(bb)), "built")
            good = rotation_match(built.sequence, ref.sequence)
            ok &= check(os.path.basename(ref_rel), good,
                        "%d bp vs %d bp" % (len(built), len(ref)))
        except Exception as exc:                          # noqa: BLE001
            ok &= check(os.path.basename(ref_rel), False, str(exc))
    return ok


def run_tm_cases(tolerance=3.0):
    print("Tm model vs Ta values recorded in Primer_All (tolerance +/-%.0f C)" % tolerance)
    ok = True
    errs = []
    for f, r, recorded in TM_CASES:
        ta = thermo.annealing_temperature(thermo.tm(f), thermo.tm(r))
        errs.append(ta - recorded)
        ok &= check("%s / %s" % (f[:14], r[:14]), abs(ta - recorded) <= tolerance,
                    "computed %.0f, recorded %d" % (ta, recorded))
    print("  mean error %+.2f C over %d pairs" % (sum(errs) / len(errs), len(errs)))
    return ok


def run_roundtrip():
    print("SnapGene .dna round trip")
    src = P("TUs/TU1-1_LS_R1_EF1a-rtTA.dna")
    d = load(src)
    tmp = os.path.join(tempfile.gettempdir(), "_validate_roundtrip.dna")
    d.write(tmp)
    e = Dseq.read(tmp)
    raw = open(tmp, "rb").read()
    from snapgene import HEADER
    ok = check("header segment is the full 14-byte cookie",
               raw[:5] == b"\x09\x00\x00\x00\x0e" and raw[5:19] == HEADER,
               "SnapGene rejects a file whose segment 9 is truncated")
    ok &= check("sequence preserved", e.sequence == d.sequence)
    ok &= check("topology preserved", e.circular == d.circular)
    ok &= check("features preserved", len(e.features) == len(d.features),
                "%d vs %d" % (len(e.features), len(d.features)))
    ok &= check("feature coordinates preserved",
                all((a.name, a.start, a.end, a.strand) == (b.name, b.start, b.end, b.strand)
                    for a, b in zip(d.features, e.features)))
    ok &= check("primers preserved", len(e.primers) == len(d.primers),
                "%d vs %d" % (len(e.primers), len(d.primers)))
    ok &= check("history tree preserved", e.history_xml == d.history_xml)
    os.remove(tmp)
    return ok


def run_binding_sites():
    """Primers must carry binding sites, or SnapGene will not draw them."""
    import re as _re
    import struct as _struct
    from snapgene import find_binding_site
    print("Primer binding sites")
    src = P("TUs/TU1-1_LS_R1_EF1a-rtTA.dna")
    raw = open(src, "rb").read()
    stored, i = "", 0
    while i < len(raw):
        t = raw[i]
        ln = _struct.unpack(">I", raw[i + 1:i + 5])[0]
        if t == 5:
            stored = raw[i + 5:i + 5 + ln].decode("utf8", "replace")
        i += 5 + ln
    d = load(src)
    agree = total = 0
    for m in _re.finditer(r'<Primer [^>]*sequence="([^"]*)"(.*?)</Primer>', stored, _re.S):
        seqp, body = m.group(1), m.group(2)
        want = set(_re.findall(r'<BindingSite[^>]*location="(\d+)-(\d+)"', body))
        if not want:
            continue
        total += 1
        got = find_binding_site(seqp, d.sequence, d.circular)
        if got and (str(got[0]), str(got[1])) in want:
            agree += 1
    ok = check("computed sites match SnapGene's own", agree == total,
               "%d/%d primers" % (agree, total))
    # A written file must actually contain them.
    tmp = os.path.join(tempfile.gettempdir(), "_validate_primers.dna")
    d.write(tmp)
    written = open(tmp, "rb").read()
    ok &= check("written file contains BindingSite elements",
                b"BindingSite" in written)
    os.remove(tmp)
    return ok


def run_structure_checks():
    """The dimer and hairpin warnings must fire on a pathological pair."""
    from design import DesignedPrimer, PrimerPair
    print("Secondary-structure warnings")
    tail = "ggccgcggcgcgccgcggcc"
    f = DesignedPrimer("bad_F", tail, "ATGGCCGTGGAAAAGAC", "t", 100, "fwd")
    r = DesignedPrimer("bad_R", tail, "AGCAGGCACAGCAGCAC", "t", 100, "rev")
    w = " ".join(PrimerPair(f, r, 500, "t", 100, "test").warnings())
    ok = check("tail-induced hairpin caught", "hairpin" in w)
    ok &= check("full-length self-dimer caught", "self-dimer over the full oligo" in w)
    ok &= check("full-length hetero-dimer caught", "full length" in w)
    clean = design.design_kld(load(P("TUs/TU1-5_LS_R1_TRE-GvpA.dna")), 1343, 1555)
    quiet = [x for x in clean.warnings() if "dimer" in x or "hairpin" in x]
    ok &= check("a clean pair raises no structure warnings", not quiet,
                "; ".join(quiet))
    return ok


def run_naming():
    """ID allocation must skip outliers and never collide."""
    import naming
    print("Naming and ID allocation")
    used = naming.scan_ids()
    ok = True
    for series in ("mL", "mT", "TU1", "TU2", "TU3", "TU4"):
        if series not in used:
            continue
        nid, _out = naming.next_id(series, used=used)
        ok &= check("%s next ID %d is free" % (series, nid), nid not in used[series])
    # TU2-772 is a construct number, not a serial; it must not drag the series up.
    if "TU2" in used and 772 in used["TU2"]:
        nid, outliers = naming.next_id("TU2", used=used)
        ok &= check("TU2 outlier ignored", nid < 100 and 772 in outliers,
                    "next=%d, outliers=%s" % (nid, outliers))
    ok &= check("mT and mPB share one piggyBac run of numbers",
                naming.next_id("mPB", used=used)[0] == naming.next_id("mT", used=used)[0])
    ok &= check("mL numbers independently of the piggyBac run",
                naming.next_id("mL", used=used)[0] != naming.next_id("mT", used=used)[0])
    ok &= check("backbone kinds classify correctly", _kinds_ok())
    ok &= check("part labels strip the MTK prefix",
                naming.part_label("C5_pMTK2_TRE") == "TRE"
                and naming.part_label("mG-26_pMTK3-emiRFP670") == "emiRFP670"
                and naming.part_label("TU1-12_LS_R1_TRE-NV-WPRE") == "TRE-NV-WPRE")
    ok &= check("filenames follow the convention",
                naming.tu_filename(1, 50, "ConLS", "ConR1", "TRE-X")
                == "TU1-50_LS_R1_TRE-X"
                and naming.plasmid_filename("mPB", 116, "pPB-TRE-X")
                == "mPB-116_pPB-TRE-X")
    return ok


def _kinds_ok():
    import naming
    base = os.path.join(repo_root(), "Sequences", "MammalianToolKit", "MTK_Parts",
                        "Type 0_BB_ctga-agca")
    expect = {"mG-29_MTK0_Lenti_CMV": "mL", "H4_pMTK0_Lenti": "mL",
              "mG-31_MTK0_piggyBac_noHygoR": "mPB", "H1_pMTK0_piggyBac": "mPB",
              "mG-36_MTK0_transient_bGH": "mT", "H5_MTK0_051_hAAVS1": None}
    for stem, want in expect.items():
        path = os.path.join(base, stem + ".dna")
        if not os.path.exists(path):
            continue
        if naming.backbone_kind(load(path)) != want:
            return False
    return True


def run_gibson():
    """A Gibson design must give two pairs whose amplicons really overlap.

    Built from the primer sequences alone: simulate both PCRs, find the
    overlaps, join, and compare with the product the designer reported. This
    checks the design end to end rather than re-reading the code's own maths.
    """
    from snapgene import rc
    print("Gibson: simulated PCRs must assemble into the reported product")
    vec = load(P("TUs/TU1-5_LS_R1_TRE-GvpA.dna"))
    ins = load(P("MTK_Parts/Type 3_CDSs_tatg-atcc/mG-26_pMTK3-emiRFP670.dna"))

    def split(primer):
        i = 0
        while i < len(primer) and primer[i].islower():
            i += 1
        return primer[:i].upper(), primer[i:].upper()

    def pcr(tpl, fwd, rev):
        s = (tpl.sequence + tpl.sequence).upper()
        ftail, fa = split(fwd)
        rtail, ra = split(rev)
        i = s.find(fa)
        j = s.find(rc(ra), i) if i >= 0 else -1
        if i < 0 or j < 0:
            return None
        return ftail + s[i:j + len(ra)] + rc(rtail)

    def overlap(a, b, cap=60):
        for L in range(min(cap, len(a), len(b)), 0, -1):
            if a[-L:] == b[:L]:
                return L
        return 0

    ok = True
    for homology in (20, 25):
        r = design.design_gibson_insertion(vec, ins, 1555, 1343, 1075, 2010,
                                           homology=homology, name="T")
        vamp = pcr(vec, r["vector"].forward.sequence, r["vector"].reverse.sequence)
        iamp = pcr(ins, r["insert"].forward.sequence, r["insert"].reverse.sequence)
        if vamp is None or iamp is None:
            ok &= check("homology %d: primers anneal" % homology, False)
            continue
        o1 = overlap(vamp, iamp)
        o2 = overlap(iamp, vamp)
        ok &= check("homology %d: both overlaps >= 20 bp" % homology,
                    o1 >= 20 and o2 >= 20, "%d and %d bp" % (o1, o2))
        ok &= check("homology %d: overlaps are the requested length" % homology,
                    o1 == homology and o2 == homology, "%d and %d" % (o1, o2))
        joined = vamp + iamp[o1:len(iamp) - o2]
        prod = r["product"].sequence.upper()
        ok &= check("homology %d: simulated assembly == designed product" % homology,
                    len(joined) == len(prod) and joined.upper() in prod + prod,
                    "%d bp vs %d bp" % (len(joined), len(prod)))
    # A junction linker must land in the product exactly once.
    r = design.design_gibson_insertion(vec, ins, 1555, 1343, 1075, 2010,
                                       homology=20, extra_5="GGCAGCGGCGGATCC",
                                       name="T")
    ok &= check("a junction linker appears once in the product",
                r["product"].sequence.upper().count("GGCAGCGGCGGATCC") == 1)
    return ok


def run_feature_transfer():
    """Every design path must carry annotation onto its product.

    A map with no features is a map nobody can read, and the loss is silent —
    the sequence is still right, so nothing else catches it.
    """
    from snapgene import rc
    print("Features survive every design path")
    vec = load(P("TUs/TU1-5_LS_R1_TRE-GvpA.dna"))
    ins = load(P("MTK_Parts/Type 3_CDSs_tatg-atcc/mG-26_pMTK3-emiRFP670.dna"))

    gib = design.design_gibson_insertion(vec, ins, 1555, 1343, 1075, 2010,
                                         homology=20, name="T")["product"]
    ok = check("Gibson product has features", len(gib.features) > 0,
               "%d features" % len(gib.features))
    ok &= check("Gibson keeps vector annotation",
                any(f.name == "TRE3GV promoter" for f in gib.features))
    ok &= check("Gibson keeps insert annotation",
                any("emiRFP" in f.name for f in gib.features))
    ok &= check("Gibson drops what was deleted",
                not any(f.name == "GvpA" for f in gib.features))

    # Every carried feature must actually sit on its parent's sequence.
    s = gib.sequence.upper()
    both = (vec.sequence * 2).upper() + "\x00" + (ins.sequence * 2).upper()
    misplaced = [f.name for f in gib.features
                 if f.name != "junction insert"
                 and s[f.start - 1:f.end] not in both
                 and rc(s[f.start - 1:f.end]) not in both]
    ok &= check("carried features sit on their original sequence", not misplaced,
                ", ".join(misplaced[:4]))

    kld = design.apply_kld(vec, 1343, 1555, "")
    ok &= check("KLD product has features", len(kld.features) > 0,
                "%d features" % len(kld.features))

    from moclo import build_tu
    tu = build_tu([load(P(p)) for p in TU_CASES[0][1]], load(P(TU_CASES[0][2])), "t")
    ok &= check("MoClo product has features", len(tu.features) > 0,
                "%d features" % len(tu.features))
    return ok


def run_csv_format():
    """The `ta` cell must carry the PCR product length, not the template's.

    Easy to get wrong and easy to miss: for a whole-plasmid KLD the two numbers
    differ by only the size of the edit, so a wrong one still looks plausible.
    """
    import csv as _csv
    import io

    import primer_csv
    print("Primer CSV format")
    vec = load(P("TUs/TU1-5_LS_R1_TRE-GvpA.dna"))
    ins = load(P("MTK_Parts/Type 3_CDSs_tatg-atcc/mG-26_pMTK3-emiRFP670.dna"))
    r = design.design_gibson_insertion(vec, ins, 1555, 1343, 1075, 2010,
                                       homology=20, name="T")
    pairs = [r["vector"], r["insert"]]
    tmp = os.path.join(tempfile.gettempdir(), "_validate_primers.csv")
    primer_csv.write(pairs, tmp)
    rows = [x for x in _csv.DictReader(open(tmp, encoding="utf-8")) if x["name"]]
    os.remove(tmp)

    ok = check("lab columns come first",
               list(_csv.DictReader(io.StringIO(",".join(
                   primer_csv.LAB_FIELDS) + "\n")).fieldnames)
               == primer_csv.LAB_FIELDS)
    for pair in pairs:
        cell = [x["ta"] for x in rows if x["name"] == pair.forward.name][0]
        ok &= check("%s: ta cell quotes the product (%d bp)"
                    % (pair.forward.name, pair.product_len),
                    "%d bp" % pair.product_len in cell, cell)
        ok &= check("%s: ta cell is not the template length"
                    % pair.forward.name,
                    pair.template_len == pair.product_len
                    or "%d bp" % pair.template_len not in cell, cell)
    ok &= check("template length still carried in its own column",
                all(x["template_len_bp"] for x in rows))
    ok &= check("ta written once per pair, on the forward row",
                sum(1 for x in rows if x["ta"]) == len(pairs))
    return ok


def run_provenance():
    """A built product must carry its inputs' full ancestry, not just their names."""
    import xml.etree.ElementTree as ET
    from moclo import build_tu
    print("Provenance: a MoClo product records its inputs and their ancestry")
    parts = [load(P(p)) for p in TU_CASES[0][1]]
    acc = load(P(TU_CASES[0][2]))
    tu = build_tu(parts, acc, "provenance_test")
    ok = check("product has a history tree", bool(tu.history_xml))
    if not tu.history_xml:
        return False
    try:
        root = ET.fromstring(tu.history_xml).find("Node")
    except ET.ParseError as exc:                            # noqa: BLE001
        return check("history parses as XML", False, str(exc))
    kids = root.findall("Node")
    ok &= check("every input appears", len(kids) == len(parts) + 1,
                "%d nodes for %d inputs" % (len(kids), len(parts) + 1))
    # At least one input must contribute a nested subtree of its own.
    nested = max((len(k.findall("Node")) for k in kids), default=0)
    ok &= check("an input's own ancestry is nested inside", nested > 0,
                "deepest input contributes %d sub-nodes" % nested)
    ids = [n.get("ID") for n in root.iter("Node")]
    ok &= check("node IDs are unique", len(ids) == len(set(ids)),
                "%d nodes, %d distinct IDs" % (len(ids), len(set(ids))))
    return ok


def run_kld_roundtrip():
    print("KLD product matches its primers")
    d = load(P("TUs/TU1-1_LS_R1_EF1a-rtTA.dna"))
    ok = True
    for start, end, ins in [(2200, 2260, ""), (2200, 2205, "GGCAGCGGC"), (2200, 2199, "ATGGTG")]:
        pair = design.design_kld(d, start, end, ins)
        product = design.apply_kld(d, start, end, ins)
        # The forward primer's annealing region must open the product, and the
        # reverse primer's must close it, once the product is rotated so the
        # junction sits at the origin.
        f_ok = pair.forward.anneal.upper() in (product.sequence + product.sequence).upper()
        r_ok = design.rc(pair.reverse.anneal).upper() in (product.sequence * 2).upper()
        expected = len(d) - (end - start + 1 if end >= start else 0) + len(ins)
        ok &= check("delete %d..%d insert %dnt" % (start, end, len(ins)),
                    f_ok and r_ok and len(product) == expected,
                    "product %d bp (expected %d)" % (len(product), expected))
    return ok


def run_part_sweep():
    print("Part sweep: every catalogued part digests to exactly one clean fragment")
    import csv as _csv
    inv = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets", "mtk_inventory.csv")
    if not os.path.exists(inv):
        print("  SKIP (no inventory; run inventory.py --refresh)")
        return True
    rows = [r for r in _csv.DictReader(open(inv, encoding="utf-8"))
            if r["category"] in ("MTK part", "TU", "acceptor", "MTK0 backbone")]
    bad = [r["name"] for r in rows if not r["left_overhang"]]
    okrows = len(rows) - len(bad)
    ok = check("%d/%d parts classified" % (okrows, len(rows)), not bad,
               ", ".join(bad[:5]))
    # Every declared part type must present the overhangs its type demands.
    from moclo import MTK_PART_OVERHANGS
    mism = []
    for r in rows:
        t = r["part_type"]
        if t and t in MTK_PART_OVERHANGS:
            want = MTK_PART_OVERHANGS[t]
            if (r["left_overhang"], r["right_overhang"]) != want:
                mism.append(r["name"])
    ok &= check("part overhangs match their declared type", not mism,
                ", ".join(mism[:5]))
    return ok


def run_sweep():
    """Rebuild every TU and assembly from the history recorded inside it.

    The broadest check there is: for each file that records a Golden Gate step,
    resolve its inputs on disk, re-run the assembly and compare. Inputs are
    matched on name *and* length, because SnapGene history nodes keep the name
    a file had when it was used and some have since been renamed.
    """
    import glob
    from history import enzymes, inputs as hist_inputs
    from moclo import golden_gate

    root = os.path.join(repo_root(), "Sequences", "MammalianToolKit")
    cache = {}

    def get(path):
        if path not in cache:
            try:
                cache[path] = load(path)
            except Exception:                              # noqa: BLE001
                cache[path] = None
        return cache[path]

    by_name, by_len = {}, {}
    for dirpath, _d, filenames in os.walk(root):
        for fn in filenames:
            if not fn.endswith(".dna"):
                continue
            path = os.path.join(dirpath, fn)
            d = get(path)
            if d is None:
                continue
            by_name.setdefault(fn, []).append(path)
            by_len.setdefault(len(d), []).append(path)

    ok = mismatch = incomplete = skipped = 0
    bad = []
    targets = sorted(glob.glob(os.path.join(root, "Assemblies", "*.dna")))
    targets += sorted(glob.glob(os.path.join(root, "TUs", "*.dna")))
    for target in targets:
        if "conflicted" in target or "(from " in target:
            continue
        recorded = hist_inputs(target)
        enz = [e for e in enzymes(target) if e in ("BsaI", "BsmBI")]
        if not recorded or not enz:
            skipped += 1
            continue
        paths, resolved = [], True
        for node in recorded:
            cands = [p for p in by_name.get(node["name"], [])
                     if len(get(p)) == node["length"]]
            cands = cands or by_len.get(node["length"], [])
            if not cands:
                resolved = False
                break
            paths.append(cands[0])
        if not resolved:
            incomplete += 1
            continue
        try:
            built = golden_gate([get(p) for p in paths], enz[0], "x")
        except Exception:                                  # noqa: BLE001
            incomplete += 1
            continue
        if rotation_match(built.sequence, get(target).sequence):
            ok += 1
        else:
            mismatch += 1
            bad.append(os.path.basename(target))

    print("Repo sweep: rebuild every construct from its own recorded history")
    passed = check("%d constructs rebuilt exactly, %d wrong" % (ok, mismatch),
                   mismatch == 0, ", ".join(bad[:5]))
    print("  %d skipped (no Golden Gate history), %d with an input that could not "
          "be resolved or assembled" % (skipped, incomplete))
    return passed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--sweep", action="store_true",
                    help="also rebuild every construct in the repo from its history")
    args = ap.parse_args(argv)

    results = [run_roundtrip(), run_tu_cases(), run_plasmid_cases(),
               run_kld_roundtrip(), run_tm_cases(), run_provenance(),
               run_binding_sites(), run_structure_checks(), run_naming(),
               run_gibson(), run_feature_transfer(), run_csv_format()]
    if not args.quick:
        results.append(run_part_sweep())
    if args.sweep:
        results.append(run_sweep())
    print()
    if all(results):
        print("all checks passed")
        return 0
    print("SOME CHECKS FAILED")
    return 1


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    raise SystemExit(main())
