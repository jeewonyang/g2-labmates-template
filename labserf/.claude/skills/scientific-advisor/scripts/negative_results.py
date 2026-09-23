#!/usr/bin/env python
"""The lab's negative-result memory.

Negative and null results are the most expensive knowledge the lab produces and
the first thing forgotten. This ledger keeps them so that planning the next
experiment, and discussing an idea months later, starts from what has already
failed and *why*.

The ledger lives at `LabMemory/negative_results.jsonl` in the repo — one JSON
object per line, human-readable and hand-editable. `render` rewrites
`LabMemory/NEGATIVE_RESULTS.md` from it.

    # before planning or proposing anything
    python negative_results.py check --tags mARG,HEK293T --query "doxycycline induction"

    # after an analysis that produced a null / failed result
    python negative_results.py add \
        --title "No xAM signal from mARG HEK cells at 3 V" \
        --assay ultrasound --system "HEK293T mARG clone 4" \
        --question "Does clone 4 make detectable GVs after 72 h dox?" \
        --tried "72 h 1 ug/mL dox, L22-14vX xAM, 3 V, 96-well plate" \
        --outcome below-detection \
        --observation "well means within 1.2 dB of blank; n=3" \
        --why "voltage may be under collapse threshold; clone may be silenced" \
        --confound "no positive-control well on the plate" \
        --next "repeat with purified-GV positive control and a 3-10 V ramp" \
        --run /path/to/run --source /path/to/run/AI_analysis/RESULTS.md

`outcome` is the field that matters most, and it is deliberately not free text:

  no-effect          the manipulation did nothing, and the assay was working
  below-detection    real effect possible but under the assay's floor
  technical-failure  the assay itself failed - says nothing about the biology
  did-not-express    construct/protein never made it - upstream of the question
  inconclusive       underpowered, confounded, or uninterpretable

Only `no-effect` is evidence about the biology. Everything else is evidence
about the experiment, and conflating the two is how a real effect gets
abandoned - which is exactly what this ledger exists to prevent.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent


def find_repo():
    """The repo root, without assuming where this skill is nested.

    `$LABSERF_ROOT`, else the nearest ancestor of the skill or the working
    directory that holds a `.claude/`, else the working directory. The ledger
    belongs to the repo, not to the skill, so it survives reinstalling the
    skill and is visible to anyone browsing the lab's files.
    """
    import os

    env = os.environ.get("LABSERF_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    for start in (SKILL, Path.cwd().resolve()):
        for candidate in (start, *start.parents):
            if (candidate / ".claude").is_dir() and candidate.name != ".claude":
                return candidate
    return Path.cwd().resolve()


REPO = find_repo()
LEDGER = REPO / "LabMemory" / "negative_results.jsonl"
RENDERED = REPO / "LabMemory" / "NEGATIVE_RESULTS.md"

OUTCOMES = {
    "no-effect": "manipulation did nothing; assay was working",
    "below-detection": "possible effect under the assay's floor",
    "technical-failure": "the assay failed; says nothing about the biology",
    "did-not-express": "construct/protein never made it",
    "inconclusive": "underpowered, confounded or uninterpretable",
}
# Outcomes that are evidence about biology rather than about the experiment.
BIOLOGICAL = {"no-effect", "below-detection"}


def read(ledger=LEDGER):
    if not ledger.exists():
        return []
    out = []
    for i, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"warning: {ledger}:{i} is not valid JSON ({exc}); skipped", file=sys.stderr)
    return out


def write_all(entries, ledger=LEDGER):
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")


def next_id(entries):
    n = 0
    for e in entries:
        try:
            n = max(n, int(str(e.get("id", "NR-0")).split("-")[-1]))
        except ValueError:
            pass
    return f"NR-{n + 1:04d}"


def cmd_add(args):
    entries = read(args.ledger)
    entry = {
        "id": next_id(entries),
        "date": args.date or date.today().isoformat(),
        "title": args.title,
        "assay": args.assay,
        "system": args.system,
        "question": args.question,
        "tried": args.tried,
        "outcome": args.outcome,
        "observation": args.observation,
        "why": args.why,
        "confounds": args.confound,
        "next": args.next,
        "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()],
        "run": args.run,
        "source": args.source,
        "resolved": None,
    }
    # Tags carry the retrieval burden; seed them from the structured fields.
    for extra in (args.assay, args.system):
        if extra and extra not in entry["tags"]:
            entry["tags"].append(extra)
    entries.append(entry)
    write_all(entries, args.ledger)
    render(args.ledger, args.rendered)
    print(f"{entry['id']} recorded in {args.ledger}")
    if entry["outcome"] not in BIOLOGICAL:
        print(f"note: outcome '{entry['outcome']}' is evidence about the experiment, "
              f"not about the biology — the question is still open.")
    return 0


def matches(entry, tags, query):
    hay = " ".join(str(v) for v in entry.values() if isinstance(v, str)).lower()
    hay += " " + " ".join(entry.get("tags", [])).lower()
    if query and query.lower() not in hay:
        return False
    if tags and not any(t.lower() in hay for t in tags):
        return False
    return True


def fmt(entry, verbose=True):
    head = (f"{entry['id']}  [{entry.get('outcome', '?')}]  {entry.get('date', '')}  "
            f"{entry.get('title', '')}")
    if not verbose:
        return head
    lines = [head]
    for key, label in (("system", "system"), ("question", "question"), ("tried", "tried"),
                       ("observation", "observed"), ("why", "why it may have failed"),
                       ("confounds", "confounds"), ("next", "suggested next"),
                       ("source", "source"), ("resolved", "resolved by")):
        val = entry.get(key)
        if val:
            lines.append(f"    {label}: {val}")
    return "\n".join(lines)


def cmd_check(args):
    """The pre-flight query: what has already failed near this idea?"""
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    hits = [e for e in read(args.ledger) if matches(e, tags, args.query) and not e.get("resolved")]
    if not hits:
        print("negative-result ledger: no prior failures recorded near this idea.")
        return 0
    bio = [e for e in hits if e.get("outcome") in BIOLOGICAL]
    tech = [e for e in hits if e.get("outcome") not in BIOLOGICAL]
    print(f"negative-result ledger: {len(hits)} related prior failure(s).\n")
    if bio:
        print("Evidence about the biology — do not simply repeat these:")
        for e in bio:
            print(fmt(e))
        print()
    if tech:
        print("Failed for experimental reasons — the underlying question is still open,")
        print("but repeating without fixing the stated cause will fail the same way:")
        for e in tech:
            print(fmt(e))
    return 0


def cmd_list(args):
    entries = read(args.ledger)
    if args.outcome:
        entries = [e for e in entries if e.get("outcome") == args.outcome]
    for e in entries:
        print(fmt(e, verbose=args.verbose))
    if not entries:
        print("ledger is empty")
    return 0


def cmd_resolve(args):
    entries = read(args.ledger)
    for e in entries:
        if e.get("id") == args.id:
            e["resolved"] = args.note
            write_all(entries, args.ledger)
            render(args.ledger, args.rendered)
            print(f"{args.id} marked resolved: {args.note}")
            return 0
    sys.exit(f"no entry with id {args.id}")


def render(ledger=LEDGER, out=RENDERED):
    entries = read(ledger)
    lines = [
        "# Negative-result memory",
        "",
        "Auto-generated from `negative_results.jsonl` by",
        "`.claude/skills/scientific-advisor/scripts/negative_results.py render`.",
        "Edit the JSONL, not this file.",
        "",
        "`no-effect` and `below-detection` are evidence about the biology.",
        "The other outcomes are evidence about the experiment: those questions are still open.",
        "",
    ]
    if not entries:
        lines += ["_No entries yet._", ""]
    for outcome in list(OUTCOMES):
        group = [e for e in entries if e.get("outcome") == outcome]
        if not group:
            continue
        lines += [f"## {outcome} — {OUTCOMES[outcome]}", ""]
        for e in group:
            flag = " ✅ resolved" if e.get("resolved") else ""
            lines += [f"### {e['id']} · {e.get('title', '')}{flag}", ""]
            for key, label in (("date", "Date"), ("system", "System"), ("question", "Question"),
                               ("tried", "Tried"), ("observation", "Observed"),
                               ("why", "Why it may have failed"), ("confounds", "Confounds"),
                               ("next", "Suggested next"), ("run", "Run"),
                               ("source", "Source"), ("resolved", "Resolved by")):
                if e.get(key):
                    lines.append(f"- **{label}:** {e[key]}")
            if e.get("tags"):
                lines.append(f"- **Tags:** {', '.join(e['tags'])}")
            lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument("--rendered", type=Path, default=RENDERED)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="record a negative / null / failed result")
    a.add_argument("--title", required=True)
    a.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    a.add_argument("--assay", default="")
    a.add_argument("--system", default="")
    a.add_argument("--question", default="")
    a.add_argument("--tried", default="", help="the actual conditions, specific enough to repeat")
    a.add_argument("--observation", default="", help="the numbers, with n")
    a.add_argument("--why", default="", help="hypotheses for the failure")
    a.add_argument("--confound", default="")
    a.add_argument("--next", default="")
    a.add_argument("--tags", default="")
    a.add_argument("--run", default="")
    a.add_argument("--source", default="", help="path to the RESULTS.md this came from")
    a.add_argument("--date", default="")
    a.set_defaults(func=cmd_add)

    c = sub.add_parser("check", help="what has already failed near this idea?")
    c.add_argument("--tags", default="")
    c.add_argument("--query", default="")
    c.set_defaults(func=cmd_check)

    l = sub.add_parser("list")
    l.add_argument("--outcome", choices=sorted(OUTCOMES))
    l.add_argument("-v", "--verbose", action="store_true")
    l.set_defaults(func=cmd_list)

    r = sub.add_parser("resolve", help="a later experiment explained or overturned this")
    r.add_argument("id")
    r.add_argument("note")
    r.set_defaults(func=cmd_resolve)

    rd = sub.add_parser("render", help="rewrite NEGATIVE_RESULTS.md from the ledger")
    rd.set_defaults(func=lambda args: (print(render(args.ledger, args.rendered)), 0)[1])

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
