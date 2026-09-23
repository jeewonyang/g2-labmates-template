#!/usr/bin/env python3
"""Find MTK parts and TUs carrying Type IIS sites they should not have.

    python qc_sites.py            # print the report
    python qc_sites.py --write    # also refresh Sequences/_domestication/

A clean MoClo component has exactly **two** sites of the enzyme used at its own
level (BsaI for an MTK part, BsmBI for a TU or backbone) and **none** of the
other one. Two failure modes matter, and they fail at different times:

*Blocking* — the wrong number of sites of its own enzyme. The one-pot reaction
cannot release a single clean fragment, so the assembly fails outright. This is
caught immediately.

*Latent* — a stray site of the *other* level's enzyme. A Type 2/3/4 part with
an internal BsmBI site assembles into a TU perfectly well, then breaks the
TU-to-plasmid step weeks later; this is how a broken TU usually comes about,
and the part, not the TU, is the thing to fix.

**Connectors legitimately carry one BsmBI site.** A Type 1 or Type 5 part
contributes the half-site that becomes the finished TU's own BsmBI boundary, so
exactly one is correct there and is not reported. Expectations per type are
taken from the collection itself: Type 1 and 5 carry one, everything else
carries none, and every component carries two of its own enzyme.

The fix in both cases is domestication: remove the internal site with a silent
change (a synonymous codon inside a CDS), usually by KLD, then re-clone.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import re

import naming
from moclo import classify_part, cut_positions, load

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIELDS = ["name", "category", "own_enzyme", "own_sites", "other_enzyme",
          "other_sites", "severity", "problem", "path"]


def own_enzyme(category: str) -> str:
    return "BsaI" if category in ("MTK part", "acceptor") else "BsmBI"


# How many sites of the *other* level's enzyme a clean component carries.
# Connectors carry one on purpose: it becomes the TU's own boundary.
EXPECTED_OTHER = {"1": 1, "5": 1, "12": 1}


def expected_other(part_type: str | None) -> int:
    return EXPECTED_OTHER.get(part_type or "", 0)


def part_type_of(d, parent: str) -> str | None:
    info = classify_part(d)
    if "part_type" in info:
        return info["part_type"]
    m = re.match(r"Type (\d+)", parent)
    return m.group(1) if m else None


def scan(root: str | None = None) -> list:
    root = root or os.path.join(naming.sequences_root(), "MammalianToolKit")
    rows = []
    for dirpath, _d, filenames in os.walk(root):
        for fn in sorted(filenames):
            if not fn.endswith(".dna") or any(j in fn for j in naming.JUNK):
                continue
            path = os.path.join(dirpath, fn)
            parent = os.path.basename(dirpath)
            parts = dirpath.split(os.sep)
            if "TUs" in parts:
                category = "TU"
            elif parent.startswith("Type 0"):
                category = "MTK0 backbone"
            elif parent.startswith("Type 678"):
                category = "acceptor"
            elif parent.startswith("Type"):
                category = "MTK part"
            else:
                continue
            try:
                d = load(path)
            except Exception:                                # noqa: BLE001
                continue
            mine = own_enzyme(category)
            other = "BsaI" if mine == "BsmBI" else "BsmBI"
            ptype = part_type_of(d, parent) if category == "MTK part" else None
            want_other = expected_other(ptype)
            n_own = len(cut_positions(d.sequence, mine, d.circular))
            n_other = len(cut_positions(d.sequence, other, d.circular))
            if n_own == 2 and n_other == want_other:
                continue
            if n_own != 2:
                severity = "blocking"
                problem = ("%d %s sites instead of 2 — no single clean fragment, "
                           "the assembly fails" % (n_own, mine))
            elif n_other > want_other:
                extra = n_other - want_other
                if other == "BsmBI":
                    severity = "latent"
                    problem = ("%d stray BsmBI site%s — assembles into a TU fine, "
                               "then breaks that TU's plasmid assembly"
                               % (extra, "s" if extra > 1 else ""))
                else:
                    severity = "informational"
                    problem = ("%d stray BsaI site%s — harmless, since this %s is "
                               "only ever cut with BsmBI; it just cannot be "
                               "re-digested with BsaI"
                               % (extra, "s" if extra > 1 else "", category))
            else:
                severity = "informational"
                problem = ("%d %s site(s), expected %d" % (n_other, other, want_other))
            rows.append(dict(
                name=os.path.splitext(fn)[0], category=category,
                own_enzyme=mine, own_sites=n_own, other_enzyme=other,
                other_sites=n_other, severity=severity, problem=problem,
                path=os.path.relpath(path, os.path.dirname(naming.sequences_root()))))
    order = {"blocking": 0, "latent": 1, "informational": 2}
    rows.sort(key=lambda r: (order.get(r["severity"], 3), r["category"], r["name"]))
    return rows


def render(rows: list) -> str:
    blocking = [r for r in rows if r["severity"] == "blocking"]
    latent = [r for r in rows if r["severity"] == "latent"]
    info = [r for r in rows if r["severity"] == "informational"]
    out = ["# Components needing domestication", "",
           "Generated by `.claude/skills/molecular-cloning/scripts/qc_sites.py`.",
           "Refresh with `python qc_sites.py --write` after changing anything in",
           "`Sequences/MammalianToolKit/`.", "",
           "A clean MoClo component has exactly two sites of its own enzyme (BsaI",
           "for an MTK part, BsmBI for a TU or backbone) and none of the other.",
           "Everything below breaks one of those rules. **Nothing here has been",
           "fixed — this is a to-do list, not a record.**", ""]

    out += ["## Blocking — the assembly will fail", ""]
    if blocking:
        out += ["| Component | Kind | Problem |", "|---|---|---|"]
        out += ["| `%s` | %s | %s |" % (r["name"], r["category"], r["problem"])
                for r in blocking]
    else:
        out.append("None.")
    out.append("")

    out += ["## Latent — assembles now, breaks at the next level", "",
            "A Type 2/3/4 part with a stray BsmBI site is the usual root cause of a",
            "broken TU: fix the part and rebuild the TU, rather than patching the TU.",
            ""]
    if latent:
        out += ["| Component | Kind | Problem |", "|---|---|---|"]
        out += ["| `%s` | %s | %s |" % (r["name"], r["category"], r["problem"])
                for r in latent]
    else:
        out.append("None.")

    out.append("")
    out += ["## Informational — no action needed now", ""]
    if info:
        out += ["| Component | Kind | Note |", "|---|---|---|"]
        out += ["| `%s` | %s | %s |" % (r["name"], r["category"], r["problem"])
                for r in info]
    else:
        out.append("None.")

    out += ["", "## How to fix one", "",
            "Domestication: remove the internal site with a change that does not",
            "alter the product — a synonymous codon inside a CDS, any single base",
            "in a non-coding stretch — then re-clone. With the skill:", "",
            "```bash",
            "cd .claude/skills/molecular-cloning/scripts",
            "python cloning.py inspect <part>.dna          # confirm the site positions",
            "python cloning.py kld <part>.dna --delete <n>-<n> --insert <newbase> \\",
            "    --name domesticate",
            "```", "",
            "Pick the base to change inside the recognition site, check the codon it",
            "sits in, and choose a synonymous replacement. Re-run `inspect` on the",
            "product to confirm the count dropped, then `qc_sites.py --write` to",
            "refresh this file.", "",
            "## Known good alternatives", "",
            "| Instead of | Use |", "|---|---|",
            "| `mG-16_pMTK3-PuroR` | `mG-16-2_pMTK3-PuroR_noBsaI` |",
            "| `mG-40_MTK0_piggyBac_noHygroR_hGH` | `mG-39_MTK0_piggyBac_noHygroR_SV40` "
            "or `mG-31_MTK0_piggyBac_noHygoR` (different polyA — check that suits) |",
            "",
            "## Where a broken TU comes from", "",
            "The two blocking TUs trace directly to parts in the latent list:", "",
            "| Broken TU | Caused by |", "|---|---|",
            "| `TU1-38_LS_R1_EF1a-DRD2` (3 BsmBI) | `mG-51_pMTK3-DRD2-Gqi` (1 stray BsmBI) |",
            "| `TU1-39_LS_R1_EF1a_M1` (4 BsmBI) | `mG-52_pMTK3-M1Ach-Gq` (2 stray BsmBI) |",
            "",
            "Domesticating the part and rebuilding the TU fixes both at once;",
            "editing the TU alone leaves the part to cause it again.",
            ""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="refresh Sequences/_domestication/")
    args = ap.parse_args(argv)

    rows = scan()
    text = render(rows)
    print(text)

    if args.write:
        folder = os.path.join(naming.sequences_root(), "_domestication")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "README.md"), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        with open(os.path.join(folder, "needs_domestication.csv"), "w",
                  newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print("\nwrote %s/README.md and needs_domestication.csv" % folder)


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
