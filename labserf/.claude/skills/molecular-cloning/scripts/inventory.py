"""Build and search a catalog of the lab's MTK parts, TUs and backbones.

Run it to refresh `assets/mtk_inventory.csv` after new parts land in
Sequences/MammalianToolKit:

    python inventory.py --refresh
    python inventory.py --search "TRE"
    python inventory.py --slot 2            # everything that fits TU slot 2
    python inventory.py --type 3            # every MTK Type 3 CDS part

Each row records where the file is, what overhangs it presents to which
enzyme, and therefore what it can legally be assembled with. The overhangs are
measured from the sequence, not taken from the folder name, so a part filed in
the wrong folder shows up as a mismatch rather than silently breaking an
assembly.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from moclo import MTK_CONNECTORS, MTK_PART_OVERHANGS, TU_SLOTS, classify_part, load

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CSV = os.path.join(SKILL_DIR, "assets", "mtk_inventory.csv")
FIELDS = ["name", "category", "part_type", "tu_slot", "tu_position",
          "enzyme", "left_overhang", "right_overhang", "length", "features", "path"]


def _repo_root(start: str | None = None) -> str:
    """Walk up from the skill directory to the LabSerf repo root."""
    d = start or SKILL_DIR
    while d != "/":
        if os.path.isdir(os.path.join(d, "Sequences")):
            return d
        d = os.path.dirname(d)
    raise SystemExit("could not find the repo root (no Sequences/ above %s)" % SKILL_DIR)


def scan(root: str | None = None) -> list:
    root = root or os.path.join(_repo_root(), "Sequences", "MammalianToolKit")
    rows = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            if not fn.endswith(".dna"):
                continue
            # Sync artefacts and duplicates from other machines.
            if "conflicted copy" in fn or "(from SSD)" in fn or "(from Mac)" in fn:
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, _repo_root())
            try:
                d = load(path)
                info = classify_part(d)
            except Exception as exc:                      # noqa: BLE001
                rows.append(dict(name=os.path.splitext(fn)[0], category="unreadable",
                                 part_type="", tu_slot="", tu_position="", enzyme="",
                                 left_overhang="", right_overhang="", length="",
                                 features=str(exc)[:80], path=rel))
                continue

            category = _category(dirpath, info)
            enzyme = "BsaI" if "BsaI" in info else ("BsmBI" if "BsmBI" in info else "")
            lo, ro = info.get(enzyme, ("", ""))
            slot = info.get("tu_slot", ("", ""))
            rows.append(dict(
                name=info["name"], category=category,
                part_type=info.get("part_type", ""),
                tu_slot="%s-%s" % slot if slot[0] else info.get("role", ""),
                tu_position=info.get("tu_position", ""),
                enzyme=enzyme, left_overhang=lo, right_overhang=ro,
                length=info["length"],
                features="; ".join(f.name for f in d.features
                                   if f.type not in ("rep_origin",)
                                   and "NeoR" not in f.name)[:160],
                path=rel))
    return rows


def _category(dirpath: str, info: dict) -> str:
    parent = os.path.basename(dirpath)
    if "TUs" in dirpath.split(os.sep):
        return "TU"
    if parent.startswith("Type 0"):
        return "MTK0 backbone"
    if parent.startswith("Type 678"):
        return "acceptor"
    if parent.startswith("Type"):
        return "MTK part"
    if "Assemblies" in dirpath.split(os.sep):
        return "assembled plasmid"
    if "tu_slot" in info:
        return "TU"
    if "part_type" in info:
        return "MTK part"
    return "plasmid"


def write_csv(rows: list, path: str = DEFAULT_CSV) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def read_csv(path: str = DEFAULT_CSV) -> list:
    if not os.path.exists(path):
        raise SystemExit("no inventory at %s — run: python inventory.py --refresh" % path)
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="rescan and rewrite the CSV")
    ap.add_argument("--search", help="substring match on name or features")
    ap.add_argument("--type", help="MTK part type (0,1,2,3,4,5,678)")
    ap.add_argument("--slot", type=int, help="TU slot position 1-4")
    ap.add_argument("--category")
    ap.add_argument("--csv", default=DEFAULT_CSV)
    args = ap.parse_args(argv)

    if args.refresh:
        rows = scan()
        write_csv(rows, args.csv)
        cats = {}
        for r in rows:
            cats[r["category"]] = cats.get(r["category"], 0) + 1
        print("wrote %s (%d entries)" % (args.csv, len(rows)))
        for k in sorted(cats):
            print("  %-20s %d" % (k, cats[k]))
        return

    rows = read_csv(args.csv)
    if args.search:
        q = args.search.lower()
        rows = [r for r in rows if q in r["name"].lower() or q in r["features"].lower()]
    if args.type:
        rows = [r for r in rows if r["part_type"] == args.type]
    if args.slot:
        rows = [r for r in rows if str(r["tu_position"]) == str(args.slot)]
    if args.category:
        rows = [r for r in rows if r["category"] == args.category]

    if not rows:
        print("no match")
        return
    for r in rows:
        print("%-46s %-14s %-10s %4s %-9s %s" % (
            r["name"][:46], r["category"], r["tu_slot"][:10], r["length"],
            "%s/%s" % (r["left_overhang"], r["right_overhang"]) if r["left_overhang"] else "",
            r["features"][:60]))
    print("\n%d entries" % len(rows))


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
