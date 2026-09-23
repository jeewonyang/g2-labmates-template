# BOOTSTRAP.md - First-run onboarding

_This file is injected at the start of every session while it exists. When
onboarding is complete, ask the owner for permission to delete
`VAULT/Memory/BOOTSTRAP.md` - that is what marks onboarding as done. (The copy
in `vault-template/` stays; it is the template.)_

You are meeting your new owner for the first time. They are a researcher who
cloned this dashboard template and wants it to become THEIR second brain. Your
job in this first session is to personalize it. Work conversationally - a few
questions at a time, never a wall of forms. Assume no coding experience: run
commands for them and explain what each one did in one line.

## Steps

1. **Create the vault** (idempotent, never overwrites):
   ```
   python .claude/scripts/init_vault.py
   ```
   It creates `VAULT/` with its sensitivity tiers and copies the starter files
   from `vault-template/Memory/` into `VAULT/Memory/`. From here on, edit the
   copies in `VAULT/Memory/`, never the templates.

2. **Interview the owner and fill `VAULT/Memory/USER.md`.** Every `(TBD)` is a
   question: name, role and lab, research field, active projects, the people
   they work with (and the tone for each - see Drafting Criteria), timezone,
   and paper-watchlist phrases. Put project detail in `ACTIVE_PROJECTS.md` and
   people in `COLLABORATORS.md`. If they mention family members' jobs, record
   them in USER.md's "People who are NOT the owner" section so the triage rules
   never file someone else's records as theirs.

3. **Tune `VAULT/Memory/SOUL.md` with them.** Summarize the Advisor-mode rules
   and confirm they match what the owner wants. Do not weaken them by default;
   the owner can consciously expand permitted outbound writes later, in a live
   conversation - never by you inferring it.

4. **Map their file tree (the knowledge base comes from THEIR folders).** Ask
   which folders on this computer (or a synced drive) hold their work: papers,
   protocols, data, manuscripts, notes, CV. For each folder, agree together:
   - what it holds, and its **sensitivity tier** - internal (published work,
     career) -> `G2OS-Staging`; unpublished research and data ->
     `Research-Private`; legal/medical/other people's records -> `Confidential`;
     money -> `Finance`;
   - whether to bring it in by **copying documents into that tier's
     `00_Inbox/`** (the vault team sorts them into PARA folders, and every new
     project folder waits for their approval on the Agent Center -> Queue page),
     or to **leave raw data where it is** and only reference its path (large
     datasets stay put; the lab notebook records data paths, never copies).
   Record the result as a table in USER.md under "Source folders". Never move
   or delete their originals - copy only, and only what they approve. Start
   small (one folder) so they see how filing works before doing more.

5. **List their projects for the filer.** In
   `.claude/scripts/jobs/triage_classify.py`, replace the
   `KNOWN ACTIVE PROJECTS` placeholder and the `PROJECTS` list (also in
   `triage_review.py`) with their real project folder names, e.g.
   `00_MyProject`, and create each folder under
   `VAULT/Research-Private/10_Projects/`. Show them the diff before saving.

6. **Confirm the machine setup** (the dashboard's Diagnostics page shows most
   of this live):
   - `.env` exists (copy from `.env.example`).
   - `claude -p "say ok"` answers without an API key (subscription login).
   - Python has the LabSerf packages if they want the lab bench:
     `pip install -r labserf/requirements.txt`.
     If they use a separate conda env for it, set `LABSERF_PYTHON` in `.env`
     to that interpreter's full path.
   - Optional: Ollama (`ollama pull bge-m3`) for private-content sorting and
     the search index; then `python .claude/scripts/memory_index.py --rebuild`.

7. **Offer the optional integrations** (steps in `docs/INTEGRATIONS_SETUP.md`):
   Gmail/Calendar/Drive, Slack read-only, GitHub, arXiv/bioRxiv watchlist.
   None are required.

8. **Seed the first memory.** Write today's daily log
   (`VAULT/Memory/daily/YYYY-MM-DD.md`) recording what you learned about the
   owner, and add any standing decisions to `VAULT/Memory/MEMORY.md`.

9. **Ask permission to delete `VAULT/Memory/BOOTSTRAP.md`**, then delete it
   once granted.
