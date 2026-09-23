---
name: draft-replies
description: Scan the owner's incoming Gmail, work Outlook, and Slack for messages that need their reply, and write draft responses to the vault in their voice. Also the fast incremental Slack catch-up (only messages since the last scan). Use when they say "draft replies", "check my messages", "what needs a response", "any replies to draft", "/draft-replies", "slack catch-up", "what's new on slack", "catch me up on slack", "check slack since last time", or "/slack-catchup". On-demand (Advisor mode - drafts only, never sends or posts).
---

# Draft Replies

On-demand pass over the owner's inboxes. Gather messages that need a reply, draft
responses in their voice, and write them to `VAULT/Memory/drafts/active/`. This is
**Advisor mode**: draft only, never send or post anything.

Runs interactively (you, in this session), so Gmail/Slack use the Python
wrappers and Outlook uses the Microsoft 365 MCP tools directly.

**One skill, two modes** (merged 2026-09-22; `slack-catchup` is now an alias):

- **Full sweep** (default) - Gmail + Outlook + Slack, steps 1-6 below.
- **Slack catch-up** - "slack catch-up", "what's new on slack": Slack only,
  only what arrived since the last scan. Do step 1, then the Slack part of
  step 2, then steps 3-6. Skip Gmail and Outlook.

**The drafting rules are shared with the scheduled `draft.reply` job.** The block
between the `shared:drafting` markers in step 3 is spliced verbatim into that
job's prompt (`.claude/scripts/skill_rules.py`), so the 05:00 run and this skill
follow one text. Edit the rules there and only there; keep the block free of
chat-only instructions (commands, tools), because a job reads it too.

## 1. Load context

- Read `VAULT/Memory/USER.md` — especially **Drafting Criteria** and **Team**
  (who counts as important; Dr. Ada Advisor = urgent).
- Default scope: messages from roughly the last 3 days unless they say otherwise.

## 2. Gather

**Gmail (personal, you@example.com)** - full sweep only:
```
python .claude/scripts/query.py gmail admin --json
```
This includes ordinary unread mail plus messages sent/forwarded by the owner to
their intake account even if already read. For self-forwarded mail, recover the
original `From:` header and judge whether that underlying message needs a reply;
address the draft to the original sender, never to the owner.

**Slack (read-only) - new messages since the last scan, independent of read state:**
```
python .claude/scripts/query.py slack since --json
```
- Returns incoming DMs and group DMs newer than the committed checkpoint in
  `.claude/data/state/slack-scan-state.json`, their own messages excluded. First
  run ever (no checkpoint): the last 2 days; add a number to widen it
  (`slack since 3 --json`).
- `since` stashes the scan-start time WITHOUT advancing the checkpoint;
  `mark-scanned` (step 6) promotes it. An interrupted run never loses
  messages - the window is re-scanned next time and deduped against drafts.
- **Scope / speed.** The default is DMs + group DMs only (~100 conversations,
  the reply-critical set). Add `--all` to also sweep channel broadcasts and
  @-mentions - complete but slow (Slack rate-limits history; there is no bulk
  "everything unread" endpoint for user tokens). Use `--all` only when they
  explicitly want channel catch-up.
- If stderr prints `WARNING: N conversations could not be fetched` the scan was
  throttled and is INCOMPLETE: do not advance the checkpoint; tell them, wait a
  minute, and rerun.
- If Slack reports "not configured", the `slack.env` token is missing - tell
  them and skip Slack.
- Empty array and no warning: report "nothing new since <last scan>" and still
  advance the checkpoint (step 6).
- The token lacks `search:read`. With it, one `search.messages after:<date>`
  call would replace the slow `--all` sweep; mention they can re-authorize the
  Slack app with that scope (docs/INTEGRATIONS_SETUP.md).

Channel broadcasts (lab supplies, safety notices, forwarded opportunities) are
usually FYI: surface anything important in the report (Dr. Ada Advisor, career
opportunities per USER.md) but draft only under the rules in step 3.

**Outlook (work, you@work.example) via MCP** - full sweep only:
- `outlook_email_search` with `folderName: "Inbox"`, `order: "newest"`,
  `afterDateTime: "3 days ago"`, `limit: 25`.
- For candidates, fetch the body with `read_resource` on the returned URI.
- To tell whether they already replied, `outlook_email_search` with
  `folderName: "Sent Items"` and the same `afterDateTime`, and match by
  subject/thread. Skip anything they're already answered.

## 3. Decide what needs a reply, and how it sounds

<!-- shared:drafting -->
RELATIONSHIP CLASSIFICATION AND VOICE
Classify the sender into exactly one relationship group before drafting. Use
the message plus USER.md/COLLABORATORS.md when useful. Search prior draft
frontmatter for this recipient and reuse an established classification unless
the current message or a user correction clearly supersedes it. User-confirmed anchors:
- Dr. Ada Advisor = Mentor/PI.
- Sam Student = Mentee.
For a genuinely new person, infer from evidence: senior advisor/PI/mentor ->
Mentor/PI; someone the owner supervises or mentors -> Mentee; an external project
or professional partner -> Collaborator; a peer, labmate, coworker, or friend ->
Colleague. If evidence is insufficient, use Collaborator as the respectful
default and say so in the relationship rationale.

Set the register from the group:
- Mentor/PI: polite and appreciative.
- Mentee: casual and warm.
- Collaborator: formal and warm.
- Colleague: casual and fun, while still clear and work-appropriate.

Relationship tone is the baseline, not permission to ignore the situation.
Serious, sensitive, corrective, deadline-driven, or scientific content should
become more restrained and precise even for a mentee or colleague.
Never make a serious message playful.

Across every group: be direct, use contractions when natural, and put the point
in the first sentence. Never use "I hope this email finds you well", "Per my
last email", "Dear Sir/Madam", or "Kind regards". Thank or acknowledge people
when appropriate. No emojis, filler, sycophancy, or effusive openers. Slack is
shorter than email. Stay precise on scientific content.

WHEN TO DRAFT
Only when a reply from the owner is genuinely needed - the message requires their
specific answer or input (policy set by the owner 2026-08-27): a direct question
addressed to them; a request for their action, decision, data, or approval;
meeting scheduling; anything with a deadline (grants, reviews, admin); PI or
core-facility correspondence. This bar applies to one-to-one Slack DMs too - a
DM is not drafted just because it is a DM. A self-forwarded email whose
original sender was recovered should be judged against these same criteria and
addressed to the original sender, never to the owner.

WHEN TO SKIP (no draft)
Casual conversation and small talk; acknowledgements ("thanks", "sounds good",
"got it"); FYI status updates that expect no answer; congratulations and
social messages; newsletters; mass CCs where they are not the direct recipient;
automated notifications; listserv traffic. When unsure whether their input is
required, skip - err toward drafting only for Dr. Ada Advisor or
deadline-bearing content.

RULES
- Never commit them to a date, number, or deliverable that is not already in the
  message. Use a clearly marked [placeholder] only when the reply cannot be
  useful without that missing fact. If no timing was requested, simply confirm
  the action and say they will follow up when it is complete.
- Never invent facts about their work or results.
- If the message asks for something you cannot verify, say so in the reply
  rather than guessing.
<!-- /shared:drafting -->

In chat, list skipped-yet-notable items as FYI in the report rather than
hiding them.

## 4. Match their voice

Search their past sent replies and mirror the tone you find:
```
python .claude/scripts/memory_search.py "<topic or sender>" --path-prefix Memory/drafts/sent
```
If there's no corpus yet, write from the rules above directly.

## 5. Write draft files

One file per message in `VAULT/Memory/drafts/active/`.

- **Dedup first:** if a draft with the same `source_id` already exists in
  `drafts/active/`, skip it - the Slack overlap window can re-surface a
  message you already drafted.
- **Filename:** `YYYY-MM-DD_<type>_<slug>.md` — `<type>` is `email` (Gmail),
  `outlook` (work), or `slack`; `<slug>` is a short kebab of sender/subject.
- **Frontmatter:**
  ```
  ---
  type: email | outlook | slack
  source_id: <message id, or channel_id:ts for Slack>
  thread_id: <gmail thread id, if Gmail>
  recipient: <who she'd reply to>
  subject: <subject, or "Slack DM" / "#<channel>">
  context: <one line: why this needs a reply>
  relationship_group: Mentor/PI | Mentee | Collaborator | Colleague
  relationship_rationale: <short evidence or provisional-default note>
  relationship_confidence: high | medium | low
  created: YYYY-MM-DD HH:MM
  status: active
  ---
  ```
- **Body:** `## Original Message` (quote what they're replying to) then
  `## Draft Reply` (the drafted response, ready to review).

Note on approval: `type: email` drafts can be pushed to Gmail Drafts from the
`/drafts` page. `outlook` and `slack` drafts are copy-paste (no auto-push -
there's no send path, by design). Say so in the summary.

## 6. Advance the Slack checkpoint, then report

After a complete Slack pass (no throttling warning), and only after drafting:
```
python .claude/scripts/query.py slack mark-scanned
```
No argument - it promotes the scan-start time `since` stashed.

Summarize: the window covered, how many messages scanned per source, drafts
written (filename + sender + one-line why), FYI items (sender, channel, gist;
flag Dr. Ada Advisor, deadlines, opportunities), and anything skipped as a
duplicate. Don't send anything - they review and sends from `/drafts` or the
platform themselves.
