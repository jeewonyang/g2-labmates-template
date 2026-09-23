"""Skills and jobs share one text for their rules (skill_rules.py, 2026-09-22).

Asserts every pairing is intact: the skill carries the marked block, the job's
prompt carries that block verbatim, and the block holds nothing chat-only that
a no-tools job must not see.

Run: python .claude/scripts/tests/test_skill_rules.py
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import skill_rules  # noqa: E402
import jobs as job_registry  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(label)
    print(f"{'PASS' if cond else 'FAIL'} {label}{'' if cond or not detail else '  -> ' + detail}")


# A minimal payload per kind: enough for build_prompt to render.
PAYLOADS = {
    "draft.reply": {"source": "email", "sender": "A. Person", "subject": "Hi", "body": "Can you send the data?"},
    "research.lit_review": {"title": "A paper", "authors": "X", "summary": "An abstract."},
    "admin.meeting_followup": {"title": "Lab meeting", "body": "We agreed to meet Friday."},
    "wiki.ingest": {"path": ""},
}

# Chat-only instructions a no-tools job must never be handed.
CHAT_ONLY = ("python ", ".py", "query.py", "memory_search", "mark-scanned", "outlook_email_search")


def test_every_pair_is_intact():
    registered = set(job_registry.kinds())
    for kind, (skill, name) in skill_rules.PAIRS.items():
        check(f"{kind}: kind is registered", kind in registered)
        try:
            text = skill_rules.block(skill, name)
        except skill_rules.SkillRulesError as e:
            check(f"{kind}: {skill} carries shared:{name}", False, str(e))
            continue
        check(f"{kind}: {skill} carries shared:{name}", bool(text))
        leaked = [w for w in CHAT_ONLY if w in text]
        check(f"{kind}: shared block holds no chat-only instructions", not leaked, str(leaked))
        mod = job_registry.get(kind)
        prompt = mod.build_prompt(PAYLOADS[kind])
        check(f"{kind}: job prompt carries the skill's block verbatim", text in prompt)


def test_missing_block_fails_loudly():
    try:
        skill_rules.block("draft-replies", "no-such-block")
        check("a missing block raises", False)
    except skill_rules.SkillRulesError:
        check("a missing block raises", True)


def test_slack_catchup_is_only_an_alias():
    text = (skill_rules.SKILLS_DIR / "slack-catchup" / "SKILL.md").read_text(encoding="utf-8")
    check("slack-catchup carries no rules of its own",
          "shared:" not in text and "WHEN TO DRAFT" not in text and "Mentor/PI" not in text)
    check("slack-catchup points at draft-replies", "draft-replies" in text)
    dr = (skill_rules.SKILLS_DIR / "draft-replies" / "SKILL.md").read_text(encoding="utf-8")
    check("draft-replies no longer says every DM gets a draft",
          "Every new one-to-one DM gets a draft" not in dr)


if __name__ == "__main__":
    for fn in (test_every_pair_is_intact, test_missing_block_fails_loudly,
               test_slack_catchup_is_only_an_alias):
        fn()
    total = len(PASS) + len(FAIL)
    if FAIL:
        print(f"\n{len(FAIL)} of {total} skill-rule checks FAILED.")
        sys.exit(1)
    print(f"\n{total}/{total} skill-rule checks passed.")
