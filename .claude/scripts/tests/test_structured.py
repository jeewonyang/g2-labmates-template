"""The structured-output extractor every runtime parses a model's final
message with, and the raw-message keep on failure.

Run: python .claude/scripts/tests/test_structured.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtimes import structured  # noqa: E402

CHECKS = 0
FAILED = []


def check(cond, msg):
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILED.append(msg)
        print(f"  FAIL  {msg}")


SCHEMA = {"required": ["fit_score", "email_body", "cv_markdown"]}
REAL = json.dumps({
    "fit_score": 4,
    "email_body": "Dear Dr. Baker, {a brace in prose}",
    "cv_markdown": "# CV\n- Postdoc, Example University {2021-}",
})


def test_shapes():
    for label, text in {
        "pure object": REAL,
        "code fence": "```json\n" + REAL + "\n```",
        "prose before": "Here is the packet you asked for:\n\n" + REAL,
        "prose after, with braces": REAL + "\n\nNote: the posting {could not be fetched}.",
        "small object first": '{"status": "self-check passed", "identity_check_ok": true}\n' + REAL,
        "small object after": REAL + '\n{"sources": []}',
        "two prose wraps": "Packet:\n" + REAL + "\nDone {see above}.",
    }.items():
        data, err = structured.extract_json(text, SCHEMA)
        check(err == "" and data and data.get("fit_score") == 4
              and data.get("cv_markdown", "").startswith("# CV"), f"{label}: real object chosen")


def test_baker_shape():
    """The 2026-09-18 failure: a valid ~170-char object, then more text. The
    old first-brace-to-last-brace slice raised `Extra data`."""
    preface = json.dumps({"note": "Reading the master CV and the Baker lab posting before "
                                  "writing; the sources list follows the packet.", "ok": True})
    check(len(preface) > 100, "preface is a realistic size")
    data, err = structured.extract_json(preface + "\n\n" + REAL, SCHEMA)
    check(err == "" and data.get("email_body", "").startswith("Dear"), "preface object is skipped")


def test_no_schema_picks_largest():
    data, err = structured.extract_json('{"a": 1}\n' + REAL)
    check(err == "" and "cv_markdown" in data, "largest object wins without a schema")


def test_failures_keep_the_prefix():
    _, err = structured.extract_json("no json here at all", SCHEMA)
    check(err == "no JSON object found in the final message", "no object → no-object message")
    _, err = structured.extract_json('{"fit_score": "unterminated', SCHEMA)
    check(err.startswith("structured output did not parse"), "broken object → parse-failure prefix")
    _, err = structured.extract_json("[1, 2, 3]", SCHEMA)
    check(err.startswith("no JSON object") or err.startswith("structured output"), "array is not an object")
    _, err = structured.extract_json("", SCHEMA)
    check(err, "empty text fails")


def test_keep_raw():
    with tempfile.TemporaryDirectory(dir=structured.LOG_DIR.parent) as tmp:
        saved, structured.RAW_DIR = structured.RAW_DIR, Path(tmp) / "structured"
        try:
            err = structured.keep_raw("claude", "the model said {x", "structured output did not parse: Extra data",
                                      job_id="job_abc/../evil")
            check(err.startswith("structured output did not parse: Extra data (raw message kept at "),
                  "error names the kept file")
            files = list(structured.RAW_DIR.glob("*.txt"))
            check(len(files) == 1 and "claude-job_abc" in files[0].name and ".." not in files[0].name,
                  "one sanitized file per failure")
            check(files[0].read_text(encoding="utf-8").endswith("the model said {x"), "raw text kept verbatim")
            rel = err.split("kept at ", 1)[1].rstrip(")")
            check((structured.REPO_ROOT / rel).is_file(), "the named path is repo-relative and exists")
        finally:
            structured.RAW_DIR = saved


def main():
    for fn in (test_shapes, test_baker_shape, test_no_schema_picks_largest,
               test_failures_keep_the_prefix, test_keep_raw):
        print(fn.__name__)
        fn()
    print(f"\n{CHECKS - len(FAILED)}/{CHECKS} checks passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
