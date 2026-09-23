"""Local-only protection for credentials and oversized/raw archive material.

Only a coarse category leaves this module. Matched content and filenames are
never logged.
"""

from __future__ import annotations

import re
from pathlib import Path

from shared import REPO_ROOT
from triage import extract as extractor

MAX_CLOUD_METADATA_BYTES = 50 * 1024 * 1024
RAW_SUFFIXES = {
    ".raw", ".bin", ".dat", ".npy", ".npz", ".h5", ".hdf5", ".mat",
    ".nd2", ".czi", ".lif", ".oir", ".ims", ".dcm", ".nii", ".bam",
    ".fastq", ".fq", ".fcs",
}
_SECRET_SUFFIXES = {".env", ".pem", ".key", ".p12", ".pfx", ".kdbx"}
_CREDENTIAL_NAME = re.compile(
    r"(?i)(?:^|[^a-z0-9])(?:passwords?|passwd|credentials?|api[-_ ]?keys?|"
    r"recovery[-_ ]?codes?|seed[-_ ]?phrase|private[-_ ]?key|id_rsa|"
    r"auth[-_ ]?tokens?|secrets?)(?:[^a-z0-9]|$)"
)
_CREDENTIAL_CONTENT = re.compile(
    r"(?i)(?:password|passwd|api[-_ ]?key|client[-_ ]?secret|access[-_ ]?token|"
    r"recovery[-_ ]?code|seed[-_ ]?phrase|private[-_ ]?key)"
    r"\s*(?::|=)\s*\S+"
)
_PAYMENT_CARD_NAME = re.compile(
    r"(?i)(?:credit|debit)[-_ ]?card|card[-_ ]?(?:number|details)|\bcvv\b|\bcvc\b"
)
_PAYMENT_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_PAYMENT_CARD_CODE = re.compile(
    r"(?i)\b(?:cvv2?|cvc2?|security[-_ ]?code)\b\s*(?::|=)\s*\d{3,4}\b"
)


def _luhn(value: str) -> bool:
    digits = [int(ch) for ch in value if ch.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _contains_payment_card(text: str) -> bool:
    if _PAYMENT_CARD_CODE.search(text):
        return True
    return any(_luhn(match.group(0))
               for match in _PAYMENT_CARD_CANDIDATE.finditer(text))


def category(path_value: str | Path) -> str | None:
    """Return a protected category, using only local inspection."""
    path = Path(path_value)
    if not path.is_absolute():
        path = REPO_ROOT / path

    normalized = str(path).replace("\\", "/")
    if path.suffix.lower() in _SECRET_SUFFIXES or _CREDENTIAL_NAME.search(path.name):
        return "credentials"
    card_named = bool(_PAYMENT_CARD_NAME.search(path.name))

    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if "/archive/" in normalized.casefold() and (
        size >= MAX_CLOUD_METADATA_BYTES or path.suffix.lower() in RAW_SUFFIXES
    ):
        return "large-raw-data"

    text, _method = extractor.extract(path)
    if text and _CREDENTIAL_CONTENT.search(text):
        return "credentials"
    if (text and _contains_payment_card(text)) or (card_named and not text):
        return "payment-card"
    return None


def protected_proposal(original: dict, protection: str) -> dict:
    """Return a terminal no-copy decision for the append-only ledger."""
    if protection == "credentials":
        reason = "Credential material remains in place"
    elif protection == "large-raw-data":
        reason = "Large/raw archive data remains in place"
    elif protection == "payment-card":
        reason = "Sensitive payment-card material remains in place"
    else:
        reason = "Ambiguous classification remains in place"
    return {
        **(original or {}),
        "vault": "leave-in-inbox",
        "bucket": "none",
        "project": None,
        "folder": None,
        "folder_mode": "bucket-root",
        "folder_rationale": "Protected locally by deterministic policy",
        "reason": reason,
        "actions": [],
        "protection": protection,
    }
