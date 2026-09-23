---
name: paper-digest
description: Fetch new research papers matching the owner's watchlist, rank them by relevance to their active projects, and write a dated digest to the vault. Use when they say "any new papers", "check the literature", "paper digest", or when the heartbeat runs the daily papers check.
---

# Paper Digest

Task #6: monitor up-to-date research papers relevant to the owner's projects.
This skill fetches new matches, ranks them against their active work, and writes a
readable digest to `VAULT/Memory/research/`.

## Steps

1. **Fetch new papers** matching the watchlist in USER.md:
   `python .claude/scripts/query.py papers new --json`
   (Returns only papers not seen before; state is tracked automatically.)
   - If the watchlist is empty/TBD, tell the owner their `## Paper Watchlist` in
     `VAULT/Memory/USER.md` needs keywords first, and stop.
   - For an ad-hoc topic instead: `query.py papers search "<phrase>" --json`.

2. **Load project context** to rank by relevance: read the "Active Projects"
   section of `VAULT/Memory/MEMORY.md` and any `projects/*.md`. Optionally
   `memory_search.py "<paper topic>"` to see if a paper connects to past notes.

3. **Rank and filter.** Order papers by how directly they bear on an active
   project. Drop clear false positives (keyword coincidences unrelated to their
   work) - note how many you dropped rather than silently hiding them.

4. **Write the digest** to `VAULT/Memory/research/YYYY-MM-DD_digest.md`:

   ```markdown
   ---
   type: paper-digest
   date: YYYY-MM-DD
   count: <n kept>
   ---

   # Paper digest - YYYY-MM-DD

   ## Highly relevant
   ### <title>
   - Authors, date, link
   - **Why it matters to you:** 1-2 sentences tying it to <project>.

   ## Possibly relevant
   (same format, lighter)

   ## Filtered out
   <n> off-topic matches dropped (e.g. "<term>" hit unrelated fields).
   ```

5. **Summarize** to the owner: the top 1-3 papers and why, plus where the full
   digest is. Keep it short - they can open the file for the rest.

## Rules

**The rules between the `shared:relevance` markers are shared with the scheduled
`research.lit_review` job** - `.claude/scripts/skill_rules.py` splices that block verbatim into
the job's prompt, so this skill and the job follow one text. Edit them only
there, and keep the block free of chat-only instructions (commands, tools).

<!-- shared:relevance -->
- Judge relevance against what they are actually doing now (their active
  projects), not against the field in general.
- Judge relevance honestly. Most papers are low. Inflating relevance makes the
  whole digest worthless because they stop trusting it.
- Never claim a paper says something you have not read. Do not invent results,
  numbers, or claims not present in the abstract; if judging would need the
  full text, say so rather than guess.
<!-- /shared:relevance -->

- Advisor mode: this only reads and writes to the vault - it never emails or
  shares anything externally.
