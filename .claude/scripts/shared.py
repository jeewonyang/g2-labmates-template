"""Shared utilities for the Second Brain agent system.

Used by hooks, memory flush, and (later phases) heartbeat/reflection/chat.
Cross-cutting concerns: paths, file locking, retries, atomic writes, and
daily-log appends. Multiple processes write to the same files concurrently -
every daily-log or state write must go through file_lock().
"""

import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
VAULT = REPO_ROOT / "VAULT"
MEMORY = VAULT / "Memory"
DAILY = MEMORY / "daily"
DATA = REPO_ROOT / ".claude" / "data"
STATE_DIR = DATA / "state"
LOG_DIR = DATA / "logs"
TMP_DIR = DATA / "tmp"

TIMEZONE = ZoneInfo("America/Los_Angeles")

# Model for background reasoning (flush, guardrail, heartbeat, reflection,
# drafting). Sonnet by default per the owner - cheaper than Opus, plenty for
# drafting/triage. Override with SECONDBRAIN_MODEL in .env (e.g. "haiku").
AGENT_MODEL = os.environ.get("SECONDBRAIN_MODEL", "sonnet")


def now() -> datetime:
    return datetime.now(TIMEZONE)


def ensure_dirs() -> None:
    for d in (STATE_DIR, LOG_DIR, TMP_DIR, DAILY):
        d.mkdir(parents=True, exist_ok=True)


def log_line(name: str, message: str) -> None:
    """Append a timestamped line to .claude/data/logs/<name>.log. Never raises."""
    try:
        ensure_dirs()
        with open(LOG_DIR / f"{name}.log", "a", encoding="utf-8") as f:
            f.write(f"{now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


@contextmanager
def file_lock(path: Path, timeout: float = 15.0):
    """Cross-process advisory lock via a sidecar .lock file.

    msvcrt on Windows, fcntl on Unix. Blocks up to `timeout` seconds, then
    raises TimeoutError. Lock is released and the handle closed on exit.
    """
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Could not lock {path} within {timeout}s")
                time.sleep(0.2)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def with_retry(fn, *, retries: int = 4, base_delay: float = 1.0,
               exceptions: tuple = (Exception,), on_retry=None):
    """Call fn() with exponential backoff. For external API calls (429/5xx)."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except exceptions as e:
            if attempt == retries:
                raise
            delay = base_delay * (2 ** attempt)
            if on_retry:
                on_retry(attempt + 1, delay, e)
            time.sleep(delay)


def atomic_write_text(path: Path, content: str) -> None:
    """Write to .tmp then os.replace() - a crash never leaves a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, data) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def daily_log_path(date: datetime | None = None) -> Path:
    return DAILY / f"{(date or now()):%Y-%m-%d}.md"


def append_to_daily_log(section_title: str, body: str) -> Path:
    """Append a timestamped section to today's daily log (lock-protected)."""
    ensure_dirs()
    path = daily_log_path()
    entry = f"\n### {section_title} ({now():%H:%M})\n\n{body.rstrip()}\n"
    with file_lock(path):
        is_new = not path.exists()
        with open(path, "a", encoding="utf-8") as f:
            if is_new:
                f.write(f"# {now():%Y-%m-%d}\n")
            f.write(entry)
    return path


def load_env() -> None:
    """Load KEY=VALUE pairs from the repo-root .env into os.environ (no override).

    Background scripts (flush/heartbeat/reflection) need ANTHROPIC_API_KEY from
    .env: some organizations disable Claude subscription auth for headless SDK
    sessions (oauth_org_not_allowed), so API-key auth is required there.
    """
    env_file = REPO_ROOT / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


# ---------- command guardrails (Phase 8) ----------
# Distinct from block-secrets.py (credential files): these patterns catch
# destructive, exfiltrating, or privilege-escalating COMMANDS. Both hooks run
# on every PreToolUse Bash/PowerShell call.

ALLOWED_DOMAINS = (
    "arxiv.org", "api.biorxiv.org", "api.crossref.org", "api.semanticscholar.org",
    "eutils.ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "doi.org",
    "api.github.com", "github.com", "slack.com", "googleapis.com",
    "google.com", "anthropic.com", "localhost", "127.0.0.1",
)

DANGEROUS_BASH_PATTERNS = [
    # destructive - files/disks (never-delete boundary)
    r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+", r"\brm\s+.*\*",
    r"\bdel\s+/[sq]", r"\brmdir\s+/s", r"\brd\s+/s",
    r"remove-item\s+.*(-recurse|-force)", r"\bmkfs", r"\bdd\s+if=",
    r"\bformat\s+[a-z]:", r"\bdiskpart", r"\bcipher\s+/w",
    r"git\s+push\s+.*--force", r"git\s+reset\s+--hard",
    r"git\s+clean\s+-[a-z]*f", r"\btruncate\s+-s\s*0",
    # exfiltration / remote execution
    r"(curl|wget|invoke-webrequest|invoke-restmethod|iwr|irm)\s+[^|]*\|\s*(sh|bash|powershell|iex|python)",
    r"\|\s*(sh|bash)\s*$", r"invoke-expression", r"\biex\b",
    r"(curl|wget)\s+.*(-d|--data|--upload-file|-T)\s",
    r"\bnc(\.exe)?\s+.*\d{1,3}(\.\d{1,3}){3}", r"\bnc\s+-[a-z]*e",
    r"\bscp\s+.*@", r"\bftp\s+",
    r"base64\s+.*(\.env|secret|token|credential)",
    # package installation
    r"\bpip3?\s+install", r"\bnpm\s+install\s+-g", r"\bnpm\s+i\s+-g",
    r"\bwinget\s+install", r"\bchoco\s+install", r"\bbrew\s+install",
    r"\bapt(-get)?\s+install", r"\byum\s+install", r"\bconda\s+install",
    # privilege escalation / system tampering
    r"\bsudo\b", r"\brunas\b", r"chmod\s+777", r"chmod\s+.*\+s",
    r"icacls\s+.*everyone", r"takeown\s+", r"\breg\s+(add|delete)",
    r"schtasks\s+/(create|delete|change)", r"net\s+user\s+.*/add",
    r"new-service", r"sc\s+(create|delete|config)",
    r"set-executionpolicy", r"\battrib\s+.*\+h",
    # shutdown / process killing
    r"\bshutdown\b", r"stop-computer", r"restart-computer",
    r"taskkill\s+/f", r"stop-process\s+.*-force",
]
_DANGEROUS_COMPILED = None

_PATH_PREFIXES = ("/usr/bin/", "/usr/local/bin/", "/bin/", "/sbin/",
                  "c:\\windows\\system32\\", "c:/windows/system32/")


def extract_subshells(command: str) -> list[str]:
    """Recursively pull out $(...) and `...` contents - naive matching is
    bypassable via $(echo rm\\ -rf\\ /)."""
    found, queue = [], [command]
    while queue:
        text = queue.pop()
        for m in re.finditer(r"\$\(([^()]*(?:\([^()]*\)[^()]*)*)\)", text):
            found.append(m.group(1))
            queue.append(m.group(1))
        for m in re.finditer(r"`([^`]+)`", text):
            found.append(m.group(1))
            queue.append(m.group(1))
    return found


def _strip_prefixes(command: str) -> str:
    out = command
    for p in _PATH_PREFIXES:
        out = out.replace(p, "")
    return out


def _non_allowlisted_urls(command: str) -> list[str]:
    urls = re.findall(r"https?://([^/\s\"']+)", command, re.IGNORECASE)
    bad = []
    for u in urls:
        host = u.lower().split("@")[-1].rsplit(":", 1)[0]  # strip creds + port
        # exact host or a dotted subdomain of an allowed domain (NOT a mere
        # suffix - "evil-github.com" must not match "github.com")
        if not any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS):
            bad.append(u)
    return bad


def check_dangerous_command(command: str) -> list[str]:
    """Return reasons this command is dangerous (empty = allowed).
    Checks the command plus every recursively-extracted subshell,
    with binary path prefixes stripped before matching."""
    global _DANGEROUS_COMPILED
    if _DANGEROUS_COMPILED is None:
        _DANGEROUS_COMPILED = [re.compile(p, re.IGNORECASE)
                               for p in DANGEROUS_BASH_PATTERNS]
    reasons = []
    texts = [command] + extract_subshells(command)
    for text in texts:
        text = _strip_prefixes(text.replace("\\ ", " "))
        for rx in _DANGEROUS_COMPILED:
            if rx.search(text):
                reasons.append(rx.pattern)
        if (re.search(r"\b(curl|wget|invoke-webrequest|iwr|irm|invoke-restmethod)\b",
                      text, re.IGNORECASE)):
            bad = _non_allowlisted_urls(text)
            if bad:
                reasons.append(f"outbound call to non-allowlisted host: {bad}")
    return sorted(set(reasons))


def invoked_by() -> str | None:
    """Which Agent SDK entry point spawned this process chain, if any.

    Every SDK entry point (memory_flush, heartbeat, reflection, chat) sets
    CLAUDE_INVOKED_BY before creating its session. SessionEnd/PreCompact hooks
    skip when it's set - otherwise every SDK exit would spawn another flush.
    """
    return os.environ.get("CLAUDE_INVOKED_BY") or None
