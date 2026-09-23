"""A cloud reasoning model reviews a batch of Ollama classifications.

The second tier is independent of qwen3:8b. Codex is the default because its
structured-output runtime is reliable unattended; Claude remains a supported
runtime and uses Opus when selected.

SANITIZED DECISION DATA ONLY. The payload carries a filename, coarse source
zone, proposed destination, confidence, and the local model's stated reason.
It carries neither source paths nor document text. A local deterministic
preflight removes credential material and oversized/raw archive data before a
review job is created.

Batched: one call reviews ~25 proposals. Reviewing 500 individually would be
500 Opus calls for a task that is mostly pattern-checking a table.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

KIND = "triage.review"
DEFAULT_RUNTIME = "codex"
SENSITIVITY = "internal"        # metadata only - see the module docstring
REVIEW_REQUIRED = False         # the verdicts ARE the output; no second gate
TIMEOUT = 900
MODEL = None                    # each runtime uses its configured reasoning model
ALLOWED_TOOLS = []              # pure reasoning over the supplied table

BATCH_SIZE = 25

VAULTS = {
    "G2OS-Staging": ["10_Projects", "20_Areas", "30_Resources", "90_Archive"],
    "Research-Private": ["10_Projects", "20_Areas", "30_Resources", "90_Archive"],
    "Confidential": ["20_Areas", "40_People", "90_Archive"],
    "Finance": ["20_Areas", "30_Resources", "90_Archive"],
}
# Seed project folders - replace with your own 10_Projects folder names
# (keep this list in sync with jobs/triage_classify.py).
PROJECTS = ["00_Example-Project"]

SCHEMA = {
    "type": "object",
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "job", "verdict", "vault", "bucket", "project",
                    "folder", "folder_mode", "note", "actions_verdict",
                ],
                "properties": {
                    "job": {"type": "string"},
                    "verdict": {"type": "string",
                                "enum": ["confirm", "correct", "uncertain"]},
                    "vault": {"type": "string",
                              "enum": list(VAULTS) + ["leave-in-inbox"]},
                    "bucket": {"type": "string",
                               "enum": sorted({b for v in VAULTS.values() for b in v}
                                              | {"none"})},
                    "project": {"type": ["string", "null"]},
                    "folder": {"type": ["string", "null"]},
                    "folder_mode": {
                        "type": "string",
                        "enum": ["bucket-root", "existing", "create"],
                    },
                    "note": {"type": "string"},
                    "actions_verdict": {
                        "type": "string",
                        "enum": ["confirm", "uncertain", "not_applicable"],
                    },
                },
            },
        },
    },
}


def build_prompt(payload) -> str:
    items = (payload or {}).get("items", [])
    lines = []
    for it in items:
        action_text = "; ".join(
            f"{a.get('kind')}: {a.get('title')} "
            f"(due {a.get('due_date') or '-'}, scheduled "
            f"{a.get('scheduled_date') or '-'}, confidence "
            f"{a.get('confidence')})"
            for a in (it.get("actions") or [])[:10]
            if isinstance(a, dict)
        ) or "(none)"
        lines.append(
            f"- job: {it['job']}\n"
            f"  file: {it['name']}\n"
            f"  source zone: {it.get('source_zone', 'inbox')}\n"
            f"  proposed: {it['vault']}/{it['bucket']}"
            f"{'/' + str(it.get('folder')) if it.get('folder') else ''}"
            f"  [folder mode: {it.get('folder_mode') or 'legacy'};"
            f" folder state: {it.get('folder_state') or 'unknown'};"
            f" reclassification pass: {it.get('reclassification_pass', 0)}]"
            f"  (confidence {it.get('confidence')})\n"
            f"  folder rationale: {it.get('folder_rationale', '')[:200]}\n"
            f"  local model's reason: {it.get('reason', '')[:200]}\n"
            f"  proposed dashboard actions: {action_text}"
        )
    table = "\n".join(lines)

    # Aggregate correction tendencies only - the sanitization contract in the
    # module docstring holds: no titles, paths, or content reach this prompt.
    try:
        from triage import lessons
        tendencies = lessons.review_block()
    except Exception:  # noqa: BLE001 - advisory, never blocking
        tendencies = ""

    return f"""You are auditing a local model's file-classification decisions for
the owner's vault. Their role, field, and key people are described in
VAULT/Memory/USER.md.

You see filenames, a coarse source zone, and the local model's proposal - NOT
source paths or file contents. Judge from those. Return one verdict per job.
Return only the JSON object.

DESTINATIONS
  Research-Private  ANY unpublished research output or working material:
                    manuscripts in preparation, figures, data, cloning and
                    construct plans, sequence maps, lab protocols, experiment
                    notes, progress reports, internship/industry work.
                    Buckets: 10_Projects | 20_Areas | 30_Resources | 90_Archive
  G2OS-Staging      Already-public or purely personal: published papers, public
                    conference notes, third-party literature, software guides,
                    CV, job applications, teaching.
                    Buckets: 10_Projects | 20_Areas | 30_Resources | 90_Archive
  Confidential      Immigration/visa, medical, housing, and other people's
                    personal records.  Buckets: 20_Areas | 40_People | 90_Archive
                    (NO 10_Projects, NO 30_Resources)
  Finance           Tax, banking, benefits, insurance, receipts, and financial
                    references. Buckets: 20_Areas | 30_Resources | 90_Archive.
                    Payment-card material was removed by local preflight.
  leave-in-inbox    Genuinely unclear. bucket "none", project null.

KNOWN PROJECTS (only under 10_Projects): {', '.join(PROJECTS)}
A clearly defined new project may propose folder_mode "create"; its project
must equal the first folder segment. A brainstorm is not a new project. Even a
confirmed new project proposal remains pending for the owner's explicit approval.

WHAT TO CATCH - the local model's known weaknesses, in priority order
1. Unpublished project work sent to G2OS-Staging instead of Research-Private.
   G2OS-Staging/10_Projects is almost always wrong. This is the costly error:
   G2OS-Staging may sync to their phone.
2. Immigration, medical, housing, or another person's records NOT sent to
   Confidential. Family members' records go to Confidential/40_People, never to
   any career or CV path, and a family member's profession is never the
   owner's - if USER.md says a partner works in insurance, that employment
   material belongs to that person. Never infer a relationship from a
   name; use only what USER.md states. (List the owner's family members and
   their fields in USER.md so this check has something to match on.)
3. bucket 10_Projects with a null project, or a project on a non-10_Projects
   bucket. Both are malformed.
4. A bucket that does not exist for that vault.
5. A proposed new folder that merely renames one file, duplicates an existing
   concept, is vague, is unsafe, or is not likely to hold future related
   information. A new folder is justified only when it is a durable semantic
   category and existing folders are materially worse.
6. folder_mode "existing" without a folder, folder_mode "bucket-root" with a
   folder, or any absolute/traversal path. Folder paths are bucket-relative and
   at most two levels deep.
7. Any folder_mode "create" on reclassification pass 1 or later. Only one
   folder-creation pass is allowed.
8. folder state "missing" or "invalid" with folder_mode "existing". It cannot
   be filed as proposed. Correct to a defensible existing/root destination,
   correct to "create" only for a durable category, or mark uncertain.

{tendencies}RULES
- verdict "confirm": the proposal is right. Repeat its
  vault/bucket/project/folder/folder_mode.
- verdict "correct": give the corrected destination and say why in note.
- verdict "uncertain": you cannot tell from this metadata alone. Set vault
  "leave-in-inbox", bucket "none", project and folder null, folder_mode
  "bucket-root". Prefer this over guessing.
- Confirming folder_mode "create" creates only the folder, then sends the source
  back through local classification and this verifier with the expanded folder
  map. It does not file the document on this pass.
- Confirmed and corrected items are filed automatically when their dashboard
  actions are also coherent. An uncertain capture action routes only that
  capture to the owner; ordinary filesystem files may still use the local
  content-informed destination with generated actions suppressed.
- `actions_verdict` reviews only the structured action metadata shown above.
  Use `confirm` when the action type, title, and dates are internally coherent;
  use `uncertain` if a deadline, scheduled time, project, or commitment appears
  invented or cannot be defended from metadata. Use `not_applicable` when no
  dashboard actions were proposed. You are not seeing source content, so never
  correct action details here - uncertainty routes them to the owner.
- Return a verdict for EVERY job listed, using the exact job id.

PROPOSALS TO AUDIT ({len(items)})
{table}
"""


def apply(job, result) -> None:
    """No filesystem effect - verdicts are consumed by triage/review.py."""
    return None
