#!/usr/bin/env python3
"""Read the assembly history SnapGene stores inside a .dna file.

SnapGene records the whole provenance tree of a construct — which plasmids went
in, which enzyme joined them, what happened before that — in segment 7. This
recovers it, so "how was mT-52 actually built?" is answerable from the file
rather than from memory.

    python history.py PLASMID.dna            # the immediate inputs
    python history.py PLASMID.dna --tree     # the whole tree
    python history.py PLASMID.dna --recipe   # a cloning.py command that rebuilds it
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _history_xml(path: str) -> str:
    raw = open(path, "rb").read()
    i = 0
    while i + 5 <= len(raw):
        stype = raw[i]
        slen = struct.unpack(">I", raw[i + 1:i + 5])[0]
        if stype == 7:
            return raw[i + 5:i + 5 + slen].decode("utf8", "replace")
        i += 5 + slen
    return ""


def tree(path: str):
    """The root history node, or None when the file records no history."""
    xml = _history_xml(path)
    if not xml:
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    return root.find("Node")


def node_info(node) -> dict:
    return {
        "name": node.get("name", "?"),
        "length": int(node.get("seqLen", 0) or 0),
        "circular": node.get("circular") == "1",
        "operation": node.get("operation", ""),
    }


def inputs(path: str) -> list:
    """The plasmids that went directly into making this one."""
    root = tree(path)
    if root is None:
        return []
    return [node_info(child) for child in root.findall("Node")]


def enzymes(path: str) -> list:
    """Enzyme names recorded on the top-level assembly step."""
    root = tree(path)
    if root is None:
        return []
    out = []
    for summ in root.findall("InputSummary"):
        for key in ("name1", "name2"):
            v = summ.get(key)
            if v and v not in out:
                out.append(v)
    return out


def walk(node, depth=0, limit=6):
    if node is None or depth > limit:
        return
    info = node_info(node)
    yield depth, info
    for child in node.findall("Node"):
        yield from walk(child, depth + 1, limit)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("plasmid", nargs="+")
    ap.add_argument("--tree", action="store_true")
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--recipe", action="store_true")
    args = ap.parse_args(argv)

    for path in args.plasmid:
        root = tree(path)
        print("%s" % os.path.basename(path))
        if root is None:
            print("  no history recorded")
            continue
        info = node_info(root)
        enz = enzymes(path)
        print("  %d bp, operation %s%s"
              % (info["length"], info["operation"],
                 (", enzymes " + "/".join(enz)) if enz else ""))
        if args.tree:
            for depth, n in walk(root, 0, args.depth):
                if depth == 0:
                    continue
                print("  %s%s  (%d bp, %s)" % ("  " * depth, n["name"], n["length"],
                                               n["operation"]))
        else:
            for n in inputs(path):
                print("    %-52s %6d bp  %s" % (n["name"][:52], n["length"],
                                                n["operation"]))
        if args.recipe:
            kids = [n["name"] for n in inputs(path)]
            tus = [k for k in kids if k.startswith("TU")]
            bb = [k for k in kids if not k.startswith("TU")]
            if tus:
                print("\n  cloning.py moclo --tus %s --backbone %s --name %s"
                      % (" ".join(tus), bb[0] if bb else "?",
                         os.path.splitext(os.path.basename(path))[0]))
        print()


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
