"""Slack integration: read messages, detect items needing the owner's reply.

Advisor mode: READ-ONLY in this module. Drafted replies are written to the
vault (Phase 6); the only Slack posting anywhere in the system is the Phase 7
chat bot replying to the owner in their own DM - and that lives elsewhere.

Tokens (in .claude/data/secrets/slack.env):
- SLACK_USER_TOKEN (xoxp-): used HERE for reading. A bot token can only see
  channels the bot was invited to and its own DMs; the user token sees what
  the owner sees - their DMs, private channels, mentions.
- SLACK_BOT_TOKEN (xoxb-) and SLACK_APP_TOKEN (xapp-): reserved for the
  Phase 7 Socket Mode chat bot; not used in this module.

Keep the Slack app single-workspace and NEVER "distribute" it - internal apps
keep Tier 3 read limits (~50 req/min); distributed non-Marketplace apps were
cut to 1 req/min in May 2025.
"""

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import DATA, STATE_DIR, atomic_write_json, read_json, with_retry  # noqa: E402

SECRETS_FILE = DATA / "secrets" / "slack.env"
SCAN_STATE = STATE_DIR / "slack-scan-state.json"
# Always inspect explicitly important collaborators (an advisor, a manager)
# before spending the limited conversations.history budget. Slack user IDs are
# supplied as a comma-separated list in SLACK_PRIORITY_USER_IDS, so no code
# change is needed to add one.
PRIORITY_USER_IDS = {
    uid.strip() for uid in
    os.environ.get("SLACK_PRIORITY_USER_IDS", "").split(",")
    if uid.strip()
}
PRIORITY_CHANNEL_IDS = {
    channel.strip() for channel in
    os.environ.get("SLACK_PRIORITY_CHANNEL_IDS", "").split(",")
    if channel.strip()
}
PERMANENT_CONVERSATION_ERRORS = {
    "channel_not_found",
    "not_in_channel",
    "is_archived",
}


@dataclass
class SlackMessage:
    channel_id: str
    channel_name: str
    user_id: str
    user_name: str
    text: str
    ts: str
    is_dm: bool
    mentions_me: bool
    thread_ts: str | None = None
    is_from_me: bool = False


class IncompleteSlackScan(RuntimeError):
    """Raised when a completeness-sensitive DM scan was rate-limited."""


def _slack_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    try:
        return str(response.get("error", "")) if response is not None else ""
    except Exception:
        return ""


def _load_token(var: str = "SLACK_USER_TOKEN") -> str:
    for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{var}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise KeyError(f"{var} not found in {SECRETS_FILE}")


def _client():
    from slack_sdk import WebClient
    from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler
    client = WebClient(token=_load_token())
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
    return client


def whoami(client=None) -> tuple[str, str]:
    """(user_id, user_name) for the token owner."""
    client = client or _client()
    resp = with_retry(lambda: client.auth_test())
    return resp["user_id"], resp.get("user", "")


def _user_names(client, user_ids: set[str]) -> dict[str, str]:
    names = {}
    for uid in user_ids:
        try:
            info = with_retry(lambda uid=uid: client.users_info(user=uid))
            profile = info["user"]
            names[uid] = profile.get("real_name") or profile.get("name", uid)
        except Exception:
            names[uid] = uid
    return names


def recent_messages(hours_back: float = 8.0, max_conversations: int = 40
                   ) -> list[SlackMessage]:
    """Messages from the last N hours across DMs and member channels."""
    client = _client()
    my_id, _ = whoami(client)
    oldest = str(time.time() - hours_back * 3600)

    convs, cursor = [], None
    # Enumerate the whole lightweight conversation directory before choosing
    # which histories to fetch. Stopping after the first page made the later
    # priority sort ineffective: important older DMs may not be on page one.
    while True:
        resp = with_retry(lambda c=cursor: client.conversations_list(
            types="public_channel,private_channel,mpim,im",
            exclude_archived=True, limit=100, cursor=c))
        convs.extend(resp.get("channels", []))
        cursor = resp.get("response_metadata", {}).get("next_cursor") or None
        if not cursor:
            break
    convs = [c for c in convs if c.get("is_im") or c.get("is_member")]
    # Slack does not return conversations in recency or importance order. The
    # old arbitrary first-40 slice silently excluded long-lived, important DMs
    # (an advisor's DM was observed at position 98 of 104). Slack supplies a per-user
    # `priority` score for IMs; sort by it before applying the API-call cap so
    # frequently important people remain in the reply-critical scan. Keep
    # channels after DMs because a direct DM is more likely to need a reply
    # than ambient channel traffic.
    convs.sort(
        key=lambda c: (
            1 if c.get("user") in PRIORITY_USER_IDS else 0,
            1 if c.get("is_im") else 0,
            float(c.get("priority") or 0),
        ),
        reverse=True,
    )
    convs = convs[:max_conversations]

    messages, user_ids = [], set()
    for conv in convs:
        try:
            hist = with_retry(lambda c=conv: client.conversations_history(
                channel=c["id"], oldest=oldest, limit=50))
        except Exception:
            continue
        for m in hist.get("messages", []):
            if m.get("type") != "message" or m.get("subtype"):
                continue
            uid = m.get("user", "")
            user_ids.add(uid)
            messages.append(SlackMessage(
                channel_id=conv["id"],
                channel_name=conv.get("name") or "(dm)",
                user_id=uid, user_name=uid,
                text=m.get("text", ""), ts=m.get("ts", ""),
                is_dm=bool(conv.get("is_im")),
                mentions_me=f"<@{my_id}>" in m.get("text", ""),
                thread_ts=m.get("thread_ts")))

    names = _user_names(client, user_ids - {""})
    for m in messages:
        m.user_name = names.get(m.user_id, m.user_id)
    messages.sort(key=lambda m: m.ts, reverse=True)
    return messages


def needs_response(hours_back: float = 24.0,
                   max_conversations: int = 40) -> list[SlackMessage]:
    """Heuristic: DMs where the last message isn't from the owner, plus mentions
    they haven't replied after."""
    client = _client()
    my_id, _ = whoami(client)
    msgs = recent_messages(
        hours_back=hours_back, max_conversations=max_conversations)

    latest_by_channel: dict[str, SlackMessage] = {}
    my_latest_ts: dict[str, str] = {}
    for m in msgs:  # msgs sorted newest-first
        if m.channel_id not in latest_by_channel:
            latest_by_channel[m.channel_id] = m
        if m.user_id == my_id and m.channel_id not in my_latest_ts:
            my_latest_ts[m.channel_id] = m.ts

    out = []
    for m in msgs:
        if m.user_id == my_id:
            continue
        answered = my_latest_ts.get(m.channel_id, "0") > m.ts
        if m.is_dm and latest_by_channel[m.channel_id].user_id != my_id \
                and m.ts == latest_by_channel[m.channel_id].ts:
            out.append(m)
        elif m.mentions_me and not answered:
            out.append(m)
    return out


def priority_needs_response(hours_back: float = 72.0) -> list[SlackMessage]:
    """Fast, reliable response check for explicitly critical DM channels.

    A workspace-wide DM sweep needs one conversations.history call per
    conversation and this workspace's token is rate-limited heavily. Critical
    contacts therefore get a direct one-call check first. This does not mark
    anything read or mutate Slack.
    """
    if not PRIORITY_CHANNEL_IDS:
        return []
    client = _client()
    my_id, _ = whoami(client)
    cutoff = time.time() - hours_back * 3600
    out, user_ids = [], set()

    for channel_id in PRIORITY_CHANNEL_IDS:
        try:
            hist = with_retry(lambda cid=channel_id: client.conversations_history(
                channel=cid, limit=20))
        except Exception:
            continue
        messages = [
            m for m in hist.get("messages", [])
            if m.get("type") == "message" and not m.get("subtype")
            and float(m.get("ts", 0)) >= cutoff
        ]
        if not messages or messages[0].get("user") == my_id:
            continue
        message = messages[0]
        uid = message.get("user", "")
        user_ids.add(uid)
        out.append(SlackMessage(
            channel_id=channel_id,
            channel_name="(dm)",
            user_id=uid,
            user_name=uid,
            text=message.get("text", ""),
            ts=message.get("ts", ""),
            is_dm=True,
            mentions_me=f"<@{my_id}>" in message.get("text", ""),
            thread_ts=message.get("thread_ts"),
        ))

    names = _user_names(client, user_ids - {""})
    for message in out:
        message.user_name = names.get(message.user_id, message.user_id)
    out.sort(key=lambda message: message.ts, reverse=True)
    return out


def unread_messages(max_age_days: float = 45.0, per_conv_limit: int = 20
                   ) -> list[SlackMessage]:
    """All genuinely-unread incoming messages (newer than the owner's last-read
    marker) across DMs AND channels they're in - not just DMs/mentions. This is
    the "scan everything incoming" view; the caller triages importance.

    Uses conversations.info last_read per conversation (a broadcast in a busy
    channel won't surface once they're caught up)."""
    client = _client()
    my_id, _ = whoami(client)
    cutoff = time.time() - max_age_days * 86400

    convs, cursor = [], None
    while True:
        resp = with_retry(lambda c=cursor: client.conversations_list(
            types="public_channel,private_channel,mpim,im",
            exclude_archived=True, limit=100, cursor=c))
        convs.extend(resp.get("channels", []))
        cursor = resp.get("response_metadata", {}).get("next_cursor") or None
        if not cursor:
            break
    convs = [c for c in convs if c.get("is_im") or c.get("is_member")]

    out, user_ids = [], set()
    for conv in convs:
        try:
            info = with_retry(lambda c=conv: client.conversations_info(channel=c["id"]))
            last_read = float(info["channel"].get("last_read", 0) or 0)
            hist = with_retry(lambda c=conv: client.conversations_history(
                channel=c["id"], limit=per_conv_limit))
        except Exception:
            continue
        for m in hist.get("messages", []):
            if m.get("type") != "message" or m.get("subtype"):
                continue
            ts = float(m.get("ts", 0))
            if ts <= last_read or ts < cutoff or m.get("user") == my_id:
                continue
            uid = m.get("user", "")
            user_ids.add(uid)
            out.append(SlackMessage(
                channel_id=conv["id"],
                channel_name=conv.get("name") or "(dm)",
                user_id=uid, user_name=uid,
                text=m.get("text", ""), ts=m.get("ts", ""),
                is_dm=bool(conv.get("is_im")),
                mentions_me=f"<@{my_id}>" in m.get("text", ""),
                thread_ts=m.get("thread_ts")))

    names = _user_names(client, user_ids - {""})
    for m in out:
        m.user_name = names.get(m.user_id, m.user_id)
    out.sort(key=lambda m: m.ts, reverse=True)
    return out


def messages_since(oldest_ts: float, include_channels: bool = False,
                   include_group_dms: bool = True,
                   per_conv_limit: int = 100,
                   require_complete: bool = False,
                   include_own: bool = False) -> list[SlackMessage]:
    """Messages newer than `oldest_ts` (Slack epoch seconds).

    the owner's own messages are excluded by default. Response-aware callers may
    opt in with ``include_own=True`` and use ``SlackMessage.is_from_me`` to
    distinguish replies from incoming work. Pair this incremental primitive
    with get_checkpoint()/set_checkpoint().

    Scope, and why it matters for speed:
    - Default (include_channels=False): DMs + group DMs only. This is the
      reply-critical set and there are ~100 of them, so the scan stays quick.
    - include_channels=True: also every public/private channel they're a member of
      (hundreds). Complete, but Slack heavily rate-limits conversations.history
      (see the 2025 tier note at the top of this module), so a full sweep can
      take minutes. Use it for an occasional catch-up on channel broadcasts, not
      the routine scan.

    Implementation is ONE conversations.history call per conversation with the
    server-side `oldest` filter (no conversations.info call, unlike
    unread_messages) - quiet conversations return an empty page. It runs SERIAL
    on purpose: threading bursts straight into Slack's per-method rate limit and
    the 429 backoffs make the whole scan slower, not faster.

    Note: without the `search:read` scope there is no cheaper signal - Slack has
    no bulk "everything unread" endpoint for user tokens, so channel coverage is
    inherently one-call-per-channel. Granting search:read would let a caller use
    search.messages (`after:<date>`) for a fast, complete single-query scan.
    """
    client = _client()
    my_id, _ = whoami(client)
    oldest = f"{oldest_ts:.6f}"
    types = "im"
    if include_group_dms:
        types += ",mpim"
    if include_channels:
        types += ",public_channel,private_channel"

    convs, cursor = [], None
    while True:
        resp = with_retry(lambda c=cursor: client.conversations_list(
            types=types, exclude_archived=True, limit=100, cursor=c))
        convs.extend(resp.get("channels", []))
        cursor = resp.get("response_metadata", {}).get("next_cursor") or None
        if not cursor:
            break
    convs = [c for c in convs if c.get("is_im") or c.get("is_mpim")
             or c.get("is_member")]

    out, user_ids, failure_details = [], set(), []
    for conv in convs:
        try:
            pages, history_cursor = [], None
            while True:
                hist = with_retry(
                    lambda c=conv, cursor=history_cursor:
                    client.conversations_history(
                        channel=c["id"],
                        oldest=oldest,
                        limit=per_conv_limit,
                        cursor=cursor,
                    )
                )
                pages.extend(hist.get("messages", []))
                history_cursor = (
                    hist.get("response_metadata", {}).get("next_cursor") or None
                )
                if not history_cursor:
                    break
        except Exception as exc:
            # conversations.list can retain stale IM handles that history no
            # longer resolves. They can never yield a message, so skipping
            # them is complete; transient/rate-limit failures still fail closed.
            if _slack_error_code(exc) in PERMANENT_CONVERSATION_ERRORS:
                continue
            failure_details.append((conv.get("id", ""), repr(exc)))
            continue
        for m in pages:
            if m.get("type") != "message" or m.get("subtype"):
                continue
            if float(m.get("ts", 0)) <= oldest_ts:
                continue
            uid = m.get("user", "")
            is_from_me = uid == my_id
            if is_from_me and not include_own:
                continue
            user_ids.add(uid)
            out.append(SlackMessage(
                channel_id=conv["id"],
                channel_name=conv.get("name") or "(dm)",
                user_id=uid, user_name=uid,
                text=m.get("text", ""), ts=m.get("ts", ""),
                is_dm=bool(conv.get("is_im")),
                mentions_me=f"<@{my_id}>" in m.get("text", ""),
                thread_ts=m.get("thread_ts"),
                is_from_me=is_from_me))

    names = _user_names(client, user_ids - {""})
    for m in out:
        m.user_name = names.get(m.user_id, m.user_id)
    out.sort(key=lambda m: m.ts, reverse=True)
    if failure_details:
        # Never let a throttled scan look complete. stderr keeps stdout JSON clean.
        failed = len(failure_details)
        first_channel, first_error = failure_details[0]
        warning = (
            f"{failed}/{len(convs)} conversations could not be fetched "
            "(transient or rate-limited); rerun to catch them - the checkpoint has "
            f"NOT advanced yet. First failure: {first_channel}: "
            f"{first_error[:240]}"
        )
        print(f"WARNING: {warning}", file=sys.stderr)
        if require_complete:
            raise IncompleteSlackScan(warning)
    return out


def get_checkpoint(fallback_days: float = 2.0) -> float:
    """Slack epoch-seconds of the last committed scan; `fallback_days` ago if
    never scanned."""
    state = read_json(SCAN_STATE, default={}) or {}
    ts = state.get("last_scan_ts")
    if ts is None:
        return time.time() - fallback_days * 86400
    return float(ts)


def stash_scan_start(ts: float) -> None:
    """Record when the current scan began WITHOUT advancing the committed
    checkpoint. set_checkpoint(None) promotes this, so the scan+draft window is
    re-scanned next run (deduped by existing drafts) rather than skipped."""
    state = read_json(SCAN_STATE, default={}) or {}
    state["pending_scan_ts"] = f"{ts:.6f}"
    atomic_write_json(SCAN_STATE, state)


def set_checkpoint(ts: float | None = None) -> float:
    """Commit the scan high-water mark. ts=None promotes the stashed
    pending_scan_ts (falling back to now). Returns the committed ts."""
    from datetime import datetime, timezone
    if ts is None:
        state = read_json(SCAN_STATE, default={}) or {}
        pending = state.get("pending_scan_ts")
        ts = float(pending) if pending is not None else time.time()
    atomic_write_json(SCAN_STATE, {
        "last_scan_ts": f"{ts:.6f}",
        "last_scan_iso": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
    })
    return ts


def format_context(messages: list[SlackMessage]) -> str:
    if not messages:
        return "No Slack messages."
    lines = [f"{len(messages)} Slack message(s):"]
    for m in messages:
        where = "DM" if m.is_dm else f"#{m.channel_name}"
        flag = " [mentions you]" if m.mentions_me else ""
        lines.append(f"- [{where}] {m.user_name}{flag}: {m.text[:200]}")
    return "\n".join(lines)


def is_configured() -> bool:
    return SECRETS_FILE.exists()
