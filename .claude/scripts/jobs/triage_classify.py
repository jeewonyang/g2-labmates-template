"""Classify one untriaged inbox document into a vault destination.

Local-only by construction: inboxes routinely mix sensitive personal records
(immigration or medical material, other people's documents) into ordinary
material, so no inbox content may reach a cloud model. The Phase 3 dispatcher enforces this via
sensitivity=private; this module declares it, and the payload path (under a
vault) makes the guard derive it independently.

Destination map, keywords, and hard rules live in
.agent/plans/agent-os/taxonomy.md - the single source of truth. Keep the prompt
below in sync with it rather than inventing a second copy.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import REPO_ROOT  # noqa: E402
from triage import extract as extractor  # noqa: E402

KIND = "triage.classify"
DEFAULT_RUNTIME = "ollama"
SENSITIVITY = "private"
REVIEW_REQUIRED = True          # filing into a vault reaches outside Memory/
# 300s was too tight: the full 1,053-document run had a p90 of 64s but a max of
# 303s, and 12 jobs failed on "ollama unreachable: timed out" - long documents
# under GPU contention from three parallel workers. Raised with headroom.
TIMEOUT = 900
MODEL = "qwen3:8b"

VAULTS = {
    "G2OS-Staging": ["10_Projects", "20_Areas", "30_Resources", "90_Archive"],
    "Research-Private": ["10_Projects", "20_Areas", "30_Resources", "90_Archive"],
    # Confidential has no 10_Projects / 30_Resources - do not offer them.
    "Confidential": ["20_Areas", "40_People", "90_Archive"],
    "Finance": ["20_Areas", "30_Resources", "90_Archive"],
}

# Seed project folders - replace with your own 10_Projects folder names and
# keep the keyword hints in _RULES below in sync with them.
PROJECTS = ["00_Example-Project"]
FOLDER_MODES = ["bucket-root", "existing", "create"]
MAX_FOLDER_DEPTH = 2
MAX_FOLDER_RECLASSIFICATIONS = 1

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}
_INVALID_FOLDER_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')

# `project` is REQUIRED (nullable). Left optional, qwen3 simply omitted it even
# when its own reason named the project - so files bound for 10_Projects landed
# in the bucket root instead of the project folder. Forcing the key makes the
# model commit to a value.
ACTION_SCHEMA = {
    "type": "object",
    "required": [
        "kind", "title", "details", "priority", "context", "due_date",
        "scheduled_date", "duration_minutes", "calendar_event", "project",
        "area", "confidence",
    ],
    "properties": {
        "kind": {"type": "string", "enum": ["task", "note", "resource", "none"]},
        "title": {"type": "string"},
        "details": {"type": "string"},
        "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
        "context": {"type": ["string", "null"]},
        "due_date": {"type": ["string", "null"]},
        "scheduled_date": {"type": ["string", "null"]},
        "duration_minutes": {"type": ["number", "null"]},
        "calendar_event": {"type": "boolean"},
        "project": {"type": ["string", "null"]},
        "area": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
    },
}

SCHEMA = {
    "type": "object",
    "required": [
        "vault", "bucket", "project", "folder", "folder_mode",
        "folder_rationale", "confidence", "title", "reason", "actions",
    ],
    "properties": {
        "vault": {"type": "string", "enum": list(VAULTS) + ["leave-in-inbox"]},
        "bucket": {"type": "string",
                   "enum": sorted({b for v in VAULTS.values() for b in v} | {"none"})},
        "project": {"type": ["string", "null"]},
        "folder": {"type": ["string", "null"]},
        "folder_mode": {"type": "string", "enum": FOLDER_MODES},
        "folder_rationale": {"type": "string"},
        "person": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "title": {"type": "string"},
        "reason": {"type": "string"},
        "actions": {"type": "array", "items": ACTION_SCHEMA},
    },
}


def safe_folder_parts(value) -> list[str]:
    """Validate a bucket-relative folder path without changing its meaning."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("folder must be a non-empty bucket-relative path")
    text = value.strip().replace("\\", "/")
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise ValueError("folder must be relative to its bucket")
    parts = text.split("/")
    if len(parts) > MAX_FOLDER_DEPTH:
        raise ValueError(
            f"folder may be at most {MAX_FOLDER_DEPTH} levels deep")
    for part in parts:
        if not part or part in {".", ".."}:
            raise ValueError("folder contains an empty or traversal segment")
        if len(part) > 80:
            raise ValueError("folder segment is too long")
        if part.endswith((" ", ".")) or _INVALID_FOLDER_CHARS.search(part):
            raise ValueError(f"unsafe folder segment: {part!r}")
        if part.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
            raise ValueError(f"reserved Windows folder name: {part!r}")
        if part.casefold() in {"finance", "_private"}:
            raise ValueError(
                f"protected folder name is not a triage destination: {part!r}")
    return parts


def normalized_folder(result: dict) -> str | None:
    """Return the explicit folder, with legacy project/person compatibility."""
    folder = result.get("folder")
    if isinstance(folder, str) and folder.strip():
        return "/".join(safe_folder_parts(folder))
    bucket = result.get("bucket")
    if bucket == "10_Projects" and result.get("project"):
        return "/".join(safe_folder_parts(str(result["project"])))
    if (result.get("vault") == "Confidential"
            and bucket == "40_People" and result.get("person")):
        return "/".join(safe_folder_parts(str(result["person"])))
    return None


def _bucket_root(vault: str, bucket: str) -> Path:
    if bucket not in VAULTS.get(vault, []):
        raise ValueError(f"{bucket!r} is not a valid bucket for {vault!r}")
    root = (REPO_ROOT / "VAULT" / vault / bucket).resolve()
    vault_root = (REPO_ROOT / "VAULT" / vault).resolve()
    if not root.is_relative_to(vault_root):
        raise ValueError("destination escaped its vault")
    return root


def destination_folder(result: dict, *, must_exist: bool = False) -> Path:
    """Resolve a validated destination folder inside one permitted Vault bucket."""
    vault = result.get("vault")
    bucket = result.get("bucket")
    if vault in (None, "leave-in-inbox") or bucket in (None, "none"):
        raise ValueError("leave-in-inbox has no filesystem destination")
    root = _bucket_root(str(vault), str(bucket))
    mode = result.get("folder_mode")
    folder = normalized_folder(result)
    if mode == "bucket-root" or (mode is None and folder is None):
        dest = root
    else:
        if mode not in {"existing", "create", None}:
            raise ValueError(f"invalid folder_mode: {mode!r}")
        if not folder:
            raise ValueError(f"folder_mode {mode!r} requires a folder")
        dest = root.joinpath(*safe_folder_parts(folder)).resolve()
        if not dest.is_relative_to(root):
            raise ValueError("folder escaped its bucket")
    if must_exist and not dest.is_dir():
        raise ValueError(f"existing destination folder does not exist: {folder}")
    return dest


def folder_state(result: dict) -> str:
    """Return a metadata-only verifier signal for the proposed folder."""
    mode = result.get("folder_mode")
    if mode == "bucket-root":
        return "bucket-root"
    try:
        dest = destination_folder(result)
    except ValueError:
        return "invalid"
    if mode == "create":
        return "already-exists" if dest.is_dir() else "new-proposal"
    return "exists" if dest.is_dir() else "missing"


def folder_catalog() -> str:
    """Describe existing bucket folders without reading any file contents."""
    lines = []
    for vault, buckets in VAULTS.items():
        for bucket in buckets:
            root = REPO_ROOT / "VAULT" / vault / bucket
            found: list[str] = []
            if root.is_dir():
                try:
                    first_level = sorted(
                        (p for p in root.iterdir()
                         if p.is_dir() and not p.is_symlink()
                         and not p.name.startswith(".")
                         and p.name.casefold() not in {"finance", "_private"}),
                        key=lambda p: p.name.casefold(),
                    )
                    for first in first_level[:60]:
                        found.append(first.name)
                        try:
                            children = sorted(
                                (p for p in first.iterdir()
                                 if p.is_dir() and not p.is_symlink()
                                 and not p.name.startswith(".")
                                 and p.name.casefold()
                                 not in {"finance", "_private"}),
                                key=lambda p: p.name.casefold(),
                            )
                            found.extend(
                                f"{first.name}/{child.name}"
                                for child in children[:20]
                            )
                        except OSError:
                            continue
                except OSError:
                    pass
            listing = " | ".join(found[:100]) if found else "(bucket root only)"
            lines.append(f"  {vault}/{bucket}: {listing}")
    return "\n".join(lines)


_RULES = """\
DESTINATIONS
  G2OS-Staging      10_Projects | 20_Areas | 30_Resources | 90_Archive
                    Career, job applications, published research, technical
                    learning, conference notes, public literature.
  Research-Private  10_Projects | 20_Areas | 30_Resources | 90_Archive
                    Unpublished research, data, constructs, protocols,
                    manuscripts in preparation, industry/internship work.
  Confidential      20_Areas | 40_People | 90_Archive      (NO 10_Projects, NO 30_Resources)
                    Immigration/visa, housing, medical, and other people's
                    personal records.
  Finance           20_Areas | 30_Resources | 90_Archive
                    Tax, banking, benefits, insurance, receipts, and financial
                    reference material. Payment-card credentials are removed
                    by deterministic local policy before this decision.
  leave-in-inbox    Use when genuinely unsure. This is always acceptable.

WHICH BUCKET
  10_Projects   ONLY if the file is specific to ONE genuine project. Set
                "project" to the project's folder name. A clearly defined new
                project may propose a new folder; a brainstorm is not a project.
  30_Resources  Reusable reference material not tied to one project: protocols,
                methods, SOPs, literature, conference and seminar notes, software
                and tooling guides, sequences, structures, templates.
  20_Areas      Ongoing responsibilities, not projects: career and job
                applications, CV, job search, teaching, team admin.
                (In Confidential: immigration, housing, medical.)
  90_Archive    Concluded work: past positions, finished coursework, old degrees.

KNOWN ACTIVE PROJECTS (Research-Private/10_Projects):
  (Template placeholder - list the owner's real project folders here, one per
  line, each with the keywords that identify it, for example:)
  00_Example-Project   example topic: keyword-one, keyword-two, keyword-three

WHICH FOLDER
  folder_mode "existing"    Use the exact bucket-relative path from EXISTING
                            FOLDERS when one is a good semantic home.
  folder_mode "create"      Propose a concise new bucket-relative folder only
                            when it is a durable category likely to hold future
                            related information and every existing folder is
                            materially worse. This creates the folder only after
                            review, then runs classification again before filing.
  folder_mode "bucket-root" Use when the bucket itself is already specific
                            enough. Set folder to null.

Folder paths are relative to the selected bucket, at most two levels deep.
Never use `..`, absolute paths, `_private`, or `Finance`. Do not make a folder
for one filename, one date, or cosmetic tidiness. Prefer an existing folder
when it expresses the same concept.

HARD RULES
1. Immigration or visa material -> Confidential / 20_Areas, project "Immigration".
   Signals: visa, residency or work permit, immigration petition or receipt
   notice, adjustment of status, passport, citizenship. Add the specific form
   numbers and agency names for the owner's jurisdiction here.
2. Records belonging to ANOTHER PERSON -> Confidential / 40_People, and set
   "person" to their name. Never infer a relationship from a name alone: use
   only what USER.md states. A family member's profession is theirs, not the
   owner's - for example, if USER.md says a partner works in insurance, then
   insurance employment records belong to that person's 40_People folder,
   NEVER to the owner and NEVER into a career or CV path. List the owner's
   family members and their fields in USER.md so this rule has something to
   match on.
3. Medical records, housing or rental agreements -> Confidential / 20_Areas.
   Tax, banking, benefits, receipts, and other financial records -> Finance.
4. If bucket is 10_Projects, project MUST NOT be null and must equal the first
   segment of folder. The projects listed above are established; propose a new
   project folder only when the source clearly describes an ongoing effort with
   an outcome. Exploratory or brainstormed ideas are NOT projects.
5. If vault is "leave-in-inbox", set bucket to "none", project and folder to
   null, and folder_mode to "bucket-root".
6. WHICH VAULT - this is the distinction most often gotten wrong, so decide it
   FIRST, before choosing a bucket. Ask: "would it harm the owner if this synced
   to a phone or was seen by someone outside the lab?"
     Research-Private  ANY unpublished research output or working material:
                       manuscripts and outlines in preparation, figures, raw or
                       analysed data, cloning and construct plans, sequence
                       maps, lab protocols, experiment notes, progress and
                       accomplishment reports, grant-progress text, internship
                       or industry work. If it names one of the four projects
                       and is not already published, it is Research-Private.
     G2OS-Staging      Only material that is already public or purely personal:
                       published papers, public conference and seminar notes,
                       third-party literature, software and tooling guides, CV,
                       job applications, teaching material.
   When genuinely torn between the two, choose Research-Private. Over-protecting
   costs nothing; under-protecting exposes unpublished work.
   NOTE: G2OS-Staging/10_Projects is almost always WRONG. Project-specific
   material belongs in Research-Private/10_Projects.
7. The owner's own role and field are described in VAULT/Memory/USER.md. Their
   own CV, job applications, and career materials go to
   G2OS-Staging / 20_Areas.

CONFIDENCE
  Report your true confidence in [0,1]. Below 0.85 sends this to human review,
  which is the safe outcome - do not inflate it.\
"""

_CAPTURE_ACTION_RULES = """\

G2 CAPTURE ACTIONS
If and only if the content frontmatter says `type: g2-capture`, also turn the
thought into zero or more concrete dashboard actions. For every other file,
return an empty `actions` array.

- task: something the owner can actually do. Use one task per independent action.
- note: an idea, observation, question, journal thought, or knowledge worth
  keeping that is not itself an action.
- resource: a URL, paper, tool, book, or reference to save.
- none: use only when the capture has no durable information.
- Preserve the author's meaning. Do not invent commitments, deadlines, people,
  projects, or urgency.
- Resolve relative dates against today's date shown below. `due_date` is
  YYYY-MM-DD. `scheduled_date` is RFC3339 with America/Los_Angeles offset when
  a definite time exists. Otherwise use null.
- `calendar_event` is true only for a definite event with a stated date AND
  time. This is a proposal signal; it never creates an external event directly.
- `project` and `area` are names only when clearly stated. Otherwise null.
- A mixed thought may produce multiple actions. A pure thought should normally
  produce one note. Keep titles concise and put traceable context in details.
- A short imperative capture ("collect...", "email...", "run...", "write...")
  is a `task`, even when it has no date. With no date it is a next action:
  leave `due_date` and `scheduled_date` null. Infer a context only when the
  activity itself makes it clear (for example bench/sample work -> `lab`);
  otherwise leave context null so G2 can visibly flag it for clarification.
- Never turn one terse task into a new project or folder. A new project requires
  explicit project intent plus a durable outcome, not merely a noun or acronym.
- Dates, times, durations, projects, and urgency must be grounded in the capture.
  Never copy the capture timestamp into due/scheduled fields.
"""

_IMPERATIVE_VERBS = {
    "add", "analyze", "ask", "book", "buy", "call", "check", "clean",
    "collect", "compare", "complete", "confirm", "contact", "create",
    "draft", "email", "embed", "export", "file", "finish", "fix",
    "follow", "freeze", "image", "make", "measure", "message", "order",
    "prepare", "read", "reply", "review", "run", "schedule", "send",
    "set", "submit", "test", "update", "upload", "verify", "write",
}
_DATE_SIGNAL = re.compile(
    r"\b(?:today|tomorrow|tonight|next\s+(?:week|month|"
    r"mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)|"
    r"mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}\b|"
    r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    re.IGNORECASE,
)
_TIME_SIGNAL = re.compile(
    r"\b(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)\b|"
    r"\b(?:noon|midnight)\b",
    re.IGNORECASE,
)
_DURATION_SIGNAL = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:minutes?|mins?|hours?|hrs?)\b",
    re.IGNORECASE,
)
_EXPLICIT_PROJECT = re.compile(
    r"\b(?:start|create|launch|begin|set\s+up)\s+"
    r"(?:a\s+|an\s+|new\s+)?project\b|\bproject\s*:",
    re.IGNORECASE,
)
_VALID_CONTEXTS = {
    "office", "lab", "computer", "phone", "home", "errand",
    "anywhere", "creative", "routine",
}


def _capture_text(job: dict) -> str | None:
    """Return the authored body for a staged G2 capture, without frontmatter."""
    rel = (job.get("payload") or {}).get("path")
    if not isinstance(rel, str) or not rel:
        return None
    path = (REPO_ROOT / rel).resolve()
    if not path.is_relative_to(REPO_ROOT) or not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not re.search(r"(?m)^type:\s*g2-capture\s*$", raw):
        return None
    raw = re.sub(r"\A---\s*\n.*?\n---\s*", "", raw, count=1,
                 flags=re.DOTALL)
    lines = [line.rstrip() for line in raw.splitlines()]
    heading = ""
    if lines and lines[0].lstrip().startswith("# "):
        heading = lines.pop(0).lstrip()[2:].strip()
    body = "\n".join(lines).strip()
    return body or heading or None


def _looks_like_task(text: str) -> bool:
    first = re.search(r"[A-Za-z]+", text)
    return bool(first and first.group(0).casefold() in _IMPERATIVE_VERBS)


def _grounded_context(text: str, proposed) -> str | None:
    """Keep/infer only dashboard contexts defensible from the capture itself."""
    proposed_text = str(proposed or "").strip().casefold()
    if proposed_text in _VALID_CONTEXTS:
        return proposed_text
    folded = text.casefold()
    if re.search(
        r"\b(?:brain|sample|specimen|embed|embedding|oct|histology|"
        r"microscope|assay|culture|clone|cloning|mouse|mice|imaging|"
        r"experiment|bench|centrifuge|stain|fixation)\b",
        folded,
    ):
        return "lab"
    if re.search(
        r"\b(?:code|script|spreadsheet|document|slides?|analy[sz]e|"
        r"search|upload|download|website|computer)\b",
        folded,
    ):
        return "computer"
    if re.search(r"\b(?:call|phone|text|message)\b", folded):
        return "phone"
    if re.search(r"\b(?:buy|pick\s+up|drop\s+off|store|mail)\b", folded):
        return "errand"
    return None


def normalize_capture_result(job: dict, result: dict) -> dict:
    """Ground mechanically checkable capture metadata before review/Prisma."""
    text = _capture_text(job)
    if not text or not isinstance(result, dict):
        return result
    text = text.strip()
    short_task = len(text) <= 240 and _looks_like_task(text)
    explicit_project = bool(_EXPLICIT_PROJECT.search(text))
    blocked_new_project = False

    if (short_task and not explicit_project
            and result.get("bucket") == "10_Projects"
            and result.get("folder_mode") == "create"):
        blocked_new_project = True
        result["bucket"] = "20_Areas"
        result["project"] = None
        result["folder"] = None
        result["folder_mode"] = "bucket-root"
        result["folder_rationale"] = (
            "Terse next action: file at the area root; one action does not "
            "establish a new project or durable folder."
        )
        result["reason"] = (
            "Deterministic capture policy prevented a one-line next action "
            "from creating a project."
        )

    actions = result.get("actions")
    if not isinstance(actions, list):
        actions = []
    usable = [action for action in actions if isinstance(action, dict)]
    if short_task and not usable:
        usable = [{}]

    for action in usable:
        if short_task:
            action["kind"] = "task"
            action["title"] = text[:300]
            action["details"] = text[:10000]
            try:
                confidence = float(action.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0
            action["confidence"] = max(0.9, confidence)
            if blocked_new_project:
                action["project"] = None
            if not re.search(
                    r"\b(?:urgent|asap|immediately|critical|high priority)\b",
                    text, re.IGNORECASE):
                action["priority"] = "medium"
        if action.get("kind") != "task":
            continue
        action["context"] = _grounded_context(text, action.get("context"))
        if not _DATE_SIGNAL.search(text):
            action["due_date"] = None
        if not (_DATE_SIGNAL.search(text) and _TIME_SIGNAL.search(text)):
            action["scheduled_date"] = None
            action["calendar_event"] = False
        if not _DURATION_SIGNAL.search(text):
            action["duration_minutes"] = None
        if action.get("priority") not in {
                "low", "medium", "high", "urgent"}:
            action["priority"] = "medium"
    result["actions"] = usable
    return result


def build_prompt(payload) -> str:
    payload = payload or {}
    rel = payload.get("path", "")
    info = extractor.describe(REPO_ROOT / rel, REPO_ROOT)
    body = info["text"] or "(no extractable text - classify from the path and filename)"
    reclassification_pass = int(payload.get("reclassificationPass") or 0)
    created = payload.get("createdFolder")
    if reclassification_pass:
        reclassification_note = f"""
RECLASSIFICATION PASS {reclassification_pass}
  A reviewed folder proposal was created at: {created or "(unknown)"}
  Classify the source again against the expanded folder map. You may select
  that folder, another existing folder, a different bucket, or leave it in the
  inbox. Do NOT propose another new folder on this pass.
"""
    else:
        reclassification_note = ""
    from shared import now
    # This prompt goes only to the local Ollama model, so the lesson block may
    # include capture titles; the cloud verifier gets aggregates only.
    try:
        from triage import lessons
        lessons_block = lessons.prompt_block()
    except Exception:  # noqa: BLE001 - lessons are advisory, never blocking
        lessons_block = ""
    return f"""Classify this file into The Owner's vault. Return only the JSON object.

{_RULES}
{_CAPTURE_ACTION_RULES}
{lessons_block}
EXISTING FOLDERS
{folder_catalog()}
{reclassification_note}

TODAY
  {now():%Y-%m-%d} in America/Los_Angeles

FILE
  path:     {info['path']}
  filename: {info['name']}
  folder:   {info['folder']}
  size:     {info['size']} bytes
  nearby:   {', '.join(info['siblings']) or '(none)'}

CONTENT (first {len(body)} chars)
\"\"\"
{body}
\"\"\"
"""


# Auto-approval is DISABLED for triage, and this is a measurement, not caution.
# On a 12-document sample (2026-07-26, qwen3:8b) bucket and project choice were
# correct 12/12, but *vault* choice was wrong 2/12 - unpublished manuscripts and
# lab protocols were sent to G2OS-Staging instead of Research-Private. Both errors
# came back at confidence 0.95, so a 0.85 threshold would have auto-filed them:
# the model is confidently wrong on exactly the distinction that decides whether
# unpublished work becomes shareable. ~17% misfiling is not worth the saved clicks
# when /ops batch approval (Phase 5) makes review cheap.
#
# To re-enable once accuracy is measured higher, drop AUTO_APPROVE_THRESHOLD to a
# real value and re-run the sample first.
AUTO_APPROVE_THRESHOLD = None


def needs_human(result: dict) -> bool:
    """Confidence policy - see taxonomy.md section 5 and the note above."""
    if not isinstance(result, dict):
        return True
    if AUTO_APPROVE_THRESHOLD is None:
        return True
    if result.get("vault") in ("Confidential", "leave-in-inbox"):
        return True          # Confidential is always per-item; inbox needs a decision
    if result.get("bucket") == "10_Projects" and not result.get("project"):
        return True          # 10_Projects without a project folder is malformed
    if result.get("folder_mode") == "create":
        return True          # creating taxonomy requires the verifier
    if result.get("folder_mode") in {"existing", "create"}:
        try:
            safe_folder_parts(result.get("folder"))
        except ValueError:
            return True
    try:
        return float(result.get("confidence", 0)) < AUTO_APPROVE_THRESHOLD
    except (TypeError, ValueError):
        return True


def prepare_folder_reclassification(job: dict, result: dict, *,
                                    actor: str) -> dict:
    """Create one reviewed folder and enqueue a fresh local classification."""
    import ledger

    if result.get("folder_mode") != "create":
        raise ValueError("proposal does not request folder creation")
    payload = dict(job.get("payload") or {})
    current_pass = int(payload.get("reclassificationPass") or 0)
    if current_pass >= MAX_FOLDER_RECLASSIFICATIONS:
        raise ValueError("a reclassification pass may not create another folder")

    folder = normalized_folder(result)
    if result.get("bucket") == "10_Projects":
        parts = safe_folder_parts(folder)
        if result.get("project") != parts[0]:
            raise ValueError(
                "10_Projects project must equal the first folder segment")
    dest_dir = destination_folder(result)
    dest_dir.mkdir(parents=True, exist_ok=True)
    rel_folder = str(dest_dir.relative_to(REPO_ROOT)).replace("\\", "/")
    next_payload = {
        **payload,
        "reclassificationPass": current_pass + 1,
        "createdFolder": rel_folder.removeprefix("VAULT/"),
        "previousClassificationJob": job.get("job"),
    }
    replacement = ledger.create(
        KIND,
        next_payload,
        runtime=DEFAULT_RUNTIME,
        sensitivity=SENSITIVITY,
        parent=job.get("job"),
    )
    ledger.supersede(
        job["job"],
        replacement,
        by=actor,
        note=f"created {rel_folder}; classify again against expanded folders",
    )
    if payload.get("automationId"):
        import capture_sync
        capture_sync.record_reclassification(
            job, replacement, rel_folder, actor=actor)
    return {
        "reclassificationJobId": replacement,
        "createdFolder": rel_folder,
    }


def apply(job, result):
    """Called only after human approval. Copy, never move - see taxonomy.md 4.5."""
    import shutil
    from datetime import datetime

    payload = job.get("payload") or {}
    src = REPO_ROOT / payload.get("path", "")
    vault = result.get("vault")
    bucket = result.get("bucket")
    if vault in (None, "leave-in-inbox") or bucket in (None, "none"):
        return
    if result.get("folder_mode") == "create":
        # Approval of a folder proposal never files the source immediately.
        # Create the taxonomy, then force the local model and verifier through
        # a second pass with that folder visible as an existing option.
        return prepare_folder_reclassification(job, result, actor="approved-review")

    dest_dir = destination_folder(
        result, must_exist=result.get("folder_mode") == "existing")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    if not src.exists():
        raise FileNotFoundError(f"source vanished: {src}")
    if dest.exists():
        dest = dest_dir / f"{src.stem}__{job['job'][-8:]}{src.suffix}"
    shutil.copy2(src, dest)

    manifest = REPO_ROOT / ".claude" / "data" / "triage-manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    import json
    with open(manifest, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "job": job["job"],
            "src": str(src.relative_to(REPO_ROOT)).replace("\\", "/"),
            "dst": str(dest.relative_to(REPO_ROOT)).replace("\\", "/"),
            "confidence": result.get("confidence"),
        }, ensure_ascii=False) + "\n")

    # Web/mobile captures carry durable Prisma identities in the job payload.
    # Apply their dashboard entities in one SQLite transaction after the file
    # copy succeeds. Ordinary filesystem inbox documents skip this bridge.
    if payload.get("automationId") and payload.get("inboxItemId"):
        import capture_sync
        capture_sync.apply_capture(
            job,
            result,
            str(dest.relative_to(REPO_ROOT)).replace("\\", "/"),
        )


def on_result(job, result) -> None:
    """Mirror local-model output into the dashboard before cloud verification."""
    normalize_capture_result(job, result)
    if (job.get("payload") or {}).get("automationId"):
        import capture_sync
        capture_sync.record_local(job, result)


def on_failure(job, error) -> None:
    if (job.get("payload") or {}).get("automationId"):
        import capture_sync
        capture_sync.record_failure(job, error)
