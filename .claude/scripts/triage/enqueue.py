"""Enqueue triage.classify jobs for every untriaged inbox document.

  python .claude/scripts/triage/enqueue.py --dry-run     # count, list a sample
  python .claude/scripts/triage/enqueue.py --limit 25    # a first batch
  python .claude/scripts/triage/enqueue.py               # everything

Then drain them locally:
  python .claude/scripts/dispatch.py --watch --runtimes ollama
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger  # noqa: E402
from shared import REPO_ROOT  # noqa: E402

INBOXES = [
    "VAULT/G2OS-Staging/00_Inbox",
    "VAULT/Research-Private/00_Inbox",
    "VAULT/Confidential/00_Inbox",
    "VAULT/Finance/00_Inbox",
    "archive/PARA/00_Inbox",
]

# Never walked. Financial material is off-limits everywhere it appears, and
# _quarantine holds deduplicated copies that must not be re-filed.
NEVER_WALK = ("_Finance_PENDING", "_quarantine", "_private", ".obsidian",
              "node_modules", "__pycache__", ".git")

CLASSIFY_SUFFIXES = {".pdf", ".docx", ".md", ".txt", ".pptx", ".xlsx", ".doc"}
MIN_BYTES = 100


def candidates():
    for root in INBOXES:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if any(seg in NEVER_WALK for seg in p.parts):
                continue
            if p.name.startswith("._") or p.name.startswith("~$"):
                continue
            if p.suffix.lower() not in CLASSIFY_SUFFIXES:
                continue
            try:
                if p.stat().st_size < MIN_BYTES:
                    continue
            except OSError:
                continue
            # A .md that is just the extracted text of a sibling docx/pdf is a
            # duplicate of that file - classify the original, not the extract.
            if p.suffix.lower() == ".md":
                if any(p.with_suffix(s).exists() for s in (".pdf", ".docx", ".pptx")):
                    continue
            yield p


def main() -> int:
    dry = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        i = sys.argv.index("--limit")
        limit = int(sys.argv[i + 1])

    found = list(candidates())
    if limit:
        found = found[:limit]

    if dry:
        by_root = {}
        for p in found:
            rel = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
            key = "/".join(rel.split("/")[:2])
            by_root[key] = by_root.get(key, 0) + 1
        for k, v in sorted(by_root.items(), key=lambda x: -x[1]):
            print(f"  {v:5d}  {k}")
        print(f"total: {len(found)} documents")
        for p in found[:5]:
            print(f"    e.g. {p.relative_to(REPO_ROOT)}")
        return 0

    n = 0
    for p in found:
        rel = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
        ledger.create("triage.classify", {"path": rel},
                      runtime="ollama", sensitivity="private")
        n += 1
    print(f"enqueued {n} triage.classify jobs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
