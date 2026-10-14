"""
demo_queue.py
Manages the two-tier demo queue for darkshoxx stream.
Single source of truth for queue logic and execution.
"""
import asyncio
import datetime
import html
import json
import os
import re
import zoneinfo
from typing import Optional
import urllib.parse
import webbrowser

HERE        = os.path.abspath(os.path.dirname(__file__))
QUEUE_FILE  = os.path.join(HERE, "current_queue.json")
DONE_FILE   = os.path.join(HERE, "done.txt")
LABELS_FILE = os.path.join(HERE, "stream-overlay", "public", "assets", "files.txt")

BINGO_URL          = "https://bingobaker.com#6ab2b6440ba1d88d"
GAMES_AND_DEMOS_ID = "2634"
OWNER              = "darkshoxx"
REPLY_TIMEOUT      = 60
BRITISH_TZ         = zoneinfo.ZoneInfo("Europe/London")
SERVER             = "http://localhost:3000"

_queue: list         = []
_pending_reply: dict = {}
_pending_name: dict  = {}
_fuzzy_pending: Optional[dict] = None

# ── Persistence & Initialization ──────────────────────────────────────────────

def _save():
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(_queue, f, indent=2, ensure_ascii=False)

def _load_usual_labels() -> list[str]:
    if not os.path.exists(LABELS_FILE):
        return []
    with open(LABELS_FILE, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]

def _rebuild_usuals():
    subs = [e for e in _queue if e["type"] == "submission"]
    usuals = _load_usual_labels()
    _queue.clear()
    _queue.extend(subs)
    for label in usuals:
        _queue.append({"type": "usual", "game": label})
    _save()

def load_queue():
    global _queue
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, encoding="utf-8") as f:
            try:
                _queue = json.load(f)
            except Exception:
                _queue = []
    else:
        _queue = []
    _rebuild_usuals()

def _remove_usual_label(label: str):
    if not os.path.exists(LABELS_FILE):
        return
    with open(LABELS_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    new_lines = []
    removed = False
    for line in lines:
        if not removed and line.strip() == label:
            removed = True
        else:
            new_lines.append(line)
    with open(LABELS_FILE, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

# ── Queue Ordering ────────────────────────────────────────────────────────────

def _sort_queue():
    subs    = [e for e in _queue if e["type"] == "submission"]
    usuals  = [e for e in _queue if e["type"] == "usual"]

    weightless = [e for e in subs if not e["weight"]]
    weighted   = [e for e in subs if e["weight"]]

    seen_order = {}
    for i, e in enumerate(weightless):
        u = e["user"].lower()
        if u not in seen_order:
            seen_order[u] = i

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
    for e in _queue:
        if e["type"] == "submission" and e["user"].lower() == user_lower and e["weight"]:
            e["weight"] = False
            break
    _sort_queue()

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

# ── Public Accessors ──────────────────────────────────────────────────────────

async def queue_is_open() -> bool:
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{SERVER}/layout", timeout=aiohttp.ClientTimeout(total=1)) as r:
                data = await r.json()
                return data.get("queue_open", False)
    except Exception:
        return False

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
    return [e for e in _queue if e["type"] == "submission" and e["user"].lower() == user_lower]

# ── Commands Execution Logic ──────────────────────────────────────────────────

async def cmd_enter(msg, twitch=None) -> str:
    if not await queue_is_open():
        return "The queue is currently closed."

    user  = msg.user.name
    lower = user.lower()
    subs = user_submissions(lower)

    for s in subs:
        if s.get("game") is None:
            return f"@{user} Please name your current submission first (just reply to the bot's message)."

    has_weightless = any(not s["weight"] for s in subs)

    entry = {
        "type":         "submission",
        "user":         user,
        "game":         None,
        "weight":       has_weightless,
        "submitted_at": datetime.datetime.utcnow().isoformat(),
    }
    _queue.append(entry)
    _sort_queue()

    await msg.reply(f"@{user} You're in the queue! Please reply to this message with the name of your game.")

    event = asyncio.Event()
    _pending_reply[lower] = event
    _pending_name[lower]  = None

    try:
        await asyncio.wait_for(event.wait(), timeout=REPLY_TIMEOUT)
    except asyncio.TimeoutError:
        pass

    name = _pending_name.pop(lower, None)
    _pending_reply.pop(lower, None)

    if name:
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
        return f"@{user} No game name received — you're in the queue as '{user}'."

def handle_potential_reply(msg) -> bool:
    lower = msg.user.name.lower()
    if lower not in _pending_reply:
        return False
    text = msg.text.strip()
    if text.lower() == "!leave":
        _pending_name[lower] = None
        _pending_reply[lower].set()
        return False
    text = re.sub(r'^@\S+\s*', '', text).strip()
    _pending_name[lower] = text
    _pending_reply[lower].set()
    return True

def cmd_leave(msg) -> str:
    user  = msg.user.name
    lower = user.lower()

    if lower in _pending_reply:
        _pending_name[lower] = None
        _pending_reply[lower].set()

    subs = user_submissions(lower)
    if not subs:
        return f"@{user} You're not in the queue."

    _queue[:] = [e for e in _queue if not (e["type"] == "submission" and e["user"].lower() == lower)]
    _save()
    return f"@{user} Removed all your submissions from the queue."

def cmd_current() -> str:
    e = top_entry()
    return f"Current: {_format_entry(e)}" if e else "The queue is empty."

def cmd_peek() -> str:
    e = second_entry()
    return f"Next up: {_format_entry(e)}" if e else "Nothing next in the queue."

def get_top_game_name() -> Optional[str]:
    """Helper to extract the game name from the top queue entry regardless of type."""
    top = top_entry()
    if not top:
        return None
    if top["type"] == "usual":
        return top.get("game")
    elif top["type"] == "submission":
        return top.get("game")  # None if user hasn't named it yet
    return None

async def _get_category_viewers(twitch, game_id: str) -> int:
    total = 0
    pages = 0
    async for stream in twitch.get_streams(game_id=game_id):
        total += stream.viewer_count
        pages += 1
        if pages >= 500:
            break
    return total

async def _apply_category(twitch, broadcaster_id: str, cat) -> str:
    if twitch and broadcaster_id:
        await twitch.modify_channel_information(broadcaster_id=broadcaster_id, game_id=cat.id)
        viewer_count = await _get_category_viewers(twitch, cat.id)
        
        # Open the Twitch category page in the default browser
        slug = urllib.parse.quote(cat.name.lower().replace(" ", "-"), safe="")
        category_url = f"https://www.twitch.tv/directory/category/{slug}"
        webbrowser.open(category_url)

        return f"Category set to '{cat.name}'. Currently {viewer_count:,} viewers across all live streams."
    
    return f"Category set to '{cat.name}'."

async def _apply_category_by_id(twitch, broadcaster_id: str, game_id: str):
    if twitch and broadcaster_id:
        await twitch.modify_channel_information(broadcaster_id=broadcaster_id, game_id=game_id)

async def _set_twitch_category(twitch, broadcaster_id: str, game_name: str) -> str:
    global _fuzzy_pending
    if not twitch or not broadcaster_id:
        return f"Category target: '{game_name}'"

    clean_name = html.unescape(game_name)
    results = []
    async for cat in twitch.search_categories(query=clean_name):
        results.append(cat)
        if len(results) >= 10:
            break

    exact = next((c for c in results if c.name.lower() == clean_name.lower()), None)
    if exact:
        return await _apply_category(twitch, broadcaster_id, exact)

    if results and clean_name.lower() != "games + demos":
        _fuzzy_pending = {
            "candidates":     results,
            "game":           game_name,
            "twitch":         twitch,
            "broadcaster_id": broadcaster_id,
        }
        lines = [f"{i+1}. {c.name}" for i, c in enumerate(results)]
        return f"No exact match for '{clean_name}'. Candidates: " + " | ".join(lines) + " — reply with a number or 'no'."

    # Fallback: Perform a live search for "Games + Demos" category
    async for cat in twitch.search_categories(query="Games + Demos"):
        if cat.name.lower() == "games + demos":
            await twitch.modify_channel_information(broadcaster_id=broadcaster_id, game_id=cat.id)
            return f"No category found for '{clean_name}'. Category set to 'Games + Demos'."

    return f"Failed to set category for '{clean_name}'."


async def handle_fuzzy_reply(msg, twitch, broadcaster_id: str) -> Optional[str]:
    global _fuzzy_pending
    if _fuzzy_pending is None or msg.user.name.lower() != OWNER.lower():
        return None

    text = msg.text.strip().lower()

    if text == "no":
        _fuzzy_pending = None
        # Dynamic fallback search for Games + Demos
        async for cat in twitch.search_categories(query="Games + Demos"):
            if cat.name.lower() == "games + demos":
                await twitch.modify_channel_information(broadcaster_id=broadcaster_id, game_id=cat.id)
                return "Category set to Games + Demos."
        return "Category set fallback failed."

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
        return None

async def cmd_set(twitch, broadcaster_id: str, custom_game: Optional[str] = None) -> str:
    """
    Sets the Twitch category.
    - If custom_game is provided (e.g. !set blue prince), sets to 'blue prince'.
    - If custom_game is None, sets to the top entry of the queue.
    """
    if custom_game:
        target_game = custom_game
    else:
        target_game = get_top_game_name()
        if not target_game:
            return "Cannot set category: Top of queue has no game name associated."

    return await _set_twitch_category(twitch, broadcaster_id, target_game)

async def cmd_next(twitch, broadcaster_id: str) -> str:
    global _fuzzy_pending
    if not _queue:
        return "The queue is empty."

    entry = _queue.pop(0)
    _log_done(entry)

    if entry["type"] == "usual":
        _remove_usual_label(entry["game"])
        _save()
    else:
        user_lower = entry["user"].lower()
        if not entry["weight"]:
            _promote_if_needed(user_lower)
        else:
            _sort_queue()

    _save()
    done_label = _format_entry(entry)

    new_top = _queue[0] if _queue else None
    if new_top is None:
        return f"Done: {done_label}. Queue is now empty."

    next_label = _format_entry(new_top)

    # Automatically set category whenever top updates
    cat_result = await cmd_set(twitch, broadcaster_id)
    return f"Done: {done_label}. {cat_result}"


async def cmd_open() -> str:
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(f"{SERVER}/queue/open", timeout=aiohttp.ClientTimeout(total=1))
    except Exception:
        pass
    return "Queue is now open! Use !enter to join."

async def cmd_close() -> str:
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(f"{SERVER}/queue/close", timeout=aiohttp.ClientTimeout(total=1))
    except Exception:
        pass
    return "Queue is now closed."

def cmd_bingo() -> str:
    return f"Generate your bingo card here: {BINGO_URL}"

def cmd_reload_labels() -> str:
    _rebuild_usuals()  # This reconstructs usuals and calls _save() internally
    usual_count = sum(1 for e in _queue if e["type"] == "usual")
    total_count = len(_queue)
    return f"Reloaded labels from files.txt. ({usual_count} usual demos, {total_count} total in queue)."

# Auto-initialize state when module loading finishes
load_queue()