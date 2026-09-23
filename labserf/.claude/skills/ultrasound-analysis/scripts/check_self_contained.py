#!/usr/bin/env python3
"""
check_self_contained.py — prove the skill's tools need nothing from ExampleData.

ExampleData/ was read once to build this skill. Everything learned from it is
written down in the references and the calibration CSVs, so processing a new
acquisition must never reach back into it. This script enforces that:

  1. static  — no tool source mentions ExampleData or an absolute repo path
  2. runtime — run each tool against a folder you name and record, via a Python
               audit hook, every file it opens inside the repo. Any read under
               ExampleData/ is a failure.

Usage
-----
    # static checks only
    python check_self_contained.py

    # static + runtime, against any real acquisition folder
    python check_self_contained.py --data_dir "/path/to/some/plate_or_acquisition"

Exit status is non-zero if any check fails, so it can gate a commit.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
REPO = SKILL.parents[2]                      # <repo>/.claude/skills/<name>/scripts
# Every tool in the skill, so a newly added one cannot quietly reintroduce a
# dependency on ExampleData.
TOOLS = ["identify_dataset.py", "auto_roi.py", "to_prism.py", "report_lib.py",
         "make_run_report.py", "make_well_map.py", "merge_plate_metadata.py",
         "organize_images.py", "plate_map_to_metadata.py", "view_bmode.py"]

AUDIT_STUB = '''
import sys, os, runpy
LOG, REPO = set(), {repo!r}
def hook(event, args):
    if event in ("open", "os.open") and args and isinstance(args[0], (str, bytes, os.PathLike)):
        try:
            p = os.path.abspath(os.fsdecode(args[0]))
        except Exception:
            return
        # Log anything under the repo (informational) AND any path containing an
        # ExampleData component wherever it lives — a leak must be caught even if
        # the tool is run from a copy whose computed repo root differs.
        if p.startswith(REPO) or os.sep + "ExampleData" + os.sep in p + os.sep:
            LOG.add(p)
sys.addaudithook(hook)
target, *argv = sys.argv[1:]
sys.argv = [target] + argv
try:
    runpy.run_path(target, run_name="__main__")
except SystemExit:
    pass
except BaseException as e:
    print("TOOL-ERROR:", type(e).__name__, e, file=sys.stderr)
finally:
    for p in sorted(LOG):
        print("OPENED:" + p, file=sys.stderr)
'''


def static_checks() -> list[str]:
    """No tool may hardcode ExampleData or an absolute path into the repo."""
    problems = []
    for t in TOOLS + [Path(__file__).name]:
        src = (HERE / t).read_text(encoding="utf-8")
        for lineno, line in enumerate(src.splitlines(), 1):
            if "ExampleData" in line and "check_self_contained" not in t:
                problems.append(f"{t}:{lineno}: mentions ExampleData")
            if str(REPO) in line and "check_self_contained" not in t:
                problems.append(f"{t}:{lineno}: hardcodes the repo path")
    for name in ("GE624D_pressure_calibration.csv", "L22_L10_pressure_calibration.csv"):
        if not (SKILL / "calibration" / name).exists():
            problems.append(f"calibration/{name} is missing — pressure lookup would "
                            f"have to fall back to Scripts/Probe-Calibration")
    return problems


def runtime_check(data_dir: str) -> list[str]:
    """Run each tool for real and fail on any read under ExampleData/."""
    problems = []
    with tempfile.TemporaryDirectory() as td:
        stub = Path(td) / "audit.py"
        stub.write_text(AUDIT_STUB.format(repo=str(REPO)), encoding="utf-8")

        invocations = [
            ("identify_dataset", [str(HERE / "identify_dataset.py"), data_dir]),
            ("auto_roi",         [str(HERE / "auto_roi.py"), data_dir, "--force"]),
        ]
        for name, argv in invocations:
            env = dict(os.environ, MPLBACKEND="Agg")
            r = subprocess.run([sys.executable, str(stub)] + argv,
                               capture_output=True, text=True, env=env, cwd="/")
            opened = [l[len("OPENED:"):] for l in r.stderr.splitlines()
                      if l.startswith("OPENED:")]
            bad = [p for p in opened if "/ExampleData/" in p + "/"]
            if "TOOL-ERROR:" in r.stderr:
                err = next(l for l in r.stderr.splitlines() if l.startswith("TOOL-ERROR:"))
                problems.append(f"{name}: {err}")
            if bad:
                problems.append(f"{name}: read {len(bad)} file(s) under ExampleData/, "
                                f"first = {bad[0]}")
            print(f"  {name:18s} opened {len(opened):2d} repo file(s), "
                  f"{len(bad)} under ExampleData/")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data_dir", default=None,
                    help="an acquisition folder to run the tools against "
                         "(skipped if omitted). Must NOT be inside ExampleData.")
    args = ap.parse_args()

    print("Static checks:")
    problems = static_checks()
    print(f"  {len(TOOLS)} tools scanned, calibration CSVs present, "
          f"{len(problems)} problem(s)")

    if args.data_dir:
        if "/ExampleData/" in os.path.abspath(args.data_dir):
            sys.exit("--data_dir must point outside ExampleData for this test "
                     "to mean anything.")
        print(f"\nRuntime checks against {args.data_dir}:")
        problems += runtime_check(args.data_dir)

    print()
    if problems:
        print("FAIL:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("PASS — the tools depend on nothing under ExampleData/.")


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    main()
