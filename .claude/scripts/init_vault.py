"""Create your knowledge vault. Idempotent - safe to re-run.

A fresh clone of the template has no VAULT/ at all: the vault is personal and
is never committed (see .gitignore). This script

1. creates the vault folders (the sensitivity tiers, each with PARA buckets),
2. copies the blank starting files from vault-template/Memory/ into
   VAULT/Memory/ - never overwriting a file that already exists, so re-running
   it cannot touch anything you or the agent wrote.

Run:  python .claude/scripts/init_vault.py
"""

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VAULT = REPO_ROOT / "VAULT"
TEMPLATE = REPO_ROOT / "vault-template" / "Memory"

PARA = ["00_Inbox", "10_Projects", "20_Areas", "30_Resources", "90_Archive"]

DIRS = [
    # The agent's own state: profile, decisions, daily logs, drafts, digests.
    *(f"Memory/{d}" for d in (
        "daily", "drafts/active", "drafts/sent", "drafts/expired",
        "meetings", "meetings/actions", "projects",
        "research/digests", "wiki", "admin", "security",
    )),
    # Internal vault - published work, career, technical learning. Cloud
    # models may read it; it is indexed for search.
    *(f"G2OS-Staging/{d}" for d in PARA),
    # Private vault - unpublished research, data, manuscripts, and your lab
    # notebook (10_Projects/<project>/04_Notebook/). Local models only in bulk
    # automation; indexed locally.
    *(f"Research-Private/{d}" for d in PARA),
    # Confidential - legal, housing, medical, other people's records. Never
    # indexed, never sent to a cloud model in automation.
    *(f"Confidential/{d}" for d in ("00_Inbox", "20_Areas", "40_People", "90_Archive")),
    # Finance - tax and financial records. Never indexed.
    *(f"Finance/{d}" for d in PARA),
]


def main() -> int:
    created = 0
    for rel in DIRS:
        path = VAULT / rel
        if not path.is_dir():
            path.mkdir(parents=True, exist_ok=True)
            created += 1
            print(f"created  VAULT/{rel}")

    copied = 0
    if TEMPLATE.is_dir():
        for src in sorted(TEMPLATE.rglob("*")):
            if not src.is_file():
                continue
            dest = VAULT / "Memory" / src.relative_to(TEMPLATE)
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
            print(f"copied   VAULT/Memory/{src.relative_to(TEMPLATE).as_posix()}")

    print(f"done - {created} folders created, {copied} starter files copied "
          f"(existing files are never overwritten)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
