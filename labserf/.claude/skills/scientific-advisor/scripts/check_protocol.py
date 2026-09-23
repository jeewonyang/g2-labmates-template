#!/usr/bin/env python
"""Enforce "flag and cite" on a generated protocol.

A protocol is only runnable if every number in it came from somewhere. This
linter reads a generated protocol markdown file and fails if any line that
states an experimental condition - a concentration, volume, temperature, time,
speed, voltage or pH - carries no source tag.

Every such line must end with exactly one of:

    [LAB: <file>:<line>]        this lab's own protocol, from the protocol index
    [CITE: <n>]                 a numbered reference in the REFERENCES block
    [PRIOR: <NR-id>]            a prior run / the negative-result ledger
    [DERIVED: <value> from <x>] computed from sourced values - show the arithmetic
    [FLAG: <what is missing>]   NOT KNOWN - the user must supply it
    [ASSUME: <basis>]           a stated standard practice, deliberately not cited
    [RECAP: <where>]            restates a value already sourced above; not a new claim

`[FLAG: ...]` lines are the point of the exercise: an omitted buffer condition
must appear as an explicit hole, never as a plausible invented number. The
linter reports them as a summary, not an error - a protocol with flags is
honest. A protocol with a bare number is not.

    python check_protocol.py PROTOCOL.md
    python check_protocol.py PROTOCOL.md --strict   # also fail on ASSUME
"""
import argparse
import re
import sys
from pathlib import Path

# A tag body may itself contain a bracketed reference — a flag often needs to
# say "source A gives 5 mM [2], source B omits it", and one of this lab's own
# protocol filenames contains brackets — so allow one nesting level.
TAG_RE = re.compile(
    r"\[(LAB|CITE|PRIOR|FLAG|ASSUME|DERIVED|RECAP):\s*((?:[^\[\]]|\[[^\[\]]*\])*)\]")

# A line stating an experimental condition: a number bound to a unit, or a pH.
# Bare single-letter units (`s`, `g`, `C`) are deliberately absent — under
# IGNORECASE they fire on ordinary prose, and the noise teaches people to paste
# tags onto things that are not claims, which devalues every tag in the file.
# `g` is still caught in its real form, `300 x g`.
CONDITION_RE = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?\s*"
    r"(?:%|mM|µM|uM|nM|pM|\bM\b|mg/mL|mg/ml|µg/mL|ug/mL|ng/µL|ng/uL|mg\b|µg\b|ug\b|ng\b"
    r"|mL\b|ml\b|µL\b|uL\b|\bL\b|°C|º ?C|rpm|×\s*g\b|x\s*g\b"
    r"|min\b|mins\b|hr\b|hrs\b|hours?\b|\bh\b|sec\b|days?\b|kDa|U/µL|U/uL"
    r"|\bV\b|mA|MHz|kHz|Hz|cm\b|mm\b|µm\b|um\b|nm\b)"
    r"|pH\s*\d",
    re.IGNORECASE,
)

# Lines that legitimately hold numbers without being a condition.
#
# Table rows are NOT exempt. The protocol format mandates that Materials be a
# pipe table with a Source column, so exempting `|` lines would leave the one
# section most likely to carry an invented concentration unchecked — the
# coverage would be inverted relative to the risk. Header and separator rows
# carry no number+unit and fall out on their own.
EXEMPT_RE = re.compile(
    r"^\s*(#|```|\[\d+\]|REFERENCES|-{3,}|\|[\s\-:|]*\|?\s*$)"       # headings, refs, rules
    r"|^\s*(?:step\s*)?\d+[.)]\s*$"                                   # bare step numbers
    r"|https?://",
    re.IGNORECASE,
)


def lint(path, strict=False):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    problems, flags, assumptions, derived, cited = [], [], [], [], 0
    in_references = False
    in_code = False

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if re.match(r"^#+\s*references", stripped, re.IGNORECASE) or stripped == "REFERENCES":
            in_references = True
        if in_references or in_code or not stripped:
            continue
        # Flags and assumptions count wherever they appear — a hole worth
        # flagging often has no number in it precisely because the number is
        # the thing that is missing.
        tags = TAG_RE.findall(stripped)
        for kind, body in tags:
            if kind == "FLAG":
                flags.append((i, body.strip()))
            elif kind == "ASSUME":
                assumptions.append((i, body.strip()))
                if strict:
                    problems.append((i, f"ASSUME not allowed in --strict: {stripped}"))
            elif kind == "DERIVED":
                derived.append((i, body.strip()))
                # "Derived" without saying from what is just an assertion.
                if not re.search(r"from\s+\S", body, re.IGNORECASE):
                    problems.append(
                        (i, f"DERIVED must say what it was computed from: {stripped[:120]}"))

        if EXEMPT_RE.search(stripped) or not CONDITION_RE.search(stripped):
            continue
        if not tags:
            problems.append((i, stripped))
            continue
        cited += sum(1 for kind, _ in tags if kind in ("LAB", "CITE", "PRIOR", "DERIVED"))

    print(f"{path}: {cited} sourced condition(s), {len(flags)} flagged, "
          f"{len(derived)} derived, {len(assumptions)} assumed, {len(problems)} unsourced")

    if flags:
        print("\nFLAGGED — the user must supply these before the protocol is runnable:")
        for i, body in flags:
            print(f"  line {i}: {body}")
    if derived:
        print("\nDERIVED — computed from sourced values; check the arithmetic:")
        for i, body in derived:
            print(f"  line {i}: {body}")
    if assumptions:
        print("\nASSUMED — standard practice, stated rather than cited:")
        for i, body in assumptions:
            print(f"  line {i}: {body}")
    if problems:
        print("\nUNSOURCED CONDITIONS — every one of these is a potential hallucination:")
        for i, text in problems:
            print(f"  line {i}: {text[:150]}")
        print("\nTag each with [LAB: file:line], [CITE: n], [PRIOR: NR-id],\n"
              "[DERIVED: value from x], [ASSUME: basis], [RECAP: where it was sourced above],\n"
              "or — if the source is genuinely unknown — [FLAG: what is missing].")
        return 1
    print("\nOK — every condition in this protocol is sourced or explicitly flagged.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("protocol", type=Path)
    ap.add_argument("--strict", action="store_true", help="also reject [ASSUME: ...]")
    args = ap.parse_args()
    if not args.protocol.exists():
        sys.exit(f"no such file: {args.protocol}")
    return lint(args.protocol, args.strict)


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    sys.exit(main())
