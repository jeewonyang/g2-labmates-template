"""Pull the structured result out of a model's final message - and keep the
message when that fails.

Every runtime asks a job's model for "ONLY a JSON object matching this
schema", and every runtime then has to cope with what actually comes back.
The Claude CLI path is the loose one: it runs an agent with tools, and the
final message can carry the object inside code fences, after a sentence, or
next to a second, smaller object (a status note, a sources list, a
"self-check" the model wrote before the real answer). The first parser took
the text from its first `{` to its last `}` and handed that to json.loads,
which is exactly wrong for "small object, then the real one": the decoder
finishes the small object and reports `Extra data` - the 2026-09-18 Baker lab
assemble failure, twenty minutes of opus thrown away over a formatting slip.

`extract_json` instead decodes every object it can find at top level, then
picks the one that carries the most of the schema's required keys (largest
wins a tie). No model is asked to "repair" the output: a second model call
could invent a field, and for a CV that is worse than failing.

`keep_raw` writes the unparseable message to `.claude/data/logs/structured/`
and names the file in the error. The ledger keeps only the one-line error, so
until now a parse failure left nothing to read - "the details are on /ops"
pointed at the same sentence.
"""

import json
import re

from shared import LOG_DIR, REPO_ROOT, now

RAW_DIR = LOG_DIR / "structured"
_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _candidates(text: str) -> list[tuple[dict, int, int]]:
    """Every JSON object decodable at top level: (obj, start, end)."""
    dec = json.JSONDecoder()
    found: list[tuple[dict, int, int]] = []
    i = 0
    while True:
        i = text.find("{", i)
        if i == -1:
            return found
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            found.append((obj, i, end))
            i = end          # objects nested inside a decoded one are not candidates
        else:
            i += 1


def _wanted_keys(schema: dict | None) -> list[str]:
    if not isinstance(schema, dict):
        return []
    req = schema.get("required")
    if isinstance(req, list) and req:
        return [str(k) for k in req]
    props = schema.get("properties")
    return [str(k) for k in props] if isinstance(props, dict) else []


def extract_json(text: str, schema: dict | None = None) -> tuple[dict | None, str]:
    """(object, "") or (None, error). The error text keeps the historical
    "structured output did not parse" prefix - failover matches on it to
    decide that a parse failure never reroutes a job."""
    text = text or ""
    try:
        whole = json.loads(text)
        if isinstance(whole, dict):
            return whole, ""
    except json.JSONDecodeError:
        pass
    found = _candidates(text)
    if not found:
        start = text.find("{")
        if start == -1:
            return None, "no JSON object found in the final message"
        try:
            json.JSONDecoder().raw_decode(text, start)
        except json.JSONDecodeError as e:
            return None, f"structured output did not parse: {e}"
        return None, "structured output did not parse: no object at top level"
    keys = _wanted_keys(schema)

    def score(item):
        obj, start, end = item
        return (sum(1 for k in keys if k in obj), end - start)

    best = max(found, key=score)
    return best[0], ""


def keep_raw(runtime: str, text: str, error: str, *, job_id: str | None = None) -> str:
    """Save the message that failed to parse; return the error with the path
    appended. Never raises - a logging failure must not mask the real one."""
    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        stamp = now().strftime("%Y%m%d-%H%M%S")
        tag = _SAFE.sub("-", f"{runtime}-{job_id or 'run'}")[:80]
        path = RAW_DIR / f"{stamp}-{tag}.txt"
        path.write_text(f"# {error}\n\n{text or ''}", encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        return f"{error} (raw message kept at {rel})"
    except (OSError, ValueError):
        return error
