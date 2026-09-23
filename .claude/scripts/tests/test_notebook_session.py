"""The session auto-logger: digest, skip rules, project match, dedupe, install.

Run: python .claude/scripts/tests/test_notebook_session.py

Synthetic transcripts in a temp dir; a temp projects root with the database
link off; the model call is replaced; install writes a temp settings file.
Nothing touches the real vault, dev.db, or ~/.claude.
"""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))

import lab_notebook as nb  # noqa: E402
import notebook_session as ns  # noqa: E402
import session_digest as sd  # noqa: E402

CHECKS = 0
FAILED = []


def check(cond, msg):
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILED.append(msg)
        print(f"  FAIL  {msg}")


def transcript(tmp: Path, *, cwd="D:/code/alpha-fit", prompt="Fit the Hill model to plate 3",
               tools=(), models=("claude-opus-5-5",), sid="11111111-aaaa", name="t.jsonl") -> Path:
    lines = [{"type": "user", "sessionId": sid, "cwd": cwd, "timestamp": "2026-09-22T10:00:00Z",
              "message": {"role": "user", "content": prompt}},
             {"type": "user", "sessionId": sid, "cwd": cwd, "isMeta": True,
              "message": {"role": "user", "content": "<local-command-caveat>x</local-command-caveat>"}},
             {"type": "user", "sessionId": sid, "cwd": cwd,
              "message": {"role": "user", "content": "<system-reminder>ignore</system-reminder>Also plot it"}}]
    for model in models:
        lines.append({"type": "assistant", "sessionId": sid, "cwd": cwd,
                      "timestamp": "2026-09-22T11:00:00Z",
                      "message": {"role": "assistant", "model": model, "content": [
                          {"type": "text", "text": "EC50 = 1.2 uM across 3 plates."},
                          *[{"type": "tool_use", "name": t[0], "input": t[1]} for t in tools]]}})
    lines.append({"type": "user", "sessionId": sid, "cwd": cwd,
                  "message": {"role": "user", "content": [
                      {"type": "tool_result", "content": "SECRET FILE CONTENT"}]}})
    path = tmp / name
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return path


WORK = (("Read", {"file_path": "D:/data/Alpha/plate3.csv"}),
        ("Write", {"file_path": "D:/code/alpha-fit/out/params.csv"}),
        ("Bash", {"command": "python fit.py --data D:/data/Alpha/plate3.csv"}))
PROJECTS = [{"code": "Alpha", "folder": "00_Alpha"}, {"code": "Beta", "folder": "01_Beta"},
            {"code": "Binder", "folder": "03_Binder"}]


def test_digest(tmp):
    d = sd.digest(transcript(tmp, tools=WORK, models=("claude-opus-5-5", "claude-sonnet-5",
                                                      "<synthetic>")))
    check(d["session_id"] == "11111111-aaaa" and d["cwd"] == "D:/code/alpha-fit", "ids from the transcript")
    check(d["models"] == ["claude-opus-5-5", "claude-sonnet-5"],
          f"models in order, synthetic dropped: {d['models']}")
    check(d["prompts"] == ["Fit the Hill model to plate 3", "Also plot it"],
          f"their prompts only: meta and reminders stripped: {d['prompts']}")
    check(d["read_paths"] == ["D:/data/Alpha/plate3.csv"]
          and d["written_paths"] == ["D:/code/alpha-fit/out/params.csv"], "paths by tool kind")
    text = sd.conversation(d)
    check("SECRET FILE CONTENT" not in text and "SECRET" not in json.dumps(d),
          "tool results never enter the digest")
    check(text.index("USER: Fit") < text.index("ASSISTANT: EC50"), "turns keep their order")
    missing = sd.digest(tmp / "nope.jsonl")
    check("error" in missing and missing["models"] == [], "a missing transcript is data, not a crash")
    check(sd.transcript_dir(r"C:\Users\x\Documents\G2\.claude\worktrees\a-b").name
          == "C--Users-x-Documents-G2--claude-worktrees-a-b", "Claude Code's transcript folder naming")


def test_decide(tmp):
    decide = lambda d, **kw: ns.decide(d, projects=PROJECTS, overrides=kw.get("o", {}),  # noqa: E731
                                       active=kw.get("active"))
    d = sd.digest(transcript(tmp, tools=WORK))
    v = decide(d)
    check(v["log"] and v["project"] == "Alpha", f"a project segment in the data paths matches: {v}")
    check(not decide(d, active={"Beta"})["log"], "an inactive project is not logged")
    thin = sd.digest(transcript(tmp, tools=WORK[:1], name="thin.jsonl"))
    check("too little work" in decide(thin)["reason"], "reading one file is not a session to log")
    filed = sd.digest(transcript(tmp, tools=WORK + (("Bash", {
        "command": "python ~/Documents/G2/.claude/scripts/lab_notebook.py write --file e.json"}),),
        name="filed.jsonl"))
    check("already filed" in decide(filed)["reason"], "a session that used the skill is not logged twice")
    job = sd.digest(transcript(tmp, tools=WORK, cwd=str(Path.home() / ".claude" / "jobs" / "x"),
                               name="job.jsonl"))
    check("background job" in decide(job)["reason"], "background-job sessions are skipped")
    notes = sd.digest(transcript(tmp, cwd="D:/code/g2", tools=(
        ("Write", {"file_path": "V/10_Projects/00_Alpha/04_Notebook/EXP-001_Alpha_2026-09-21.md"}),
        ("Bash", {"command": "ls"}), ("Bash", {"command": "ls"}), ("Bash", {"command": "ls"})),
        name="notes.jsonl"))
    check(not decide(notes)["log"], "touching only notebook entries is not project work")
    repo = sd.digest(transcript(tmp, cwd="D:/code/hydro", tools=(
        ("Write", {"file_path": "D:/code/hydro/sim.py"}),), name="repo.jsonl"))
    check(not decide(repo)["log"], "an unmapped repo matches nothing")
    check(decide(repo, o={"D:/code/hydro": "Binder"}).get("project") == "Binder",
          "notebook-repos.json maps a repo not named after its project")
    tie = sd.digest(transcript(tmp, cwd="D:/x", tools=(
        ("Write", {"file_path": "D:/Alpha/a.py"}), ("Write", {"file_path": "D:/Beta/b.py"})),
        name="tie.jsonl"))
    check("ambiguous" in decide(tie)["reason"], "a tie is skipped, never guessed")


def test_run(tmp):
    root = tmp / "projects"
    (root / "00_Alpha").mkdir(parents=True)
    saved = (nb.PROJECTS_ROOT, nb.DB, nb.ARCHIVE_ROOT, ns.STATE_FILE, ns.OVERRIDES_FILE)
    nb.PROJECTS_ROOT, nb.DB = root, root / "no.db"
    nb.ARCHIVE_ROOT = root / "90_Archive"
    ns.STATE_FILE, ns.OVERRIDES_FILE = tmp / "state.json", tmp / "none.json"
    calls = []

    def fake_run(prompt, **kw):
        calls.append((prompt, kw))
        return SimpleNamespace(ok=True, model="claude-sonnet-5", error="", data={
            "name": "Hill fit, plate 3", "summary": "EC50 1.2 uM.", "outcome": "positive",
            "prompt_summary": "Fit the Hill model to plate 3 and plot it.",
            "introduction": "i", "objective": "o",
            "materials_methods": "### Pipeline\n\n```mermaid\nflowchart LR\n  a[(csv)] --> b[fit]\n```",
            "result": "EC50 = 1.2 uM (3 plates)",
            "conclusion": "### Discussion\n\nd\n\n### Takeaway\n\nt", "next_steps": ["Plate 4"],
            "input_path": "D:/data/Alpha/plate3.csv", "result_path": "C:/invented/path.csv"})

    import runtimes.claude_rt as rt
    real = rt.run
    rt.run = fake_run
    try:
        path = transcript(tmp, tools=WORK, name="run.jsonl")
        out = ns.run(str(path))
        check(out.get("entry") and out["project"] == "Alpha", f"a matched session is filed: {out}")
        prompt, kw = calls[0]
        check(kw.get("disallowed_tools") and "Read" in kw["disallowed_tools"]
              and kw.get("system_mode") == "replace", "the drafting call has every tool denied")
        check("SECRET" not in prompt and "untrusted" in prompt, "the prompt carries no tool output")
        entry = root / "00_Alpha" / "04_Notebook" / "EXP-001_Alpha_2026-09-22.md"
        fm, body = nb.parse_frontmatter(entry.read_text(encoding="utf-8"))
        check(nb.check_file(entry) == [], f"the auto entry passes the linter: {nb.check_file(entry)}")
        check(fm["ai_model"] == "claude-opus-5-5" and fm["session_id"] == "11111111-aaaa"
              and fm["logged_by"] == "auto" and fm["status"] == "draft"
              and fm["assay"] == "computational",
              "model, session, logged_by, draft and assay are set by code")
        check(fm["prompt_summary"].startswith("Fit the Hill"), "the summarized prompt is recorded")
        check(fm["input_path"] == "D:/data/Alpha/plate3.csv", "a touched input path is kept")
        check(fm["result_path"].startswith("not recorded"),
              f"an invented result path is refused: {fm['result_path']}")
        check("drafted automatically by claude-sonnet-5" in body, "the entry says it was auto-drafted")
        ns.run(str(path))
        notebook = root / "00_Alpha" / "04_Notebook"
        check(sorted(p.name for p in notebook.glob("*.md")) == ["EXP-001_Alpha_2026-09-22.md"],
              "a resumed session rewrites its entry instead of filing a second")
        check(len(list((notebook / ".history").glob("*.md"))) == 1, "and keeps the old version")
        state = json.loads(ns.STATE_FILE.read_text(encoding="utf-8"))
        check("11111111-aaaa" in state, "each logged session is recorded in state")
    finally:
        rt.run = real
        nb.PROJECTS_ROOT, nb.DB, nb.ARCHIVE_ROOT, ns.STATE_FILE, ns.OVERRIDES_FILE = saved


def test_install(tmp):
    settings = tmp / "settings.json"
    existing = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "orca"}]}]},
                "theme": "dark"}
    settings.write_text(json.dumps(existing), encoding="utf-8")
    g2 = Path("C:/Users/x/Documents/G2")
    check(ns.install_hook(settings, g2) == "registered", "first install registers")
    check(ns.install_hook(settings, g2) == "already registered", "install is idempotent")
    data = json.loads(settings.read_text(encoding="utf-8"))
    check(data["theme"] == "dark" and data["hooks"]["Stop"] == existing["hooks"]["Stop"],
          "their other settings and hooks are kept")
    cmds = [h["command"] for g in data["hooks"]["SessionEnd"] for h in g["hooks"]]
    check(len(cmds) == 1 and "notebook_session.py' hook" in cmds[0] and "if [ -f" in cmds[0],
          f"one guarded SessionEnd command: {cmds}")
    check(len(list(tmp.glob("settings.json.bak-*"))) == 1, "the old settings are backed up first")
    skills = tmp / "skills"
    target = tmp / "g2" / ".claude" / "skills" / "lab-notebook"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("x", encoding="utf-8")
    check(ns.link_skill(skills, tmp / "g2") == "linked", "the skill is linked")
    check((skills / "lab-notebook" / "SKILL.md").read_text(encoding="utf-8") == "x",
          "the user-level skill reads the repo's file, not a copy")
    check(ns.link_skill(skills, tmp / "g2") == "already linked", "linking is idempotent")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        for fn in (test_digest, test_decide, test_run, test_install):
            sub = Path(tmp) / fn.__name__
            sub.mkdir()
            fn(sub)
    print(f"{CHECKS - len(FAILED)}/{CHECKS} checks passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
