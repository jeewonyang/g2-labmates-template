"""Google Drive integration (personal account): list and read files, read-only."""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.google_auth import build_service  # noqa: E402
from shared import with_retry  # noqa: E402

EXPORT_LIMIT_BYTES = 10_000_000  # Google's files.export cap


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified: str


def list_files(query: str = "trashed = false", max_results: int = 25
              ) -> list[DriveFile]:
    """List files. `query` uses Drive's q= syntax (e.g. "name contains 'grant'")."""
    svc = build_service("drive", "v3")
    resp = with_retry(lambda: svc.files().list(
        q=query, pageSize=max_results, orderBy="modifiedTime desc",
        fields="files(id, name, mimeType, modifiedTime)").execute())
    return [DriveFile(id=f["id"], name=f.get("name", ""),
                      mime_type=f.get("mimeType", ""),
                      modified=f.get("modifiedTime", ""))
            for f in resp.get("files", [])]


def read_file_text(file_id: str, mime_type: str) -> str:
    """Extract text: export native Google Docs, download media for other files."""
    svc = build_service("drive", "v3")
    if mime_type.startswith("application/vnd.google-apps."):
        data = with_retry(lambda: svc.files().export(
            fileId=file_id, mimeType="text/plain").execute())
    else:
        data = with_retry(lambda: svc.files().get_media(fileId=file_id).execute())
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return str(data)


def format_context(files: list[DriveFile]) -> str:
    if not files:
        return "No matching Drive files."
    lines = [f"{len(files)} Drive file(s):"]
    for f in files:
        kind = f.mime_type.replace("application/vnd.google-apps.", "")
        lines.append(f"- {f.name} ({kind}) modified {f.modified[:10]}")
    return "\n".join(lines)
