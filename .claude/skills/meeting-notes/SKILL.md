---
name: meeting-notes
description: Turn raw meeting notes into a structured, searchable note in the vault, and surface action items. Use when the owner pastes or points to raw notes/transcript from a meeting, says "clean up my notes", "file this meeting", or asks to capture decisions and action items from a discussion.
---

# Meeting Notes

Task #5: keep meeting notes organized and searchable. This skill converts raw
notes (pasted text, a transcript, or a Google Doc) into a structured note in
`VAULT/Memory/meetings/`, then logs action items so the heartbeat can track them.

## Steps

1. **Gather the source.** If the owner pasted text, use it. If they name a Drive
   doc, fetch it: `python .claude/scripts/query.py drive list "name contains '<title>'"`
   then `python .claude/scripts/query.py drive read <file_id> <mime_type>`.

2. **Search for prior context** so the note connects to what came before:
   `python .claude/scripts/memory_search.py "<topic or project>"`. Reference the
   relevant `projects/<project>.md` or earlier meeting if one exists.

3. **Write the note** to `VAULT/Memory/meetings/YYYY-MM-DD_<slug>.md` (today's
   date unless the meeting was another day; slug = short kebab topic). Use this
   structure:

   ```markdown
   ---
   type: meeting
   date: YYYY-MM-DD
   attendees: [names]
   project: <project or "">
   tags: [topic tags]
   ---

   # <Meeting title>

   ## Summary
   2-4 sentences: what this meeting was about and the outcome.

   ## Decisions
   - Decision + one line of why.

   ## Action Items
   - [ ] <action> - owner: <name>, due: <date if stated>

   ## Notes
   Cleaned-up narrative or bullets. Keep substance, drop filler.

   ## Open Questions
   - Anything unresolved to follow up.
   ```

4. **Log action items** to today's daily log so they enter the tracking loop.
   Append a "Meeting action items" section listing each `- [ ]` item with the
   meeting file linked. (Use the daily-log append pattern; the heartbeat and
   reflection read from there.)

5. **Update project status** if the meeting changed it: reflect decisions or
   new action items into `VAULT/Memory/projects/<project>.md`.

6. **Confirm** to the owner: where you filed it, the key decisions, and the action
   items with owners/dates. Note anything ambiguous you had to guess.

## Rules

**The rules between the `shared:extraction` markers are shared with the scheduled
`admin.meeting_followup` job** - `.claude/scripts/skill_rules.py` splices that block verbatim into
the job's prompt, so this skill and the job follow one text. Edit them only
there, and keep the block free of chat-only instructions (commands, tools).

<!-- shared:extraction -->
- Never invent a date, a name, an attendee, a decision, or an owner. A blank
  field gets asked about; a wrong one gets acted on.
- Transcribed speech is noisy. If a name or date is garbled, leave it out rather
  than guessing at what was probably said.
- Preserve technical specifics (numbers, protocol details, gene/construct
  names) - they matter for a researcher and for later search.
<!-- /shared:extraction -->

In a chat pass, anything unclear goes under Open Questions rather than being
fabricated.
