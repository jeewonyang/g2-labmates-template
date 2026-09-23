#!/usr/bin/env python3
"""One entry point for every cloning job in this skill.

    cloning.py inspect  PLASMID.dna [...]
    cloning.py kld      PLASMID.dna --delete 500-620 [--insert ATG...] -o OUTDIR
    cloning.py gibson   --vector V.dna --open 1200,1400 \
                        --insert I.dna --region 50-800 -o OUTDIR
    cloning.py re       --template T.dna --region 50-800 --five NdeI --three XhoI -o OUTDIR
    cloning.py moclo    --parts A.dna B.dna ... --acceptor ACC.dna -o OUTDIR
    cloning.py moclo    --tus TU1.dna TU2.dna --backbone MTK0.dna -o OUTDIR
    cloning.py digest   PLASMID.dna --enzyme BsaI

Every design command writes two files into OUTDIR: the product map as a
SnapGene `.dna` and the primers as a `.csv` in the lab's Primer_All format.
OUTDIR defaults to `Sequences/_designs/` — a staging area, deliberately not the
curated collection, because nothing in it has been built yet.
Coordinates are 1-based and inclusive, matching what SnapGene shows.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design
import moclo
import naming
import primer_csv
from snapgene import Dseq, Feature, Primer


def default_outdir() -> str:
    """Where finished designs go: Sequences/_designs/ in the LabSerf repo.

    Kept separate from the curated collection on purpose — nothing here has
    been built or sequenced yet. Move a map into Sequences/MammalianToolKit/
    or Sequences/Sequence_JWY/ once it exists as real DNA.
    """
    d = os.path.dirname(os.path.abspath(__file__))
    while d != "/":
        seqs = os.path.join(d, "Sequences")
        if os.path.isdir(seqs):
            return os.path.join(seqs, "_designs")
        d = os.path.dirname(d)
    return os.getcwd()


def _load(path: str) -> Dseq:
    return moclo.load(path)


def _span(text: str) -> tuple:
    """Parse '500-620' or '500..620' into (500, 620)."""
    t = text.replace("..", "-").strip()
    if "-" not in t:
        raise argparse.ArgumentTypeError("expected START-END, got %r" % text)
    a, b = t.split("-", 1)
    return int(a), int(b)


def _pair(text: str) -> tuple:
    t = text.replace("..", ",").replace("-", ",").strip()
    if "," not in t:
        raise argparse.ArgumentTypeError("expected AFTER,BEFORE, got %r" % text)
    a, b = t.split(",", 1)
    return int(a), int(b)


def _as_primers(pairs: list) -> list:
    """The designed oligos as SnapGene primer records."""
    out = []
    for pair in pairs:
        for p in (pair.forward, pair.reverse):
            desc = "%s. Tm %.1f C (annealing region only), pair Ta %.0f C, " \
                   "%d nt. %s" % (p.role or "primer", p.tm, pair.ta, p.length,
                                  pair.description)
            if p.warnings:
                desc += " Warnings: " + "; ".join(p.warnings)
            out.append(Primer(p.name, p.sequence, desc))
    return out


def _emit(product: Dseq, pairs: list, outdir: str, stem: str, notes=None,
          templates: list | None = None, operation: str = "") -> None:
    """Write the product map and the primer CSV.

    The primers are stored in the product's own map with their binding sites
    computed, so SnapGene draws them on the main display rather than merely
    listing them. `templates` are the starting plasmids; they are recorded in
    the product's History tree and are never written to or copied.
    """
    os.makedirs(outdir, exist_ok=True)
    dna = os.path.join(outdir, stem + ".dna")
    csvp = os.path.join(outdir, stem + "_primers.csv")

    primers = _as_primers(pairs)
    product.primers = primers
    if operation and templates:
        product.history_xml = moclo.build_history(product, templates, None, operation)
    product.write(dna)
    primer_csv.write(pairs, csvp, notes=notes)

    print(primer_csv.summarise(pairs))
    _report_tu_overlap(product)
    print("map      %s  (%d bp, %s)" % (dna, len(product),
                                        "circular" if product.circular else "linear"))
    print("primers  %s" % csvp)


# -- commands -------------------------------------------------------------


def _report_tu_overlap(product) -> None:
    """If a primer-based product is really a TU, say what it resembles.

    `build` does this before taking an ID; the primer commands produce TUs too
    — a CDS swapped into an existing TU is still a TU — so the same warning
    belongs here, or an identical part gets cloned twice under two numbers.
    """
    try:
        info = moclo.classify_part(product)
    except Exception:                                    # noqa: BLE001
        return
    slot = info.get("tu_position")
    if not slot:
        return
    exact, near = _find_duplicate_tu(product, slot, ignore=product.name)
    con_l, con_r = info.get("tu_slot", ("?", "?"))
    print("  this product is a slot-%s TU (%s-%s)" % (slot, con_l, con_r))
    if exact is not None:
        print("  !! identical to %s, which already exists — you may not need to "
              "clone this at all" % exact.name)
    for other, delta in near:
        print("  !  %s has the same components and is %+d bp relative to this one"
              % (other.name, delta))
    print()


def cmd_inspect(args):
    for path in args.plasmid:
        d = _load(path)
        info = moclo.classify_part(d)
        print("%s" % d.name)
        print("  %d bp, %s" % (len(d), "circular" if d.circular else "linear"))
        for enz in ("BsaI", "BsmBI"):
            hits = moclo.cut_positions(d.sequence, enz, d.circular)
            if hits:
                print("  %-6s %d site(s) at %s" % (enz, len(hits),
                                                   ", ".join(str(h + 1) for h in hits)))
        if "part_type" in info:
            print("  MTK part type %s, overhangs %s/%s"
                  % (info["part_type"], *info["BsaI"]))
        if "tu_slot" in info:
            print("  TU for slot %s (%s-%s), overhangs %s/%s"
                  % (info.get("tu_position", "?"), *info["tu_slot"], *info["BsmBI"]))
        if info.get("role"):
            print("  %s, overhangs %s/%s" % (info["role"], *info["BsmBI"]))
        if d.features:
            print("  features: %s" % ", ".join(
                "%s(%d..%d)" % (f.name, f.start, f.end) for f in d.features[:14]))
        print()


def cmd_digest(args):
    d = _load(args.plasmid)
    frags = moclo.digest(d, args.enzyme)
    print("%s: %d fragment(s) with %s" % (d.name, len(frags), args.enzyme))
    for f in frags:
        site = moclo.ENZYME_SPEC[args.enzyme][0]
        body = (f.top + f.right_overhang).upper()
        has = site in body or moclo.rc(site) in body
        print("  %6d bp  %s..%s  %s" % (len(f.top), f.left_overhang, f.right_overhang,
                                        "contains site" if has else "RELEASED"))


def cmd_kld(args):
    d = _load(args.plasmid)
    start, end = args.delete if args.delete else (args.at + 1, args.at)
    pair = design.design_kld(d, start, end, args.insert or "", args.name,
                             target_tm=args.tm)
    product = design.apply_kld(d, start, end, args.insert or "",
                               args.product_name or (d.name + "_" + args.name))
    _emit(product, [pair], args.out, args.product_name or (d.name + "_" + args.name),
          templates=[d], operation="circularize")


def cmd_gibson(args):
    vec = _load(args.vector)
    ins = _load(args.insert)
    open_a, open_b = args.open
    istart, iend = args.region
    res = design.design_gibson_insertion(
        vec, ins, open_a, open_b, istart, iend, name=args.name, target_tm=args.tm,
        homology=args.homology, insert_strand=-1 if args.reverse else 1,
        extra_5=args.extra5 or "", extra_3=args.extra3 or "")
    stem = args.product_name or "%s_%s" % (vec.name, ins.name)
    res["product"].name = stem
    _emit(res["product"], [res["vector"], res["insert"]], args.out, stem,
          templates=[vec, ins], operation="hifiAssembly")


def cmd_re(args):
    t = _load(args.template)
    start, end = args.region
    pair = design.design_re(t, start, end, args.five, args.three, args.name,
                            target_tm=args.tm, spacer_5=args.spacer5 or "",
                            spacer_3=args.spacer3 or "")
    body = t.subsequence(start, end)
    offset = len(pair.forward.tail)
    frag = Dseq(pair.forward.tail.upper() + body + pair.reverse.tail.upper(),
                False, args.product_name or (args.name + "_insert"))
    frag.features.append(Feature(args.name + " insert", offset + 1,
                                 offset + len(body), 1, "misc_feature"))
    # Carry the template's annotation across, and mark the added sites so the
    # map shows what the PCR actually added rather than just a bare fragment.
    for f in t.features:
        if start <= f.start and f.end <= end:
            frag.features.append(Feature(f.name, offset + f.start - start + 1,
                                         offset + f.end - start + 1, f.strand,
                                         f.type, f.color, dict(f.notes)))
    frag.features.append(Feature(args.five + " site", 1, offset, 1, "misc_feature",
                                 "#ffef86"))
    frag.features.append(Feature(args.three + " site", offset + len(body) + 1,
                                 len(frag), -1, "misc_feature", "#ffef86"))
    frag.features.sort(key=lambda f: (f.start, f.end))
    _emit(frag, [pair], args.out, args.product_name or (args.name + "_insert"),
          templates=[t], operation="amplifyFragment")


def cmd_moclo(args):
    if args.parts:
        if not args.acceptor:
            raise SystemExit("--parts needs --acceptor")
        parts = [_load(p) for p in args.parts]
        acc = _load(args.acceptor)
        name = args.name or "TU_new"
        product = moclo.build_tu(parts, acc, name)
        inputs = parts + [acc]
        enzyme = "BsaI"
    elif args.tus:
        if not args.backbone:
            raise SystemExit("--tus needs --backbone")
        tus = [_load(t) for t in args.tus]
        bb = _load(args.backbone)
        name = args.name or "construct"
        product = moclo.build_plasmid(tus, bb, name)
        inputs = tus + [bb]
        enzyme = "BsmBI"
    else:
        raise SystemExit("give either --parts/--acceptor or --tus/--backbone")

    os.makedirs(args.out, exist_ok=True)
    dna = os.path.join(args.out, name + ".dna")
    product.description = "%s assembly of: %s" % (
        enzyme, ", ".join(p.name for p in inputs))
    product.write(dna)
    print("%s assembly -> %s" % (enzyme, name))
    for p in inputs:
        f = moclo.released_fragment(p, enzyme)
        print("  %-46s %6d bp  %s..%s" % (p.name[:46], len(f.top),
                                          f.left_overhang, f.right_overhang))
    print("  %-46s %6d bp" % ("PRODUCT", len(product)))
    print("\nmap %s" % dna)
    print("\nNo primers needed: every fragment comes from an existing plasmid. "
          "Set up the reaction per references/protocols.md.")


def cmd_ids(args):
    print("Construct IDs currently in use under Sequences/")
    print(naming.describe_ids())
    print("\nmL = Lentiviral, mT = Transient transfection, mPB = piggyBac.")
    print("mL and mT number independently; mPB continues the piggyBac numbering")
    print("already recorded under mT, so the first one is mPB-116.")
    print("\nNote on the old collection: mT was used for most piggyBac constructs")
    print("before this convention settled (65 of 80 mT-* carry a pPB vector, only 9")
    print("are transient). Those keep their names; new piggyBac work is mPB.")


def _default_acceptor():
    root = naming.sequences_root()
    cand = os.path.join(root, "MammalianToolKit", "MTK_Parts",
                        "Type 678_acceptor_ccct-taca", "G12_pMTK678_mScarlet.dna")
    return cand if os.path.exists(cand) else None


def _existing_tus(slot: int):
    """Every catalogued TU for a slot, plus anything already in _designs."""
    root = naming.sequences_root()
    out = []
    for folder in (os.path.join(root, "MammalianToolKit", "TUs"),
                   os.path.join(root, "_designs")):
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if not fn.startswith("TU%d-" % slot) or not fn.endswith(".dna"):
                continue
            if any(j in fn for j in naming.JUNK):
                continue
            try:
                out.append(moclo.load(os.path.join(folder, fn)))
            except Exception:                                # noqa: BLE001
                continue
    return out


def _find_duplicate_tu(tu, slot: int, ignore: str = ""):
    """(exact_match, near_matches) among TUs that already exist.

    Exact means the released insert is the same DNA — building it again would
    just burn a fresh ID on a part the lab already has. Near means the same
    components by name, which is usually a sign you meant the existing one.
    """
    try:
        mine = moclo.released_fragment(tu, "BsmBI")
    except ValueError:
        return None, []
    my_desc = naming.part_label(tu.name).lower().replace("_", "-")
    exact, near = None, []
    for other in _existing_tus(slot):
        if ignore and other.name == ignore:
            continue        # a previous run of this same design, not a duplicate
        try:
            theirs = moclo.released_fragment(other, "BsmBI")
        except ValueError:
            continue
        if (theirs.top.upper() == mine.top.upper()
                and theirs.left_overhang == mine.left_overhang):
            exact = other
            break
        if naming.part_label(other.name).lower().replace("_", "-") == my_desc:
            near.append((other, len(theirs.top) - len(mine.top)))
    return exact, near


def cmd_build(args):
    """Build a plasmid, making any TU that does not exist yet along the way.

    Each intermediate is written as its own named `.dna` with its own history,
    so the TU is a real, reusable part of the collection rather than something
    that only exists inside the final construct.
    """
    os.makedirs(args.out, exist_ok=True)
    used = naming.scan_ids()
    backbone = _load(args.backbone)
    kind = args.kind or naming.backbone_kind(backbone)
    if kind is None:
        raise SystemExit(
            "cannot tell what kind of backbone %s is — it matches neither a "
            "lentiviral, piggyBac nor transient pattern (landing-pad backbones "
            "such as attB or AAVS1 land here). Pass --kind mL|mT|mPB."
            % backbone.name)
    made = []

    tus = []
    for slot in (1, 2, 3, 4):
        existing = getattr(args, "tu%d" % slot)
        parts = getattr(args, "tu%d_parts" % slot)
        if existing and parts:
            raise SystemExit("--tu%d and --tu%d-parts are mutually exclusive" % (slot, slot))
        if existing:
            tus.append(_load(existing))
            continue
        if not parts:
            continue

        acceptor_path = args.acceptor or _default_acceptor()
        if not acceptor_path:
            raise SystemExit("building a TU needs --acceptor (no G12 acceptor found)")
        acceptor = _load(acceptor_path)
        part_maps = [_load(p) for p in parts]

        # Assemble first: the connectors the product actually presents decide
        # the name, rather than what the slot was assumed to be.
        draft = moclo.build_tu(part_maps, acceptor, "draft")
        info = moclo.classify_part(draft)
        con_l, con_r = info.get("tu_slot", ("ConL?", "ConR?"))
        real_slot = info.get("tu_position", slot)
        if real_slot != slot:
            print("note: these parts make a slot-%s TU (%s-%s), not slot %d"
                  % (real_slot, con_l, con_r, slot))

        desc = getattr(args, "tu%d_desc" % slot) or naming.describe(part_maps)
        cid, _ = naming.next_id("TU%d" % real_slot, used=used)
        used.setdefault("TU%d" % real_slot, set()).add(cid)
        stem = naming.tu_filename(real_slot, cid, con_l, con_r, desc)

        tu = moclo.build_tu(part_maps, acceptor, stem)
        exact, near = _find_duplicate_tu(tu, real_slot)
        if exact is not None and not args.force_new_tu:
            print("%s already exists as %s — using it instead of taking a new ID."
                  % (stem, exact.name))
            print("    (pass --force-new-tu to build it again anyway)")
            tus.append(exact)
            used["TU%d" % real_slot].discard(cid)
            continue
        for other, delta in near:
            print("note: %s has the same components and is %+d bp relative to this "
                  "one — check you did not mean that TU." % (other.name, delta))
        tu.description = "MTK BsaI assembly of: %s" % ", ".join(
            p.name for p in part_maps + [acceptor])
        path = os.path.join(args.out, stem + ".dna")
        if os.path.exists(path):
            raise SystemExit("%s already exists; pass --tu%d-desc to pick another name"
                             % (path, slot))
        tu.write(path)
        made.append((stem, len(tu), path, [p.name for p in part_maps + [acceptor]]))
        tus.append(tu)

    if not tus:
        raise SystemExit("give at least one --tuN or --tuN-parts")

    desc = args.desc or (naming.vector_tag(kind) + "-" + naming.describe(tus))
    cid = args.id or naming.next_id(kind, used=used)[0]
    stem = naming.plasmid_filename(kind, cid, desc)
    product = moclo.build_plasmid(tus, backbone, stem)
    product.description = "MTK BsmBI assembly of: %s" % ", ".join(
        t.name for t in tus + [backbone])
    path = os.path.join(args.out, stem + ".dna")
    if os.path.exists(path):
        raise SystemExit("%s already exists; pass --desc or --id to pick another name"
                         % path)
    product.write(path)

    if made:
        print("Built %d intermediate TU%s first:" % (len(made), "s" if len(made) > 1 else ""))
        for stem_i, ln, p_i, srcs in made:
            print("  %-52s %6d bp" % (stem_i, ln))
            print("      from %s" % ", ".join(srcs))
            print("      %s" % p_i)
        print()
    print("Final plasmid")
    for t in tus:
        f = moclo.released_fragment(t, "BsmBI")
        print("  %-52s %6d bp  %s..%s" % (t.name[:52], len(f.top),
                                          f.left_overhang, f.right_overhang))
    f = moclo.released_fragment(backbone, "BsmBI")
    print("  %-52s %6d bp  %s..%s" % (backbone.name[:52], len(f.top),
                                      f.left_overhang, f.right_overhang))
    print("  %-52s %6d bp" % ("PRODUCT " + stem, len(product)))
    print("\n  %s" % path)
    print("\nEvery map carries its full History tree. No primers needed.")


def build_parser():
    ap = argparse.ArgumentParser(
        prog="cloning.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect", help="identify a plasmid and its MTK role")
    p.add_argument("plasmid", nargs="+")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("digest", help="show Type IIS fragments")
    p.add_argument("plasmid")
    p.add_argument("--enzyme", default="BsaI", choices=sorted(moclo.ENZYME_SPEC))
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("kld", help="back-to-back primers for deletion/insertion/mutation")
    p.add_argument("plasmid")
    p.add_argument("--delete", type=_span, help="1-based inclusive range to remove")
    p.add_argument("--at", type=int, help="insert after this base, deleting nothing")
    p.add_argument("--insert", help="sequence to put in")
    p.add_argument("--name", default="KLD")
    p.add_argument("--product-name")
    p.add_argument("--tm", type=float, default=design.DEFAULT_TM)
    p.add_argument("-o", "--out", default=None,
                   help="output directory (default: Sequences/_designs/)")
    p.set_defaults(func=cmd_kld)

    p = sub.add_parser("gibson", help="NEBuilder HiFi two-fragment assembly")
    p.add_argument("--vector", required=True)
    p.add_argument("--open", type=_pair, required=True,
                   help="AFTER,BEFORE: the vector is kept from AFTER+1 round to BEFORE-1")
    p.add_argument("--insert", required=True)
    p.add_argument("--region", type=_span, required=True)
    p.add_argument("--reverse", action="store_true", help="insert goes in flipped")
    p.add_argument("--extra5", help="sequence spliced in at the 5' junction")
    p.add_argument("--extra3", help="sequence spliced in at the 3' junction")
    p.add_argument("--homology", type=int, default=design.HOMOLOGY_LEN)
    p.add_argument("--name", default="Gib")
    p.add_argument("--product-name")
    p.add_argument("--tm", type=float, default=design.DEFAULT_TM)
    p.add_argument("-o", "--out", default=None,
                   help="output directory (default: Sequences/_designs/)")
    p.set_defaults(func=cmd_gibson)

    p = sub.add_parser("re", help="add restriction sites by PCR")
    p.add_argument("--template", required=True)
    p.add_argument("--region", type=_span, required=True)
    p.add_argument("--five", required=True, help="enzyme at the 5' end")
    p.add_argument("--three", required=True, help="enzyme at the 3' end")
    p.add_argument("--spacer5")
    p.add_argument("--spacer3")
    p.add_argument("--name", default="RE")
    p.add_argument("--product-name")
    p.add_argument("--tm", type=float, default=design.DEFAULT_TM)
    p.add_argument("-o", "--out", default=None,
                   help="output directory (default: Sequences/_designs/)")
    p.set_defaults(func=cmd_re)

    p = sub.add_parser("ids", help="show the construct ID space")
    p.set_defaults(func=cmd_ids)

    p = sub.add_parser("build", help="build a plasmid, making missing TUs on the way")
    p.add_argument("--backbone", required=True, help="an MTK0 backbone .dna")
    for slot in (1, 2, 3, 4):
        p.add_argument("--tu%d" % slot, help="existing TU for slot %d" % slot)
        p.add_argument("--tu%d-parts" % slot, nargs="+",
                       help="MTK parts to build slot %d from" % slot)
        p.add_argument("--tu%d-desc" % slot, help="name the new slot-%d TU" % slot)
    p.add_argument("--acceptor", help="pMTK678 acceptor (default: G12_pMTK678_mScarlet)")
    p.add_argument("--desc", help="component string for the final plasmid name")
    p.add_argument("--id", type=int, help="force a construct ID")
    p.add_argument("--kind", choices=["mL", "mT", "mPB"],
                   help="mL lentiviral / mT transient / mPB piggyBac")
    p.add_argument("--force-new-tu", action="store_true",
                   help="build a TU even if an identical one already exists")
    p.add_argument("-o", "--out", default=None,
                   help="output directory (default: Sequences/_designs/)")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("moclo", help="Golden Gate assembly of MTK parts or TUs")
    p.add_argument("--parts", nargs="+")
    p.add_argument("--acceptor")
    p.add_argument("--tus", nargs="+")
    p.add_argument("--backbone")
    p.add_argument("--name")
    p.add_argument("-o", "--out", default=None,
                   help="output directory (default: Sequences/_designs/)")
    p.set_defaults(func=cmd_moclo)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "out", None) is None:
        args.out = default_outdir()
    args.func(args)


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
