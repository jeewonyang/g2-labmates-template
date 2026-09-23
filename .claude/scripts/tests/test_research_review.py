"""Focused contract tests for Rho's on-demand review path."""

import json
import re
import sys
from contextlib import nullcontext
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "jobs"))
sys.path.insert(0, str(SCRIPTS / "integrations"))

import research_review  # noqa: E402
import research_lit_review  # noqa: E402
import papers_integration  # noqa: E402


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def render(tmp, result, title="A paper"):
    """Run on_result into a temp dir and return the digest markdown."""
    original_dir, original_memory = research_lit_review.digest_dir, research_lit_review.MEMORY
    research_lit_review.digest_dir = lambda: tmp
    research_lit_review.MEMORY = tmp.parent
    try:
        research_lit_review.on_result({"payload": {"title": title}, "job": "j"}, dict(result))
    finally:
        research_lit_review.digest_dir = original_dir
        research_lit_review.MEMORY = original_memory
    return next(tmp.glob("*.md")).read_text(encoding="utf-8")


def check_template(tmp_root):
    """The rendered shapes /vault and executive-digest.ts both depend on."""
    base = {"verdict": "One sentence.", "next_action": "Do the thing.",
            "evidence_scope": "abstract-only"}

    full = render(tmp_root / "full", {
        **base, "relevance": "high",
        "problem": "P", "approach": "A", "key_result": "K",
        "methodological_advance": "M", "real_world_implications": "R",
        "relevance_to_user": "U", "caveats": "C",
    })
    check("full form groups fields under three H2 sections",
          all(f"\n## {h}" in full
              for h in ("What the paper did", "Why it matters", "Limits and evidence")))
    check("full form demotes canonical fields to H3",
          "\n### Key Result" in full and "\n### Relevance To Your Interests" in full)
    check("the verdict is the first blockquote, labelled with the action",
          full.index("> **VERDICT — HIGH RELEVANCE · READ**") < full.index("## What the paper did"))
    check("full form declares its format in frontmatter", "review_format: full" in full)
    check("exactly one horizontal rule closes the document header",
          full.count("\n---\n") == 2)  # frontmatter close + header boundary

    screened = render(tmp_root / "screened", {
        **base, "relevance": "low",
        "screen_contribution": "X", "screen_why_low": "Y", "screen_possible_use": "None identified.",
        # A screened digest must ignore full-form content even if it arrives.
        "problem": "should not appear", "key_result": "should not appear",
    })
    check("low relevance yields the screened form",
          "## Screening note" in screened and "review_format: screened" in screened)
    check("screened form drops the seven canonical sections",
          "### Key Result" not in screened and "should not appear" not in screened)
    check("screened form still carries the verdict and next action",
          "· SKIP**" in screened and "**Next action:**" in screened)

    thin = render(tmp_root / "thin", {
        **base, "relevance": "medium", "problem": "P",
        "approach": None, "key_result": "INSUFFICIENT INFORMATION - nothing in the abstract",
        "methodological_advance": None, "real_world_implications": None,
        "relevance_to_user": "U",
    })
    check("unsupported fields are omitted, not stubbed",
          "### Approach" not in thin and "INSUFFICIENT INFORMATION" not in thin)
    check("omissions collapse into one evidence-gap note",
          thin.count("> **EVIDENCE GAP**") == 1)
    check("the gap note names what was missing",
          "approach" in thin.split("EVIDENCE GAP")[1]
          and "key result" in thin.split("EVIDENCE GAP")[1])


def main():
    malformed = {
        "title": "Valid " + chr(0x1F9EC),
        "abstract": "Broken \ud83d text",
        "nested": ["paired \ud83d\ude00", "caf" + chr(0xE9)],
    }
    serialized = research_review._json_text(malformed)
    repaired = json.loads(serialized)
    check("malformed feed Unicode remains UTF-8 writable",
          bool(serialized.encode("utf-8")))
    check("lone surrogates become one replacement character",
          repaired["abstract"] == "Broken \ufffd text")
    check("valid emoji and non-ASCII text remain intact",
          repaired["title"].endswith(chr(0x1F9EC)) and
          repaired["nested"] == ["paired " + chr(0x1F600), "caf" + chr(0xE9)])
    check("Unicode repair is idempotent",
          research_review._unicode_safe(repaired) == repaired)

    check(
        "DOI URLs normalize to a stable lowercase identity",
        research_review.normalize_doi("https://doi.org/10.1101/ABC.123") ==
        "10.1101/abc.123",
    )
    check(
        "tracking parameters do not create duplicate URL identities",
        research_review.canonical_url(
            "https://example.org/paper/?utm_source=rho&id=7#results"
        ) == "https://example.org/paper?id=7",
    )

    events = [
        {
            "event": "paper_selected",
            "item_id": "paper-1",
            "identifiers": {"doi": "10.1101/x"},
            "metadata": {"title": "A method"},
        },
        {
            "event": "project_assigned",
            "item_id": "paper-1",
            "project_id": "project-1",
            "project_title": "Example Project",
        },
        {
            "event": "resource_assigned",
            "item_id": "paper-1",
            "resource_id": "resource-1",
            "resource_title": "Example methods",
        },
        {
            "event": "review_completed",
            "item_id": "paper-1",
            "job_id": "job-1",
            "digest_path": "research/digests/a-method.md",
        },
    ]
    folded = research_review.fold_events(events)["paper-1"]
    check("append-only events rebuild project assignment",
          folded["projects"]["project-1"] == "Example Project")
    check("append-only events rebuild resource assignment",
          folded["resources"]["resource-1"] == "Example methods")
    check("append-only events rebuild digest linkage",
          folded["digest_path"] == "research/digests/a-method.md")
    reclassified = research_review.fold_events(events + [{
        "event": "paper_reclassified",
        "item_id": "paper-1",
        "target_type": "area",
        "target_id": "area-brainstorming",
        "target_title": "Brainstorming",
    }])["paper-1"]
    check("reclassification replaces earlier targets append-only",
          not reclassified["projects"] and
          not reclassified["resources"] and
          reclassified["areas"]["area-brainstorming"] == "Brainstorming")
    archived = research_review.fold_events(events + [{
        "event": "paper_archived",
        "item_id": "paper-1",
    }])["paper-1"]
    restored = research_review.fold_events(events + [
        {"event": "paper_archived", "item_id": "paper-1"},
        {"event": "paper_restored", "item_id": "paper-1"},
    ])["paper-1"]
    check("bibliography deletion folds as a reversible archive",
          archived["archived"] and not restored["archived"])
    emitted = []
    original_read_events = research_review._read_events
    original_append_event = research_review._append_event_unlocked
    original_file_lock = research_review.file_lock
    try:
        research_review._read_events = lambda: events
        research_review._append_event_unlocked = emitted.append
        research_review.file_lock = lambda _: nullcontext()
        archive_result = research_review.archive_item({"itemId": "paper-1"})
        move_result = research_review.reclassify_item({
            "itemId": "paper-1",
            "targetType": "area",
            "targetId": "area-brainstorming",
            "targetTitle": "Brainstorming",
        })
    finally:
        research_review._read_events = original_read_events
        research_review._append_event_unlocked = original_append_event
        research_review.file_lock = original_file_lock
    check("archive command appends rather than deleting",
          archive_result["archived"] and
          emitted[0]["event"] == "paper_archived")
    check("reclassify command appends a replacement target",
          move_result["targetType"] == "area" and
          emitted[1]["event"] == "paper_reclassified")

    # Schema contract (review_schema 3). The three review lenses are no longer
    # schema-required: a low-relevance paper gets the screened form and must
    # NOT fill them, and a field the source cannot support is omitted rather
    # than stuffed with "INSUFFICIENT INFORMATION". What replaced them as the
    # always-required floor is the verdict - the one line they are guaranteed to
    # read - plus what to do about it and how much of the paper was seen.
    required = set(research_lit_review.SCHEMA["required"])
    properties = set(research_lit_review.SCHEMA["properties"])
    lenses = {
        "methodological_advance",
        "real_world_implications",
        "relevance_to_user",
    }
    check("verdict, next action and evidence scope are schema-required",
          {"relevance", "verdict", "next_action", "evidence_scope"} <= required)
    check("all three review lenses remain part of the full form", lenses <= properties)
    check("review lenses are optional so a screened digest can omit them",
          not (lenses & required))
    check("the screened form has its own three fields",
          {"screen_contribution", "screen_why_low", "screen_possible_use"} <= properties)
    check("unsupported evidence has one consolidated home",
          "evidence_gap" in properties)

    prompt = research_lit_review.build_prompt({
        "title": "Synthetic paper",
        "summary": "A synthetic abstract for contract testing.",
        "target_type": "resource",
        "target_title": "Example methods",
    })
    check("prompt requires methodological advance", "methodological_advance" in prompt)
    check("prompt requires real-world implications", "real_world_implications" in prompt)
    check("prompt requires relevance to the user", "relevance_to_user" in prompt)
    check("prompt names the selected project or resource",
          'selected resource "Example methods"' in prompt)
    # The old rule was "label a thin abstract INSUFFICIENT INFORMATION". The
    # rule now is "leave the field null and account for it once in
    # evidence_gap" - but the prohibition on guessing is the part that matters
    # and it must survive verbatim.
    check("thin sources are declared, not guessed",
          "evidence_gap" in prompt and "never a guess" in prompt)
    check("per-section INSUFFICIENT INFORMATION is explicitly forbidden",
          'Do NOT write "INSUFFICIENT INFORMATION"' in prompt)
    check("the relevance gate is stated in the prompt",
          "SCREENED" in prompt and "FULL" in prompt)

    requested = []
    original_fetch = papers_integration._fetch_json
    try:
        papers_integration._fetch_json = lambda url, **_: (
            requested.append(url) or {"collection": []}
        )
        papers_integration.search_biorxiv(days=7, max_records=30)
    finally:
        papers_integration._fetch_json = original_fetch
    check("bioRxiv scanning uses the live API's explicit ISO-date interval",
          bool(requested) and "/7d/" not in requested[0] and
          bool(re.search(
              r"/\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}/0$", requested[0]
          )))

    with tempfile.TemporaryDirectory() as tmp:
        check_template(Path(tmp))


if __name__ == "__main__":
    main()
