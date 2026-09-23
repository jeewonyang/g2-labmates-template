#!/usr/bin/env python
"""Fail if the scientific-advisor skill depends on the repo's reference folders.

`ExampleData/`, `FigureMaking/`, `Scripts/` and `Sequences/` are reference
material. This skill must never read them. `Protocols/` is read **once**, by
`index_protocols.py` with no arguments, to build the cached index; after that
every search answers from `assets/protocol_index.json`, so the agent/skill pair
works with the whole folder absent - on another machine, or in another repo.

This checker proves that functionally, not by assertion: it hides the repo by
pointing `LABSERF_ROOT` at an empty directory and re-runs the commands the
agent actually uses.

    python check_self_contained.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"
ME = Path(__file__).name

#: Folders no script may touch at all.
FORBIDDEN = ("ExampleData", "FigureMaking", "Sequences")
#: `Scripts/` is the repo's legacy code folder. Matched as a path, so the word
#: "scripts" in prose or this skill's own scripts/ directory does not trip it.
FORBIDDEN_PATHS = (re.compile(r"(?<![\w./-])Scripts/"),)

#: Documentation rather than a dependency.
PROSE = re.compile(r"^\s*(#|\*|\"\"\"|'''|\||-|>)|provenance|reference material", re.I)


def scan():
    """Executable references to the reference folders."""
    hits = []
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name == ME:  # this file necessarily names them
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if PROSE.search(line):
                continue
            bad = [d for d in FORBIDDEN if d in line]
            bad += [p.pattern for p in FORBIDDEN_PATHS if p.search(line)]
            if bad:
                hits.append((path.name, i, line.strip()))
    return hits


def run(cmd, env):
    return subprocess.run([sys.executable, *cmd], capture_output=True, text=True,
                          env=env, cwd=tempfile.gettempdir(), timeout=120)


def main():
    failures = []

    for name, line, text in scan():
        failures.append(f"{name}:{line} reaches into a reference folder: {text}")

    if not (SKILL / "assets" / "protocol_index.json").exists():
        failures.append("assets/protocol_index.json is missing — the skill cannot answer "
                        "protocol questions without the lab's folder. Run index_protocols.py once.")

    # The real test: hide the repo entirely and use the skill from elsewhere.
    with tempfile.TemporaryDirectory() as empty:
        env = dict(os.environ, LABSERF_ROOT=empty)
        checks = [
            (["--list"], "listing the indexed protocols"),
            (["--search", "PEI", "--conditions-only"], "searching the lab's protocols"),
        ]
        for argv, what in checks:
            res = run([str(SCRIPTS / "index_protocols.py"), *argv], env)
            if res.returncode != 0 or not res.stdout.strip():
                failures.append(f"{what} failed with the repo hidden:\n"
                                f"    {res.stderr.strip() or res.stdout.strip()}")

        res = run([str(SCRIPTS / "negative_results.py"), "check", "--tags", "anything"], env)
        if res.returncode != 0:
            failures.append(f"the negative-result ledger failed with the repo hidden:\n"
                            f"    {res.stderr.strip()}")
        elif "no prior failures" not in res.stdout:
            # An empty LABSERF_ROOT must yield an empty ledger, not the lab's one.
            failures.append("the ledger did not follow LABSERF_ROOT — it read a ledger "
                            "outside the root it was given.")

        # The linter must work on a file anywhere, with no repo at all.
        sample = Path(empty) / "p.md"
        sample.write_text("# t\n\n1. Spin 300 x g for 5 min [LAB: Mammalian Cell Culture.docx:12]\n", encoding="utf-8")
        res = run([str(SCRIPTS / "check_protocol.py"), str(sample)], env)
        if res.returncode != 0:
            failures.append(f"check_protocol.py failed on a standalone file:\n    {res.stdout}")

    if failures:
        print("NOT self-contained:\n")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("self-contained: no reference-folder dependencies, and searching the lab's\n"
          "protocols, the ledger and the protocol linter all work with the repo hidden.")
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
