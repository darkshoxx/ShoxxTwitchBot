"""
demo_queue.py
Manages the two-tier demo queue for darkshoxx stream.

Queue structure (always maintained in this order):
    1. Weightless submissions  — user's first (or only) submission, unlabelled or labelled
    2. Weighted submissions    — user's 2nd+ submissions, sorted by their position
                                 in the weightless tier
    3. Usual demos             — from files.txt, played in order

Persistence: current_queue.json (rewritten on every mutation)
Done log:    done.txt (append-only)
Label file:  files.txt (usual demos, read + mutated by !next)
"""

import asyncio
import datetime
import html
import json
import os
import re
import zoneinfo
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
HERE         = os.path.abspath(os.path.dirname(__file__))
STREAM_OVERLAY = os.path.join(HERE, "stream-overlay")
PUBLIC = os.path.join(STREAM_OVERLAY, "public")
ASSETS = os.path.join(PUBLIC, "assets")
QUEUE_FILE   = os.path.join(ASSETS, "current_queue.json")
DONE_FILE    = os.path.join(ASSETS, "done.txt")
LABELS_FILE  = os.path.join(ASSETS, "files.txt")


# ── Constants ─────────────────────────────────────────────────────────────────
BINGO_URL          = "https://bingobaker.com#6ab2b6440ba1d88d"
GAMES_AND_DEMOS_ID = "509658"   # Twitch category ID for "Games + Demos"
OWNER              = "darkshoxx"
REPLY_TIMEOUT      = 60         # seconds to wait for game name reply
BRITISH_TZ         = zoneinfo.ZoneInfo("Europe/London")

# ── Entry schema ──────────────────────────────────────────────────────────────
#
# Submission entry:
#   { "type": "submission", "user": str, "game": str|None,
#     "weight": bool, "submitted_at": iso_str }
#
# Usual entry:
#   { "type": "usual", "game": str }

# ── In-memory state ───────────────────────────────────────────────────────────
_queue: list         = []
_queue_open: bool    = False
_pending_reply: dict = {}   # user_lower -> asyncio.Event (waiting for game name reply)
_pending_name: dict  = {}   # user_lower -> str|None (filled when reply arrives)

# Fuzzy match state (one pending at a time)
_fuzzy_pending: Optional[dict] = None
# { "candidates": [...], "game": str (usual label), "twitch_obj": Twitch }


# ── Persistence ───────────────────────────────────────────────────────────────

def _save():
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(_queue, f, indent=2, ensure_ascii=False)

def load_queue():
    global _queue
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, encoding="utf-8") as f:
            _queue = json.load(f)
    else:
        _queue = []
    _rebuild_usuals()

def _rebuild_usuals():
    """Sync usual entries from files.txt into the tail of the queue."""
    # Keep all submission entries as-is
    subs = [e for e in _queue if e["type"] == "submission"]
    usuals = _load_usual_labels()
    _queue.clear()
    _queue.extend(subs)
    for label in usuals:
        _queue.append({"type": "usual", "game": label})
    _save()


# ── Label file helpers ────────────────────────────────────────────────────────

def _load_usual_labels() -> list[str]:
    if not os.path.exists(LABELS_FILE):
        return []
    with open(LABELS_FILE, encoding="utf-8") as f:
        return [l.strip() for l in f
                if l.strip()]

def _remove_usual_label(label: str):
    """Remove the first matching line from files.txt (exact, full line)."""
    if not os.path.exists(LABELS_FILE):
        return
    with open(LABELS_FILE, encoding="utf-8") as f:
        lines = f.readlines()
    # Match the raw line (stripped) against label
    new_lines = []
    removed = False
    for line in lines:
        if not removed and line.rstrip("\n") == label:
            removed = True   # skip this line
        else:
            new_lines.append(line)
    with open(LABELS_FILE, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


# ── Queue ordering ────────────────────────────────────────────────────────────

def _sort_queue():
    """
    Re-sort the in-memory queue:
      1. Weightless submissions (weight=False) — in insertion order
      2. Weighted submissions (weight=True) — sorted by submitter's
         position in the weightless tier, then by their own insertion order
      3. Usual entries — in files.txt order
    """
    subs    = [e for e in _queue if e["type"] == "submission"]
    usuals  = [e for e in _queue if e["type"] == "usual"]

    weightless = [e for e in subs if not e["weight"]]
    weighted   = [e for e in subs if e["weight"]]

    # Build submitter order from weightless tier
    seen_order = {}
    for i, e in enumerate(weightless):
        u = e["user"].lower()
        if u not in seen_order:
            seen_order[u] = i

    # Sort weighted by (submitter's weightless position, submission time)
    weighted.sort(key=lambda e: (
        seen_order.get(e["user"].lower(), 999999),
        e["submitted_at"]
    ))

    _queue.clear()
    _queue.extend(weightless)
    _queue.extend(weighted)
    _queue.extend(usuals)
    _save()


def _promote_if_needed(user_lower: str):
    """
    After removing a user's first (weightless) entry, check if their
    next submission should become weightless.
    Called after any pop/leave that removes a weightless entry.
    """
    # Find the earliest weighted entry for this user
    for e in _queue:
        if e["type"] == "submission" and e["user"].lower() == user_lower and e["weight"]:
            e["weight"] = False
            break
    _sort_queue()


# ── Done log ──────────────────────────────────────────────────────────────────

def _log_done(entry: dict):
    now = datetime.datetime.now(tz=BRITISH_TZ)
    dt  = now.strftime("%Y-%m-%d %H:%M")
    if entry["type"] == "usual":
        label  = entry["game"]
        prefix = "U"
    else:
        game   = entry.get("game")
        label  = f"{entry['user']} - {game}" if game else entry["user"]
        prefix = "S"
    line = f"{prefix} {dt} {label}\n"
    with open(DONE_FILE, "a", encoding="utf-8") as f:
        f.write(line)


# ── Public accessors ──────────────────────────────────────────────────────────

def queue_is_open() -> bool:
    return _queue_open

def open_queue():
    global _queue_open
    _queue_open = True

def close_queue():
    global _queue_open
    _queue_open = False

def top_entry() -> Optional[dict]:
    return _queue[0] if _queue else None

def second_entry() -> Optional[dict]:
    return _queue[1] if len(_queue) > 1 else None

def _format_entry(e: dict) -> str:
    if e["type"] == "usual":
        return f"[Usual] {e['game']}"
    game = e.get("game")
    label = f"{e['user']} - {game}" if game else e["user"]
    tag = "[Weighted]" if e["weight"] else "[Submission]"
    return f"{tag} {label}"

def user_submissions(user_lower: str) -> list[dict]:
    return [e for e in _queue
            if e["type"] == "submission" and e["user"].lower() == user_lower]


# ── !enter ────────────────────────────────────────────────────────────────────

async def cmd_enter(msg, twitch=None) -> str:
    """Handle !enter. Returns the reply string."""
    if not _queue_open:
        return "The queue is currently closed."

    user  = msg.user.name
    lower = user.lower()

    subs = user_submissions(lower)

    # If they have an unlabelled submission, block second entry
    for s in subs:
        if s.get("game") is None:
            return f"@{user} Please name your current submission first (just reply to the bot's message)."

    # Determine weight: True if they already have a weightless submission
    has_weightless = any(not s["weight"] for s in subs)

    import datetime as _dt
    entry = {
        "type":         "submission",
        "user":         user,
        "game":         None,
        "weight":       has_weightless,
        "submitted_at": _dt.datetime.utcnow().isoformat(),
    }
    _queue.append(entry)
    _sort_queue()

    # Ask for game name
    await msg.reply(f"@{user} You're in the queue! Please reply to this message with the name of your game.")

    # Wait for reply
    event       = asyncio.Event()
    _pending_reply[lower] = event
    _pending_name[lower]  = None

    try:
        await asyncio.wait_for(event.wait(), timeout=REPLY_TIMEOUT)
    except asyncio.TimeoutError:
        pass

    name = _pending_name.pop(lower, None)
    _pending_reply.pop(lower, None)

    if name:
        # Find the entry we just added and update it
        for e in _queue:
            if (e["type"] == "submission" and
                    e["user"].lower() == lower and
                    e.get("game") is None and
                    e["submitted_at"] == entry["submitted_at"]):
                e["game"] = name
                break
        _save()
        return f"@{user} Submission recorded: {name}"
    else:
        return f"@{user} No game name received — you're in the queue as '{user}'. You can still name it later."


def handle_potential_reply(msg) -> bool:
    """
    Called on every message. If this user is in a pending reply window,
    consume the message as their game name (unless it's !leave).
    Returns True if the message was consumed as a reply.
    """
    lower = msg.user.name.lower()
    if lower not in _pending_reply:
        return False
    text = msg.text.strip()
    if text.lower() == "!leave":
        # Cancel the window; !leave will be handled normally
        _pending_name[lower] = None
        _pending_reply[lower].set()
        return False   # let !leave proceed
    # Any other message is their game name
    text = re.sub(r'^@\S+\s*', '', text).strip()
    _pending_name[lower] = text
    _pending_reply[lower].set()
    return True


# ── !leave ────────────────────────────────────────────────────────────────────

def cmd_leave(msg) -> str:
    user  = msg.user.name
    lower = user.lower()

    # Cancel pending reply window if active
    if lower in _pending_reply:
        _pending_name[lower] = None
        _pending_reply[lower].set()

    subs = user_submissions(lower)
    if not subs:
        return f"@{user} You're not in the queue."

    had_weightless = any(not s["weight"] for s in subs)

    # Remove all their entries
    _queue[:] = [e for e in _queue
                 if not (e["type"] == "submission" and e["user"].lower() == lower)]
    _save()

    # No promotion needed since all entries removed
    return f"@{user} Removed all your submissions from the queue."


# ── !current / !peek ──────────────────────────────────────────────────────────

def cmd_current() -> str:
    e = top_entry()
    if not e:
        return "The queue is empty."
    return f"Current: {_format_entry(e)}"

def cmd_peek() -> str:
    e = second_entry()
    if not e:
        return "Nothing next in the queue."
    return f"Next up: {_format_entry(e)}"


# ── !next ─────────────────────────────────────────────────────────────────────

async def cmd_next(twitch, broadcaster_id: str) -> str:
    """
    Pops the top entry, logs it, removes from files.txt if usual,
    sets Twitch category if usual, promotes weighted subs if needed.
    Returns reply string.
    """
    global _fuzzy_pending

    if not _queue:
        return "The queue is empty."

    entry = _queue.pop(0)
    _log_done(entry)

    if entry["type"] == "usual":
        _remove_usual_label(entry["game"])
        # Set Twitch category
        cat_result = await _set_twitch_category(twitch, broadcaster_id, entry["game"])
        _save()
        return cat_result
    else:
        # Was this user's only/first weightless entry?
        user_lower = entry["user"].lower()
        if not entry["weight"]:
            _promote_if_needed(user_lower)
        else:
            _sort_queue()
        label = _format_entry(entry)
        return f"Done: {label}. Next: {_format_entry(_queue[0]) if _queue else 'nothing'}."


async def _set_twitch_category(twitch, broadcaster_id: str, game_name: str) -> str:
    """
    Try exact match, then fuzzy. Returns a chat-ready string.
    Stores fuzzy state in _fuzzy_pending for !yes/<index>/!no handling.
    """
    global _fuzzy_pending
    # Unescape HTML entities from the label file
    clean_name = html.unescape(game_name)

    # Exact search
    results = []
    async for cat in twitch.search_categories(query=clean_name):
        results.append(cat)
        if len(results) >= 10:
            break

    exact = next((c for c in results if c.name.lower() == clean_name.lower()), None)

    if exact:
        info = await _apply_category(twitch, broadcaster_id, exact)
        return info

    # Fuzzy: present candidates
    if results:
        _fuzzy_pending = {
            "candidates":     results,
            "game":           game_name,
            "twitch":         twitch,
            "broadcaster_id": broadcaster_id,
        }
        lines = [f"{i+1}. {c.name}" for i, c in enumerate(results)]
        return (
            f"No exact match for '{clean_name}'. Candidates: "
            + " | ".join(lines)
            + " — reply with a number to pick, or 'no' to skip."
        )

    # Nothing found
    await _apply_category_by_id(twitch, broadcaster_id, GAMES_AND_DEMOS_ID)
    return f"No category found for '{clean_name}'. Set to Games + Demos."


async def _apply_category(twitch, broadcaster_id: str, cat) -> str:
    await twitch.modify_channel_information(
        broadcaster_id=broadcaster_id,
        game_id=cat.id,
    )
    # Get viewer count via stream aggregation
    viewer_count = await _get_category_viewers(twitch, cat.id)
    return (
        f"Category set to '{cat.name}'. "
        f"Currently {viewer_count:,} viewers across all live streams."
    )


async def _apply_category_by_id(twitch, broadcaster_id: str, game_id: str):
    await twitch.modify_channel_information(
        broadcaster_id=broadcaster_id,
        game_id=game_id,
    )


async def _get_category_viewers(twitch, game_id: str) -> int:
    """Sum viewer counts across live streams in this category (up to 10 pages)."""
    total = 0
    pages = 0
    async for stream in twitch.get_streams(game_id=game_id):
        total += stream.viewer_count
        pages += 1
        if pages >= 500:   # 500 results cap; fine for indie games
            break
    return total


async def handle_fuzzy_reply(msg, twitch, broadcaster_id: str) -> Optional[str]:
    """
    If a fuzzy match is pending and darkshoxx replies with a number or 'no',
    handle it. Returns a reply string if consumed, else None.
    """
    global _fuzzy_pending
    if _fuzzy_pending is None:
        return None
    if msg.user.name.lower() != OWNER.lower():
        return None

    text = msg.text.strip().lower()

    if text == "no":
        _fuzzy_pending = None
        await _apply_category_by_id(twitch, broadcaster_id, GAMES_AND_DEMOS_ID)
        return "Category set to Games + Demos."

    try:
        idx = int(text) - 1
        candidates = _fuzzy_pending["candidates"]
        if 0 <= idx < len(candidates):
            cat = candidates[idx]
            _fuzzy_pending = None
            return await _apply_category(twitch, broadcaster_id, cat)
        else:
            return f"Pick a number between 1 and {len(candidates)}, or 'no'."
    except ValueError:
        return None   # not a number or 'no', ignore


# ── !open / !close ────────────────────────────────────────────────────────────

def cmd_open() -> str:
    open_queue()
    return "Queue is now open! Use !enter to join."

def cmd_close() -> str:
    close_queue()
    return "Queue is now closed."


# ── !bingo ────────────────────────────────────────────────────────────────────

def cmd_bingo() -> str:
    return f"Generate your bingo card here: {BINGO_URL}"
