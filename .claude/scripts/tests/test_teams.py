"""Tests for the team registry and the invariants the teams layer must hold.

Plain-python style, matching test_security.py / test_ledger.py - the repo has no
pytest dependency and should not grow one for this.

  python .claude/scripts/tests/test_teams.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jobs as job_registry  # noqa: E402
import teams  # noqa: E402

PASS, FAIL = [], []


def check(label: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(label)
    print(f"{'PASS' if cond else 'FAIL'} {label}"
          f"{'' if cond or not detail else f'  -> {detail}'}")


def test_manifests_load():
    ms = teams.load_all(refresh=True)
    check("manifests load", len(ms) > 0, f"found {len(ms)}")
    # A retired team (design, 2026-09-22) stays on disk disabled and owns
    # nothing, so it has nothing to produce.
    check("every enabled manifest has a producer",
          all(m.get("producer") for m in ms.values() if m.get("enabled")))
    check("a disabled manifest with no kinds is never scheduled",
          all(m["kinds"] or not m.get("enabled") for m in ms.values())
          and all(t["kinds"] for t in teams.scheduled_today(0)))


def test_validate_clean():
    problems = teams.validate()
    check("registry validates clean", not problems,
          "; ".join(problems[:3]))


def test_every_kind_owned_exactly_once():
    """A kind owned by two teams would double-count on /teams and double-run."""
    owners: dict = {}
    dupes = []
    for tid, m in teams.load_all().items():
        for k in m["kinds"]:
            if k in owners:
                dupes.append(f"{k}: {owners[k]} and {tid}")
            owners[k] = tid
    check("no kind is claimed by two teams", not dupes, "; ".join(dupes))

    registered = set(job_registry.kinds())
    orphans = sorted(registered - set(owners))
    check("every registered kind belongs to a team", not orphans,
          ", ".join(orphans))

    ghosts = sorted(set(owners) - registered)
    check("no team claims a kind with no module", not ghosts,
          ", ".join(ghosts))


def test_review_gate_holds():
    """Anything whose effect leaves VAULT/Memory/ must be review-gated.

    The Advisor-mode gate, asserted mechanically. A job kind with a real
    apply() that is NOT review-required would have its effect applied with no
    human in the loop - except apply() is only ever called for approved jobs, so
    such a kind would instead silently never run. Either way it is a bug.
    """
    offenders = []
    for k in job_registry.kinds():
        mod = job_registry.get(k)
        if getattr(mod, "REVIEW_REQUIRED", True):
            continue
        apply_fn = getattr(mod, "apply", None)
        if apply_fn is None:
            continue
        src = (apply_fn.__doc__ or "").lower()
        # Non-review kinds must have a deliberately inert apply(). Every one in
        # the repo documents that in its docstring; a new kind that forgets is
        # what this catches.
        if "no-op" not in src and "no side effect" not in src and \
           "no filesystem effect" not in src:
            offenders.append(k)
    check("non-review kinds have an inert apply()", not offenders,
          ", ".join(offenders))


def test_calendar_write_is_gated():
    """The second outbound write must be unreachable without approval."""
    mod = job_registry.get("admin.schedule_proposal")
    check("admin.schedule_proposal exists", mod is not None)
    if not mod:
        return
    check("admin.schedule_proposal is review-required",
          getattr(mod, "REVIEW_REQUIRED", False) is True)
    check("admin.schedule_proposal always needs a human when events exist",
          mod.needs_human({"should_schedule": True, "events": [{}]}) is True)
    # An empty proposal has nothing an approval could gate - apply() no-ops on
    # this exact shape - so it auto-completes instead of queueing for review
    # (the owner, 2026-09-01: only proposals that matter reach /ops).
    check("a nothing-to-schedule result skips review",
          mod.needs_human({"should_schedule": False, "events": []}) is False)
    check("should_schedule with no events skips review",
          mod.needs_human({"should_schedule": True, "events": []}) is False)
    check("a malformed result still fails toward review",
          mod.needs_human(None) is True)
    check("admin.schedule_proposal gets no tools",
          getattr(mod, "ALLOWED_TOOLS", None) == [],
          "a tool-using job could reach the network before approval")


def test_sensitivity_fails_closed():
    """A manifest with a bogus ceiling must default to private, not internal."""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "bogus.json"
        p.write_text(json.dumps({
            "id": "bogus", "name": "B", "cadence": "manual",
            "kinds": ["x.y"], "sensitivity_ceiling": "public",
        }), encoding="utf-8")
        m = teams._read_manifest(p)
    check("unknown sensitivity_ceiling falls back to private",
          m["sensitivity_ceiling"] == "private", m["sensitivity_ceiling"])


def test_producer_paths_are_repo_relative():
    """Every payload path must be REPO_ROOT-relative and must resolve.

    Regression for a bug found 2026-07-27 while widening the vault producer to
    cover G2OS-Staging. wiki_build enumerates VAULT-relative paths
    ("Memory/SOUL.md"); every ledger payload is REPO_ROOT-relative
    ("VAULT/Memory/SOUL.md"). Feeding the former into wiki.ingest had two
    effects: the job resolved the path against REPO_ROOT, found nothing, and
    reported "no extractable text" - and, more seriously,
    dispatch.derive_sensitivity() matches the literal prefixes
    "VAULT/Confidential/" and "VAULT/Research-Private/", so a VAULT-relative
    path would have walked straight past the confidentiality guard.
    """
    import producers
    from shared import REPO_ROOT

    bad_form, missing = [], []
    # Only the vault planner is pure and path-producing. Research, security,
    # and markets may query integrations or package registries; invoking them
    # from a unit test made this suite hang indefinitely when a dependency was
    # offline. Their output schemas are covered by producer-specific tests.
    for team in ("vault",):
        specs = producers.get(team).plan()
        for s in specs:
            p = (s.get("payload") or {}).get("path")
            if not p:
                continue
            if p.startswith(("Memory/", "G2OS-Staging/", "Research-Private/",
                             "Confidential/")):
                bad_form.append(f"{team}:{p}")
            elif not (REPO_ROOT / p).exists():
                missing.append(f"{team}:{p}")

    check("producer payload paths are REPO_ROOT-relative", not bad_form,
          "; ".join(bad_form[:3]))
    check("producer payload paths resolve on disk", not missing,
          "; ".join(missing[:3]))


def test_wiki_sources_exclude_generated_output():
    """The wiki must not ingest the agent's own dated output.

    The team producers write digests, pulses, and audits into Memory/ daily.
    Without these exclusions the wiki fills with one page per daily digest.
    """
    import wiki_build
    generated = ("Memory/markets/", "Memory/projects/", "Memory/security/",
                 "Memory/admin/", "Memory/research/digests/",
                 "Memory/meetings/actions/", "Memory/hr/", "Memory/design/")
    leaked = [rel for rel, _, _ in wiki_build.iter_source_files()
              if rel.startswith(generated)]
    check("wiki skips agent-generated dated output", not leaked,
          "; ".join(leaked[:3]))


def test_private_project_pulse_has_local_effect():
    """A pulse rerouted to Ollama must still create its report without tools."""
    import tempfile
    from jobs import research_project_pulse as pulse

    with tempfile.TemporaryDirectory() as temp:
        original_memory = pulse.MEMORY
        pulse.MEMORY = Path(temp)
        try:
            pulse.on_result(
                {
                    "payload": {
                        "project": "Private Project",
                        "window_days": 14,
                    },
                },
                {
                    "momentum": "steady",
                    "what_moved": ["A recent file changed."],
                    "what_did_not": [],
                    "open_questions": ["What is next?"],
                    "suggested_focus": "Review the latest evidence.",
                },
            )
            outputs = list((Path(temp) / "projects").glob("*_pulse_private-project.md"))
        finally:
            pulse.MEMORY = original_memory

    check("private project pulse writes a deterministic local report",
          len(outputs) == 1)
    check("private project pulse requires no model tools",
          pulse.ALLOWED_TOOLS == [])
    check("private project pulse has a structured schema",
          isinstance(pulse.SCHEMA, dict))


def test_research_literature_sources():
    """bioRxiv/PubMed relevance and source metadata stay deterministic."""
    from integrations import papers_integration as papers
    from jobs import research_lit_review

    queries = ["de novo protein binder design", "gas sensors", "MMP9"]
    preprint = papers.Paper(
        arxiv_id="10.1101/example",
        title="Diffusion design of de novo binders",
        authors="A. Scientist",
        summary="A protein design method for generating target-specific binders.",
        published="2026-07-28",
        url="https://doi.org/10.1101/example",
        source="biorxiv",
        journal="bioRxiv (Bioengineering)",
    )
    unrelated = papers.Paper(
        arxiv_id="123",
        title="Migration of shorebirds",
        authors="B. Scientist",
        summary="A field ecology study.",
        published="2026-07-28",
        url="https://pubmed.ncbi.nlm.nih.gov/123/",
        source="pubmed",
        journal="Nature",
    )
    check("bioRxiv paper matches the project watchlist",
          bool(papers._matched_queries(preprint, queries)))
    check("unrelated CNS paper is filtered out",
          not papers._matched_queries(unrelated, queries))
    gas_only = papers.Paper(
        arxiv_id="456",
        title="Tritium separation from gaseous mixtures",
        authors="C. Scientist",
        summary="A method for separating gas isotopologues.",
        published="2026-07-28",
        url="https://pubmed.ncbi.nlm.nih.gov/456/",
        source="pubmed",
        journal="Nature Communications",
    )
    check("single generic word cannot satisfy a multi-word query",
          not papers._matched_queries(gas_only, ["gas sensors"]))

    prompt = research_lit_review.build_prompt({
        "paper_id": preprint.arxiv_id,
        "source": preprint.source,
        "journal": preprint.journal,
        "title": preprint.title,
        "authors": preprint.authors,
        "url": preprint.url,
        "summary": preprint.summary,
        "matched_queries": "de novo protein binder design",
    })
    # Match on collapsed whitespace: the PAPER block pads its labels into a
    # column ("source:  biorxiv"), and asserting one exact space made this test
    # fail over cosmetic alignment while the metadata was present all along.
    flat = " ".join(prompt.split())
    check("lit-review prompt preserves non-arXiv source metadata",
          "source: biorxiv" in flat and
          "journal: bioRxiv (Bioengineering)" in flat)


def main() -> int:
    for fn in (test_manifests_load, test_validate_clean,
               test_every_kind_owned_exactly_once, test_review_gate_holds,
               test_calendar_write_is_gated, test_sensitivity_fails_closed,
               test_producer_paths_are_repo_relative,
               test_wiki_sources_exclude_generated_output,
               test_private_project_pulse_has_local_effect,
               test_research_literature_sources):
        fn()
    total = len(PASS) + len(FAIL)
    print(f"\n{len(PASS)}/{total} team tests passed."
          if not FAIL else
          f"\n{len(FAIL)} of {total} team tests FAILED.")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
