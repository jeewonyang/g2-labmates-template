"""On-demand paper selection and Rho review launcher.

The dashboard sends a DOI or a server-validated feed item to this narrow
entrypoint over stdin. Public citation metadata is resolved here, the
selection is appended to the local bibliography event log, and the existing
research.lit_review job is enqueued in the shared Agent OS ledger.

The ``run`` command claims one known job and hands it to dispatch.run_one().
That gives manual reviews low latency without creating another queue,
scheduler, or model execution path.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import uuid
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402
from shared import DATA, file_lock, now  # noqa: E402

BIB_DIR = DATA / "research"
BIB_EVENTS = BIB_DIR / "bibliography-events.jsonl"
# 3 (2026-07-30): relevance-gated digest template - verdict blockquote, three
# grouped sections with H3 field labels, screened form for low relevance, and a
# single consolidated evidence-gap note. Bumped so a paper already reviewed
# under the old flat seven-section format is not deduped away and can be
# re-reviewed into the new one.
SCHEMA_VERSION = 3
USER_AGENT = "SecondBrain/1.0 (personal research monitor)"

DOI_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:a-z0-9]+$", re.I)
JOB_RE = re.compile(r"^\d{16}-[a-f0-9]{8}$")
ITEM_RE = re.compile(r"^[a-z0-9_-]{1,200}$", re.I)
TAG_RE = re.compile(r"<[^>]+>")


class ResearchReviewError(RuntimeError):
    pass


def _unicode_safe(value):
    """Recursively replace lone UTF-16 surrogates without harming valid text."""
    if isinstance(value, str):
        # JavaScript JSON.stringify() escapes lone surrogates, and json.loads()
        # accepts them. UTF-8 correctly refuses to encode them. This UTF-16
        # round-trip combines valid surrogate pairs and replaces only malformed
        # code units with U+FFFD, while preserving emoji and other Unicode.
        return value.encode("utf-16-le", "surrogatepass").decode(
            "utf-16-le", "replace"
        )
    if isinstance(value, dict):
        return {
            _unicode_safe(key): _unicode_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_unicode_safe(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_unicode_safe(item) for item in value)
    return value


def _json_text(value) -> str:
    """Serialize JSON that is guaranteed to be writable as UTF-8."""
    return json.dumps(
        _unicode_safe(value),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def normalize_doi(value: str) -> str:
    doi = urllib.parse.unquote(str(value or "").strip())
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    doi = doi.strip().rstrip(".,;").lower()
    if not DOI_RE.fullmatch(doi):
        raise ResearchReviewError("Enter a valid DOI, such as 10.1101/2026.01.02.123456.")
    return doi


def canonical_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"),
         urllib.parse.urlencode(query), "")
    )


def _clean_markup(value: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", str(value or ""))).split())


def _json_get(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _resolve_biorxiv(doi: str) -> dict | None:
    try:
        payload = _json_get(
            f"https://api.biorxiv.org/details/biorxiv/{urllib.parse.quote(doi)}"
        )
    except Exception:
        return None
    rows = payload.get("collection") or []
    if not rows:
        return None
    row = rows[-1]
    authors = [
        {"literal": name.strip()}
        for name in re.split(r"\s*;\s*", str(row.get("authors") or ""))
        if name.strip()
    ]
    published_doi = str(row.get("published") or row.get("published_doi") or "").strip()
    return {
        "title": " ".join(str(row.get("title") or "").split()),
        "authors": authors,
        "author_text": " ".join(str(row.get("authors") or "").split()),
        "abstract": " ".join(str(row.get("abstract") or "").split()),
        "published_at": str(row.get("date") or "")[:10],
        "journal": f"bioRxiv ({row.get('category')})" if row.get("category") else "bioRxiv",
        "source": "biorxiv",
        "url": f"https://doi.org/{doi}",
        "doi": published_doi.lower() if DOI_RE.fullmatch(published_doi) else doi,
        "preprint_doi": doi,
    }


def _resolve_crossref(doi: str) -> dict | None:
    try:
        payload = _json_get(
            f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}"
        )
    except Exception:
        return None
    row = payload.get("message") or {}
    titles = row.get("title") or []
    containers = row.get("container-title") or []
    authors = []
    author_text = []
    for author in row.get("author") or []:
        given = str(author.get("given") or "").strip()
        family = str(author.get("family") or "").strip()
        if given or family:
            authors.append({"given": given, "family": family})
            author_text.append(" ".join(part for part in (given, family) if part))
    date_parts = (
        (row.get("published") or {}).get("date-parts")
        or (row.get("published-online") or {}).get("date-parts")
        or (row.get("issued") or {}).get("date-parts")
        or []
    )
    published = "-".join(str(part).zfill(2) for part in (date_parts[0] if date_parts else []))
    return {
        "title": " ".join(str(titles[0] if titles else "").split()),
        "authors": authors,
        "author_text": ", ".join(author_text),
        "abstract": _clean_markup(row.get("abstract") or ""),
        "published_at": published,
        "journal": str(containers[0] if containers else "").strip(),
        "source": "crossref",
        "url": f"https://doi.org/{doi}",
        "doi": doi,
        "preprint_doi": "",
    }


def resolve_metadata(request: dict) -> dict:
    supplied = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
    doi_raw = request.get("doi") or supplied.get("doi") or ""
    doi = normalize_doi(doi_raw) if doi_raw else ""

    resolved = None
    if doi.startswith("10.1101/"):
        resolved = _resolve_biorxiv(doi)
    if resolved is None and doi:
        resolved = _resolve_crossref(doi)

    metadata = {
        "title": str((resolved or {}).get("title") or supplied.get("title") or "").strip(),
        "authors": (resolved or {}).get("authors") or supplied.get("authors") or [],
        "author_text": str(
            (resolved or {}).get("author_text") or supplied.get("authorText") or ""
        ).strip(),
        "abstract": str(
            (resolved or {}).get("abstract")
            or supplied.get("abstract")
            or supplied.get("summary")
            or ""
        ).strip(),
        "published_at": str(
            (resolved or {}).get("published_at") or supplied.get("publishedAt") or ""
        ).strip(),
        "journal": str(
            (resolved or {}).get("journal") or supplied.get("journal") or ""
        ).strip(),
        "source": str(
            supplied.get("source") or (resolved or {}).get("source") or request.get("source") or ""
        ).strip(),
        "url": canonical_url(
            str((resolved or {}).get("url") or supplied.get("url") or "")
        ),
        "doi": str((resolved or {}).get("doi") or doi).lower(),
        "preprint_doi": str((resolved or {}).get("preprint_doi") or "").lower(),
    }
    if not metadata["title"]:
        raise ResearchReviewError("The paper metadata did not include a title.")
    return metadata


def fold_events(events: list[dict]) -> dict[str, dict]:
    items: dict[str, dict] = {}
    for event in events:
        item_id = str(event.get("item_id") or "")
        if not item_id:
            continue
        item = items.setdefault(
            item_id,
            {
                "item_id": item_id,
                "identifiers": {},
                "metadata": {},
                "projects": {},
                "resources": {},
                "areas": {},
                "archived": False,
                "latest_review_job_id": None,
                "digest_path": None,
            },
        )
        kind = event.get("event")
        if kind in {"paper_selected", "metadata_enriched"}:
            item["identifiers"].update(event.get("identifiers") or {})
            item["metadata"].update(event.get("metadata") or {})
        elif kind == "project_assigned":
            item["projects"][str(event.get("project_id") or "")] = str(
                event.get("project_title") or ""
            )
        elif kind == "resource_assigned":
            item["resources"][str(event.get("resource_id") or "")] = str(
                event.get("resource_title") or ""
            )
        elif kind == "area_assigned":
            item["areas"][str(event.get("area_id") or "")] = str(
                event.get("area_title") or ""
            )
        elif kind == "paper_reclassified":
            item["projects"].clear()
            item["resources"].clear()
            item["areas"].clear()
            target_type = str(event.get("target_type") or "")
            target_id = str(event.get("target_id") or "")
            target_title = str(event.get("target_title") or "")
            if target_type in {"project", "resource", "area"} and target_id:
                item[f"{target_type}s"][target_id] = target_title
        elif kind == "paper_archived":
            item["archived"] = True
        elif kind == "paper_restored":
            item["archived"] = False
        elif kind == "review_linked":
            item["latest_review_job_id"] = event.get("job_id")
        elif kind == "review_completed":
            item["latest_review_job_id"] = event.get("job_id")
            item["digest_path"] = event.get("digest_path")
    return items


def _read_events() -> list[dict]:
    try:
        lines = BIB_EVENTS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _append_event_unlocked(event: dict) -> None:
    BIB_DIR.mkdir(parents=True, exist_ok=True)
    row = {"ts": now().isoformat(timespec="seconds"), **event}
    with open(BIB_EVENTS, "a", encoding="utf-8") as stream:
        stream.write(_json_text(row) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _append_event(event: dict) -> None:
    with file_lock(BIB_EVENTS):
        _append_event_unlocked(event)


def _identifiers(metadata: dict) -> dict:
    return {
        key: value
        for key, value in {
            "doi": metadata.get("doi") or "",
            "preprint_doi": metadata.get("preprint_doi") or "",
            "url": canonical_url(metadata.get("url") or ""),
        }.items()
        if value
    }


def _find_item(items: dict[str, dict], identifiers: dict) -> dict | None:
    for item in items.values():
        existing = item.get("identifiers") or {}
        if any(existing.get(key) == value for key, value in identifiers.items() if value):
            return item
    return None


def _find_existing_job(
    item_id: str,
    client_request_id: str,
    target_type: str,
    target_id: str,
) -> dict | None:
    jobs = ledger.fold()
    for job in jobs.values():
        if job.get("kind") != "research.lit_review":
            continue
        payload = job.get("payload") or {}
        if payload.get("client_request_id") == client_request_id:
            return job
        job_target_type = payload.get("target_type") or (
            "project" if payload.get("project_id") else ""
        )
        job_target_id = payload.get("target_id") or payload.get("project_id")
        if (
            payload.get("item_id") == item_id
            and payload.get("review_schema") == SCHEMA_VERSION
            and job_target_type == target_type
            and job_target_id == target_id
            and job.get("status") in {"created", "claimed", "completed"}
        ):
            return job
    return None


def _target_fields(request: dict) -> tuple[str, str, str]:
    legacy_project_id = str(request.get("projectId") or "").strip()
    target_type = str(
        request.get("targetType") or ("project" if legacy_project_id else "")
    ).strip().lower()
    target_id = str(request.get("targetId") or legacy_project_id).strip()
    target_title = str(
        request.get("targetTitle") or request.get("projectTitle") or ""
    ).strip()
    if (
        target_type not in {"project", "resource", "area"}
        or not target_id
        or not target_title
    ):
        raise ResearchReviewError(
            "Choose a project, resource, or area before saving the paper."
        )
    return target_type, target_id, target_title


def _is_only_target(
    item: dict | None,
    target_type: str,
    target_id: str,
    target_title: str,
) -> bool:
    if not item:
        return False
    buckets = [
        item.get("projects") or {},
        item.get("resources") or {},
        item.get("areas") or {},
    ]
    return (
        sum(len(bucket) for bucket in buckets) == 1
        and (item.get(f"{target_type}s") or {}).get(target_id) == target_title
    )


def enqueue(request: dict) -> dict:
    # The browser can legally send escaped lone surrogates even though UTF-8
    # storage cannot represent them. Normalize once at ingress, then again at
    # the append boundary as defense in depth for future non-browser callers.
    request = _unicode_safe(request)
    client_request_id = str(request.get("clientRequestId") or "")
    try:
        uuid.UUID(client_request_id)
    except (ValueError, TypeError):
        raise ResearchReviewError("A valid client request id is required.")
    # projectId/projectTitle remain accepted for queued requests created before
    # typed Project/Resource/Area targets shipped.
    target_type, target_id, target_title = _target_fields(request)

    metadata = _unicode_safe(resolve_metadata(request))
    identifiers = _identifiers(metadata)
    with file_lock(BIB_EVENTS):
        items = fold_events(_read_events())
        item = _find_item(items, identifiers)
        item_id = item["item_id"] if item else str(uuid.uuid4())
        if item is None:
            _append_event_unlocked({
                "event": "paper_selected",
                "item_id": item_id,
                "identifiers": identifiers,
                "metadata": metadata,
            })
        elif any(
            value and (item.get("identifiers") or {}).get(key) != value
            for key, value in identifiers.items()
        ):
            _append_event_unlocked({
                "event": "metadata_enriched",
                "item_id": item_id,
                "identifiers": identifiers,
                "metadata": metadata,
            })
        if item and item.get("archived"):
            _append_event_unlocked({
                "event": "paper_restored",
                "item_id": item_id,
            })
        if not _is_only_target(item, target_type, target_id, target_title):
            id_key = f"{target_type}_id"
            title_key = f"{target_type}_title"
            if item and any(
                item.get(bucket) for bucket in ("projects", "resources", "areas")
            ):
                _append_event_unlocked({
                    "event": "paper_reclassified",
                    "item_id": item_id,
                    "target_type": target_type,
                    "target_id": target_id,
                    "target_title": target_title,
                })
            else:
                _append_event_unlocked({
                    "event": f"{target_type}_assigned",
                    "item_id": item_id,
                    id_key: target_id,
                    title_key: target_title,
                })

    existing = _find_existing_job(
        item_id,
        client_request_id,
        target_type,
        target_id,
    )
    if existing:
        return {
            "itemId": item_id,
            "jobId": existing["job"],
            "status": existing["status"],
            "savedOnly": False,
            "reused": True,
        }

    if not metadata["abstract"]:
        return {
            "itemId": item_id,
            "jobId": None,
            "status": "saved",
            "savedOnly": True,
            "reused": False,
            "message": "Saved to the bibliography, but no abstract was available to review.",
        }

    job_payload = _unicode_safe({
        "item_id": item_id,
        "client_request_id": client_request_id,
        "review_schema": SCHEMA_VERSION,
        "trigger": "manual",
        "target_type": target_type,
        "target_id": target_id,
        "target_title": target_title,
        **({
            "project_id": target_id,
            "project_title": target_title,
        } if target_type == "project" else {}),
        "paper_id": metadata["doi"] or metadata["preprint_doi"] or item_id,
        "title": metadata["title"],
        "authors": metadata["author_text"],
        "summary": metadata["abstract"][:8_000],
        "url": metadata["url"],
        "source": metadata["source"] or "doi",
        "journal": metadata["journal"],
        "doi": metadata["doi"],
        "matched_queries": f"selected for {target_type}: {target_title}",
    })
    job_id = ledger.create(
        "research.lit_review",
        job_payload,
        runtime="claude",
        sensitivity="internal",
    )
    _append_event({
        "event": "review_linked",
        "item_id": item_id,
        "job_id": job_id,
        "schema_version": SCHEMA_VERSION,
    })
    return {
        "itemId": item_id,
        "jobId": job_id,
        "status": "created",
        "savedOnly": False,
        "reused": False,
    }


def archive_item(request: dict) -> dict:
    item_id = str(request.get("itemId") or "").strip()
    if not ITEM_RE.fullmatch(item_id):
        raise ResearchReviewError("A valid bibliography item id is required.")
    with file_lock(BIB_EVENTS):
        item = fold_events(_read_events()).get(item_id)
        if not item:
            raise ResearchReviewError("That bibliography entry no longer exists.")
        if item.get("archived"):
            return {"itemId": item_id, "archived": True, "reused": True}
        _append_event_unlocked({
            "event": "paper_archived",
            "item_id": item_id,
        })
    return {"itemId": item_id, "archived": True, "reused": False}


def reclassify_item(request: dict) -> dict:
    item_id = str(request.get("itemId") or "").strip()
    if not ITEM_RE.fullmatch(item_id):
        raise ResearchReviewError("A valid bibliography item id is required.")
    target_type, target_id, target_title = _target_fields(request)
    with file_lock(BIB_EVENTS):
        item = fold_events(_read_events()).get(item_id)
        if not item or item.get("archived"):
            raise ResearchReviewError("That bibliography entry is not active.")
        if _is_only_target(item, target_type, target_id, target_title):
            return {
                "itemId": item_id,
                "targetType": target_type,
                "targetId": target_id,
                "reused": True,
            }
        _append_event_unlocked({
            "event": "paper_reclassified",
            "item_id": item_id,
            "target_type": target_type,
            "target_id": target_id,
            "target_title": target_title,
        })
    return {
        "itemId": item_id,
        "targetType": target_type,
        "targetId": target_id,
        "reused": False,
    }


def record_review_result(
    item_id: str,
    job_id: str,
    *,
    digest_path: str | None = None,
    error: str | None = None,
) -> None:
    if not item_id or not job_id:
        return
    _append_event({
        "event": "review_completed" if digest_path else "review_failed",
        "item_id": item_id,
        "job_id": job_id,
        "digest_path": digest_path,
        "error": error,
    })


def run_job(job_id: str) -> int:
    if not JOB_RE.fullmatch(job_id):
        raise ResearchReviewError("Invalid research job id.")
    worker = f"research-manual-{os.getpid()}"
    job = ledger.claim_job(job_id, worker)
    if job is None:
        return 0
    import dispatch
    dispatch.run_one(job)
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if command in {"enqueue", "archive", "reclassify"}:
            request = json.loads(sys.stdin.read() or "{}")
            handler = {
                "enqueue": enqueue,
                "archive": archive_item,
                "reclassify": reclassify_item,
            }[command]
            print(json.dumps(handler(request), ensure_ascii=False))
            return 0
        if command == "run" and len(sys.argv) == 4 and sys.argv[2] == "--job-id":
            return run_job(sys.argv[3])
        raise ResearchReviewError(
            "Usage: research_review.py enqueue|archive|reclassify | run --job-id ID"
        )
    except (ResearchReviewError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
