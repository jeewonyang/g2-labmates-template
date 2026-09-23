"""Fail if the flow-cytometry skill depends on `ExampleData/`.

`ExampleData/` is reference material that was read once to build this skill.
Everything learned from it — the MQD/FCS scaling rule, the channel-resolution
table, the gate calibration — is written down in `references/`. The pipeline
must run on a folder the user names without reaching back into the examples.

    python check_self_contained.py --data_dir <a real run folder>
"""

from __future__ import annotations

import argparse
import os
import tempfile
import re
import subprocess
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGURE_DESIGN = os.path.join(os.path.dirname(SKILL), "figure-design")

#: Lines mentioning ExampleData that are documentation rather than a dependency.
_PROSE = re.compile(r"^\s*(#|\*|\"\"\"|'''|\||-|>)|provenance|example data|measured (on|from)",
                    re.I)


def scan_for_examplesdata() -> list[tuple[str, int, str]]:
    """Executable references to ExampleData in either skill's scripts."""
    hits = []
    for root in (os.path.join(SKILL, "scripts"), os.path.join(FIGURE_DESIGN, "scripts")):
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                # This file necessarily names ExampleData — it is the checker.
                if not f.endswith(".py") or f == os.path.basename(__file__):
                    continue
                path = os.path.join(dirpath, f)
                for i, line in enumerate(open(path, encoding="utf-8"), 1):
                    if "ExampleData" not in line:
                        continue
                    if _PROSE.search(line):
                        continue  # a comment or a docstring, not a dependency
                    hits.append((os.path.relpath(path, SKILL), i, line.strip()))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data_dir", required=True,
                    help="a real MACSQuant run folder, outside ExampleData/")
    ap.add_argument("--out", default=None, help="where to write the trial analysis")
    args = ap.parse_args()

    failures = []

    hits = scan_for_examplesdata()
    if hits:
        failures.append("scripts reference ExampleData/ in executable code:")
        for path, line, text in hits:
            failures.append(f"    {path}:{line}: {text}")
    else:
        print("ok: no executable reference to ExampleData/ in either skill's scripts")

    if os.path.abspath(args.data_dir).find(os.sep + "ExampleData" + os.sep) >= 0:
        failures.append(f"--data_dir is inside ExampleData/: {args.data_dir}. "
                        "Point this at a real run folder.")

    out = args.out or os.path.join(
        tempfile.gettempdir(), "flow_self_contained_check")
    cmd = [sys.executable, os.path.join(SKILL, "scripts", "analyze_flow.py"),
           args.data_dir, "--out", out]
    print(f"running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        failures.append(f"analyze_flow.py failed on {args.data_dir}:\n{proc.stderr[-2000:]}")
    else:
        print("ok: analyze_flow.py completed on the supplied folder")
        for expect in ("per_well.csv", "per_condition.csv", "stats.json",
                       "RESULTS.md", "figures", "prism"):
            if not os.path.exists(os.path.join(out, expect)):
                failures.append(f"expected output missing: {expect}")
        if not failures:
            print("ok: all expected outputs present")

    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nPASS: the skill is self-contained")
    return 0


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    sys.exit(main())
