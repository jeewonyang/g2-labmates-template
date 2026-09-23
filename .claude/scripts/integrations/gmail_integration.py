"""Gmail integration (personal Google account): read messages, create drafts.

Advisor mode: this module can READ mail and CREATE drafts. It never sends.
There is deliberately no send function anywhere in this file.
"""

import base64
import os
import re
import sys
from dataclasses import dataclass, field
from email.utils import parseaddr
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.google_auth import build_service  # noqa: E402
from shared import with_retry  # noqa: E402

DEFAULT_SELF_ADDRESSES = ("you@work.example.edu", "you@example.com")
SELF_SENT_LOOKBACK_DAYS = 30


@dataclass
class EmailMessage:
    id: str
    thread_id: str
    sender: str
    subject: str
    date: str
    snippet: str
    unread: bool
    labels: list[str] = field(default_factory=list)
    attachment_names: list[str] = field(default_factory=list)
    body: str = ""
    forwarded_sender: str = ""
    forwarded_subject: str = ""


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def self_addresses() -> tuple[str, ...]:
    """Addresses whose mail should be treated as the owner's own intake.

    The environment override makes future aliases additive without a code
    change. The two defaults are the authenticated personal account and the
    work account they forward into it.
    """
    configured = os.environ.get("ADMIN_SELF_EMAILS", "")
    addresses = DEFAULT_SELF_ADDRESSES + tuple(configured.split(","))
    return tuple(dict.fromkeys(
        address.strip().lower() for address in addresses if address.strip()))


def is_self_sender(sender: str) -> bool:
    """Whether a Gmail From header belongs to the owner."""
    address = parseaddr(sender or "")[1].strip().lower()
    return address in self_addresses()


_FORWARD_MARKER = re.compile(
    r"(?im)^\s*(?:-{2,}\s*Forwarded message\s*-{2,}|"
    r"Begin forwarded message:|Forwarded message:)\s*$"
)
_FORWARD_HEADER = re.compile(
    r"(?im)^\s*(From|Subject)\s*:\s*(.+?)\s*$"
)


def extract_forwarded_headers(body: str) -> dict[str, str]:
    """Recover the original sender/subject from a self-forwarded message.

    Gmail and Outlook use slightly different forward separators, and some
    clients omit the separator entirely. Prefer headers after the last explicit
    forward marker, then fall back to non-self ``From:`` lines anywhere in the
    body. The outer Gmail From header is handled separately and is never used
    as the reply target.
    """
    text = body or ""
    markers = list(_FORWARD_MARKER.finditer(text))
    candidate = text[markers[-1].end():] if markers else text
    found: dict[str, str] = {}
    for match in _FORWARD_HEADER.finditer(candidate):
        key = match.group(1).lower()
        value = match.group(2).strip()
        if key == "from" and is_self_sender(value):
            continue
        found.setdefault(key, value)

    if "from" not in found and markers:
        for match in _FORWARD_HEADER.finditer(text):
            if match.group(1).lower() != "from":
                continue
            value = match.group(2).strip()
            if not is_self_sender(value):
                found["from"] = value
                break
    return found


def is_replyable_forwarded_sender(sender: str) -> bool:
    """A recovered sender is safe to address only with a non-self email."""
    address = parseaddr(sender or "")[1].strip().lower()
    return bool(address) and address not in self_addresses()


def _embedded_message_headers(part: dict) -> dict[str, str]:
    """Extract headers from an attached RFC 822 message before text heuristics."""
    if part.get("mimeType", "").lower() == "message/rfc822":
        candidates = [part] + list(part.get("parts", []) or [])
        for candidate in candidates:
            headers = candidate.get("headers", []) or []
            sender = _header(headers, "From").strip()
            if is_replyable_forwarded_sender(sender):
                return {
                    "from": sender,
                    "subject": _header(headers, "Subject").strip(),
                }
    for sub in part.get("parts", []) or []:
        found = _embedded_message_headers(sub)
        if found:
            return found
    return {}


def _plain_text(part: dict) -> str:
    mime = part.get("mimeType", "")
    body = part.get("body", {})
    data = body.get("data")
    if mime == "text/plain" and data:
        return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
    return "".join(_plain_text(sub) for sub in part.get("parts", []) or [])


def _attachment_names(part: dict) -> list[str]:
    out = []
    filename = (part.get("filename") or "").strip()
    if filename:
        out.append(filename)
    for sub in part.get("parts", []) or []:
        out.extend(_attachment_names(sub))
    return out


def list_messages(query: str = "is:unread newer_than:2d", max_results: int = 25,
                  include_content: bool = False
                  ) -> list[EmailMessage]:
    """List messages matching a Gmail search query (same syntax as the search box)."""
    svc = build_service("gmail", "v1")
    resp = with_retry(lambda: svc.users().messages().list(
        userId="me", q=query, maxResults=max_results).execute())
    out = []
    for ref in resp.get("messages", []):
        def fetch(ref=ref):
            kwargs = {
                "userId": "me",
                "id": ref["id"],
                "format": "full" if include_content else "metadata",
            }
            if not include_content:
                kwargs["metadataHeaders"] = ["From", "Subject", "Date"]
            return svc.users().messages().get(**kwargs).execute()

        msg = with_retry(fetch)
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        labels = msg.get("labelIds", [])
        embedded = _embedded_message_headers(payload) if include_content else {}
        out.append(EmailMessage(
            id=msg["id"], thread_id=msg.get("threadId", ""),
            sender=_header(headers, "From"), subject=_header(headers, "Subject"),
            date=_header(headers, "Date"), snippet=msg.get("snippet", ""),
            unread="UNREAD" in labels, labels=labels,
            attachment_names=_attachment_names(payload) if include_content else [],
            body=_plain_text(payload).strip() if include_content else "",
            forwarded_sender=embedded.get("from", ""),
            forwarded_subject=embedded.get("subject", "")))
    return out


def list_admin_messages(unread_max: int = 20, self_max: int = 30
                        ) -> list[EmailMessage]:
    """Admin inbox: self-forwarded captures first, then ordinary unread mail.

    Self-sent mail is intentionally independent of read state. This recovers
    messages forwarded from the work account even when Gmail rules, previews,
    or another client have already marked them read. Full structure is fetched
    only for this small self-sent slice so raw-data attachment names are visible
    without downloading attachment contents.
    """
    aliases = self_addresses()
    intake_address = os.environ.get(
        "ADMIN_INTAKE_ADDRESS", "you@example.com").strip().lower()
    from_terms = " ".join(f"from:{address}" for address in aliases)
    self_query = (
        f"to:{intake_address} {{{from_terms}}} "
        f"newer_than:{SELF_SENT_LOOKBACK_DAYS}d"
        if len(aliases) > 1
        else f"to:{intake_address} {from_terms} "
             f"newer_than:{SELF_SENT_LOOKBACK_DAYS}d"
    )
    self_sent = list_messages(
        self_query, self_max, include_content=True)
    unread = list_messages(
        "is:unread newer_than:2d", unread_max, include_content=False)

    # Prefer the rich self-sent copy when a message appears in both queries.
    merged = {m.id: m for m in unread}
    merged.update({m.id: m for m in self_sent})
    self_ids = {m.id for m in self_sent}
    return (
        [merged[m.id] for m in self_sent]
        + [m for m in unread if m.id not in self_ids]
    )


def get_message_body(message_id: str) -> str:
    """Full decoded plain-text body of one message (walks multipart parts)."""
    svc = build_service("gmail", "v1")
    msg = with_retry(lambda: svc.users().messages().get(
        userId="me", id=message_id, format="full").execute())

    return _plain_text(msg.get("payload", {})).strip()


def create_draft(to: str, subject: str, body: str, thread_id: str | None = None
                ) -> str:
    """Create a Gmail DRAFT (never sends). Returns the draft id."""
    svc = build_service("gmail", "v1")
    mime = MIMEText(body)
    mime["To"] = to
    mime["Subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    message = {"raw": raw}
    if thread_id:
        message["threadId"] = thread_id
    draft = with_retry(lambda: svc.users().drafts().create(
        userId="me", body={"message": message}).execute())
    return draft.get("id", "")


def format_context(messages: list[EmailMessage]) -> str:
    if not messages:
        return "No matching emails."
    lines = [f"{len(messages)} email(s):"]
    for m in messages:
        flag = "[unread] " if m.unread else ""
        lines.append(f"- {flag}From: {m.sender} | {m.subject or '(no subject)'} "
                     f"| {m.date}\n  {m.snippet}")
    return "\n".join(lines)
