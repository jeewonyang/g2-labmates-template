# The protocol contract

A generated protocol has one job: **someone can run it tomorrow without
guessing, and every number in it can be traced to where it came from.** A
plausible-looking buffer recipe with no source is worse than a blank — the
blank gets asked about, the invented number gets used.

## Source tags

Every line that states a condition — concentration, volume, temperature, time,
speed, voltage, pH, ratio — carries at least one tag. More than one is correct
when a line needs it: a lab number corroborated by a paper takes both.

| Tag | Means | Use when |
|---|---|---|
| `[LAB: <file>:<line>]` | This lab's own protocol | Always preferred. `index_protocols.py --search` gives the file and line. |
| `[CITE: <n>]` | Reference *n* in the REFERENCES block | Read from a paper's `content.lines`; the reference URL carries `#L<n>`. |
| `[PRIOR: <NR-id>]` | A prior run or ledger entry | A parameter chosen because of what happened before. |
| `[ASSUME: <basis>]` | Standard practice, stated not cited | Genuinely universal (`spin 300 x g to pellet mammalian cells`). Use sparingly — every `ASSUME` is a small unverified claim. |
| `[DERIVED: <value> from <inputs>]` | Computed from sourced values | Scaling a 10 cm recipe to a 6-well. Show the factor; the linter rejects a `DERIVED` that does not say what it came from. Tag the inputs too. |
| `[RECAP: <where sourced>]` | Restates a value sourced above | Timeline rows and summary sentences that repeat a number from the Procedure. Not a new claim, so it needs no new source — but it must point at where the number was sourced. |
| `[FLAG: <what is missing>]` | **Not known** | The source omits it, sources disagree, or it depends on the lab's stock. Say precisely what is missing and what it depends on. |

**Never** write a number you cannot tag. If the methods section you are working
from says "washed in buffer" without saying which, that is
`[FLAG: wash buffer composition not stated in the source — confirm with lab]`,
not `25 mM Tris, 150 mM NaCl`.

Check it mechanically before handing it over:

```bash
python .claude/skills/scientific-advisor/scripts/check_protocol.py <protocol.md>
```

Exit code 1 means an untagged condition slipped in. Fix it; do not describe the
protocol as ready while the linter fails.

## Structure

```markdown
# <Protocol title>

**Purpose.** One sentence: the question this experiment answers.
**Status.** Draft generated <date>. <N> conditions flagged — see "Before you run this".
**Sources.** Lab protocols used, papers used, prior runs used.

## Before you run this
The flagged holes, gathered in one place, each with what it depends on and the
cheapest way to resolve it. A reader decides here whether the protocol is
runnable today.

## Materials
Reagent | Supplier / cat. | Stock | Final | Source
Every row tagged — the linter checks table rows, because a table is exactly
where an invented concentration hides. Note what the lab already has (from the protocol index) versus
what must be ordered.

## Equipment and settings
Instrument, probe, objective, cytometer channels, acquisition parameters. For
ultrasound, state probe, mode, voltage/pressure and depth; for flow, state the
channels and the negative control.

## Timeline
Day -1 / Day 0 / Day 1 ... so the reader can see whether it fits their week.

## Procedure
Numbered steps. One action per step. Every condition tagged. Where a step has a
known failure mode, say it inline in one clause — not in a separate section the
reader will skip.

## Controls
Named explicitly, each with what it rules out. A protocol without a positive
control and a no-manipulation control is not finished. State the negative
control the downstream analysis needs by name (flow thresholds and blank
correction both depend on it).

## Readout and analysis
The metric, how it is computed, and the n. If LabSerf will process it, name the
pipeline and the folder layout it expects, so the data lands analyzable.

## What this experiment cannot show
The bounds. Written before the experiment, not after.

--------
REFERENCES
[1] ...
```

## Rules that keep it runnable

**Prefer the lab's own protocol to the paper's.** If `Protocols/` already has a
transfection or purification procedure, build on it and cite it — the lab's
reagents, cells and instruments are what will actually be used. Cite the paper
for what the lab's protocol does not cover.

**When sources disagree, show both.** Two papers with different induction times
is a real finding about the field, not something to average. Give both, tagged,
and say which you would run and why.

**Scale arithmetic must be shown, and tagged `[DERIVED: ...]`.** If you convert
a 10 cm dish recipe to a 96-well, show the factor and cite the input value.
Unshown arithmetic is indistinguishable from an invented number, and a derived
number tagged `[LAB: ...]` overclaims — the lab never stated it.

**Name the decision points.** Where the protocol branches on a result
("if OD500 < 0.3, do not proceed to dialysis"), write the threshold and the
branch.

**Tie it back to the ledger.** Before writing, run
`negative_results.py check` on the topic. If a prior attempt failed, the new
protocol either fixes the stated cause or explains why it does not apply — say
which, in the Purpose section, tagged `[PRIOR: NR-xxxx]`.
