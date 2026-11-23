#!/usr/bin/env python3
"""Collect a game's submission data from the Discord forum and from Steam.

For each game it finds the forum post ("GAME TITLE - DEV NAME", fuzzy matched), then stores:
  - the Steam store link (a demo link is resolved to the full game via the Steam API)
  - the Steam header image (saved to RAW_THUMBS_DIR, to be turned into a thumbnail by make_thumbnails.py)
  - the AI declaration, the dev's socials, your feedback, and whether the video may be public
    (taken from the thread messages YOU marked with the reactions configured below)
Everything goes into discord_data.json (see playtest_paths.py), keyed like the video file name
("<Game> - <Studio>"). upload_playtests.py reads it.

    python discord_scraper.py "Shroud of Gloom" "Some Studio"     one game
    python discord_scraper.py --csv                                every CSV row that has no data yet
    python discord_scraper.py --csv --all                          ... and refresh the ones that have
    python discord_scraper.py --list                               list the forum posts the bot can see

Setup: pip install discord.py aiohttp python-dotenv     (bot token in .env as DISCORD_TOKEN)
The bot needs: View Channel + Read Message History on the forum, and the "Message Content Intent"
switched on in the Discord developer portal. It never posts anything.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import traceback
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import aiohttp
import discord
from dotenv import load_dotenv

from playtest_editor import clean_name, load_csv, output_filename
from playtest_paths import DATA_PATH, RAW_THUMBS_DIR, THUMBS_DIR, find_record, norm_key

# =========================================================================== #
# CONFIGURATION
# =========================================================================== #
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
TOKEN_VAR = "DISCORD_TOKEN"
load_dotenv(ENV_PATH)
GUILD_ID = int(os.getenv("GUILD_ID"))                # right-click the server icon -> Copy Server ID (needs Developer Mode)
FORUM_CHANNEL_NAME = "first-submissions"   # matched case-insensitively, as part of the channel name
MY_USER_ID = int(os.getenv("USER_ID"))                # your own user ID: only YOUR reactions mark messages
REQUIRED_ROLE = "Submitted - Feedback Received"   # the author should have this role (only a warning if not)

# Reactions by YOU that mark messages inside a post.
# A standard emoji: put the character itself. A custom server emoji: put its name (without colons).
EMOJI_FEEDBACK = "📓"         # :notebook:  your feedback (several messages are joined in order)
EMOJI_AI = "🤖"               # :robot:     the AI declaration
EMOJI_SOCIALS = "🇸🇲"         # :flag_sm:   the socials to share (the San Marino flag)
EMOJI_VISIBILITY = "👁"       # :eye:       a message saying Yes/No (public or unlisted); no eye = Yes

STEAM_API = "https://store.steampowered.com/api/appdetails"
CDN_HEADER = "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"

AUTO_ACCEPT_SCORE = 0.90      # a match at least this good, and clearly better than the runner-up, needs no confirmation
MIN_CANDIDATE_SCORE = 0.45    # below this a post isn't even offered as a candidate
# =========================================================================== #

STEAM_RE = re.compile(r"store\.steampowered\.com/app/(\d+)", re.I)
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")


# --------------------------------------------------------------------------- #
# matching forum posts to games
# --------------------------------------------------------------------------- #
def norm(text: str) -> str:
    """Lowercase, no accents, letters and digits only."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def coverage(needle: str, haystack: str) -> float:
    """1.0 if `needle` appears in `haystack`, otherwise how closely its best-matching stretch resembles it."""
    if not needle:
        return 0.0
    if needle in haystack:
        return 1.0
    n = len(needle)
    if len(haystack) <= n:
        return SequenceMatcher(None, needle, haystack).ratio()
    return max(SequenceMatcher(None, needle, haystack[i:i + n]).ratio() for i in range(len(haystack) - n + 1))


def score_title(title: str, game: str, studio: str) -> float:
    t = norm(title)
    game_score = coverage(norm(game), t)
    studio_score = coverage(norm(studio), t) if norm(studio) else 0.5
    return 0.75 * game_score + 0.25 * studio_score


def rank_threads(threads, game: str, studio: str):
    ranked = sorted(((score_title(t.name, game, studio), t) for t in threads), key=lambda x: -x[0])
    return [(s, t) for s, t in ranked if s >= MIN_CANDIDATE_SCORE]


async def choose_thread(ranked, game: str, studio: str):
    """Best match if it is clear-cut, otherwise let the user pick from the top candidates."""
    if not ranked:
        return None
    best = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    unique_full_match = best[0] >= 0.999 and runner_up < 0.999          # game and studio both appear in exactly one title
    clear_winner = best[0] >= AUTO_ACCEPT_SCORE and best[0] - runner_up >= 0.10
    if unique_full_match or clear_winner:
        return best[1]
    print(f"      not sure which post is '{game}' / '{studio}':")
    for i, (score, thread) in enumerate(ranked[:5], 1):
        print(f"        {i}) {thread.name}   (match {score:.0%})")
    try:
        answer = await asyncio.get_running_loop().run_in_executor(None, input, "      pick a number (Enter = skip): ")
    except EOFError:                                     # no keyboard attached
        answer = ""
    if answer.strip().isdigit() and 1 <= int(answer) <= min(5, len(ranked)):
        return ranked[int(answer) - 1][1]
    return None


# --------------------------------------------------------------------------- #
# reading a post
# --------------------------------------------------------------------------- #
def emoji_key(emoji) -> str:
    """Comparable key: custom emoji -> lowercase name, unicode emoji -> the character without variation selector."""
    if getattr(emoji, "id", None):
        return (emoji.name or "").lower()
    return str(emoji).replace("\ufe0f", "")


def _config_key(value: str) -> str:
    return value.replace("\ufe0f", "").strip(":").lower() if value.isascii() else value.replace("\ufe0f", "")


TAG_BY_EMOJI = {
    _config_key(EMOJI_FEEDBACK): "feedback",
    _config_key(EMOJI_AI): "ai",
    _config_key(EMOJI_SOCIALS): "socials",
    _config_key(EMOJI_VISIBILITY): "visibility",
}


async def reacted_by(reaction, user_id: int) -> bool:
    async for user in reaction.users():
        if user.id == user_id:
            return True
    return False


def plain(text: str) -> str:
    """Discord markdown -> plain text suitable for a YouTube description."""
    text = CUSTOM_EMOJI_RE.sub("", text or "")
    text = re.sub(r"<(https?://[^>\s]+)>", r"\1", text)          # <url> -> url
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)       # **bold**
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.S)           # __underline__
    text = re.sub(r"(?m)^[ \t]*[*-][ \t]+", "• ", text)            # bullets
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Label a message may start with ("Socials: https://..."), removed from the stored text.
LABELS = {
    "feedback": ("feedback",),
    "ai": ("ai declaration", "ai use", "ai"),
    "socials": ("social media", "socials", "social", "links"),
    "visibility": ("visibility",),
}
NO_WORDS = {"no", "nope", "nah", "not", "later", "unlisted", "private", "false"}   # "Not Yet" counts as No


def strip_label(text: str, labels) -> str:
    """Remove a leading 'Label:' (colon required, so 'AI-generated art' is left alone)."""
    pattern = r"^\s*(?:" + "|".join(re.escape(l) for l in sorted(labels, key=len, reverse=True)) + r")\s*[:：]\s*"
    return re.sub(pattern, "", text or "", count=1, flags=re.I).strip()


def parse_public(text: str) -> bool:
    """'No' / 'Not yet' / 'Unlisted' -> False; anything else (including 'Yes') -> True."""
    words = re.sub(r"[^a-z]+", " ", strip_label(text, LABELS["visibility"]).lower()).split()
    return not (words and words[0] in NO_WORDS)


def find_app_ids(messages, owner_id) -> list[int]:
    """Steam app IDs linked in the post, the author's messages first."""
    ids: list[int] = []
    for m in sorted(messages, key=lambda m: m.author.id != owner_id):
        texts = [m.content or ""]
        for e in m.embeds:
            texts += [x for x in (e.url, e.title, e.description) if x]
        for text in texts:
            for found in STEAM_RE.findall(text):
                if int(found) not in ids:
                    ids.append(int(found))
    return ids


# --------------------------------------------------------------------------- #
# Steam
# --------------------------------------------------------------------------- #
class Steam:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def details(self, appid: int):
        """The 'data' object of the store API for one app, or None."""
        try:
            async with self.session.get(STEAM_API, params={"appids": appid, "l": "english"},
                                        timeout=aiohttp.ClientTimeout(total=20)) as r:
                payload = await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return None
        entry = (payload or {}).get(str(appid)) or {}
        return entry.get("data") if entry.get("success") else None

    async def fetch(self, url: str):
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                return await r.read() if r.status == 200 else None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None


async def resolve_game(steam, linked_id: int) -> dict:
    """The linked app, or the full game if the link was a demo. -> {appid, name, header, note}"""
    details = await steam.details(linked_id)
    note = ""
    appid = linked_id
    if details and details.get("type") == "demo" and (details.get("fullgame") or {}).get("appid"):
        root = int(details["fullgame"]["appid"])
        root_details = await steam.details(root)
        if root_details:
            note = f"link was a demo ({linked_id}), using the full game ({root})"
            appid, details = root, root_details
        else:
            note = f"link was a demo ({linked_id}); its full game ({root}) isn't available via the API, keeping the demo"
    header = (details or {}).get("header_image") or CDN_HEADER.format(appid=appid)
    return {"appid": appid, "name": (details or {}).get("name"), "header": header.split("?")[0], "note": note,
            "api_ok": details is not None}


def image_extension(data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def find_row(game: str, studio: str):
    """The CSV row of this game (case/punctuation-insensitive), or None. Falls back to the game name alone
    if exactly one row has it."""
    try:
        _, rows = load_csv()
    except OSError:
        return None
    rows = [r for r in rows if r["Index"].strip().isdigit()]
    both = [r for r in rows if norm_key(r["Game Name"]) == norm_key(game) and norm_key(r["Studio"]) == norm_key(studio)]
    if both:
        return both[0]
    game_only = [r for r in rows if norm_key(r["Game Name"]) == norm_key(game)]
    return game_only[0] if len(game_only) == 1 else None


def pick_thumbnail_stem(index, game: str, key: str, previous) -> str:
    """'<Index>' normally; '<Index>_<Game>' if '<Index>.*' is already there; the video name if the Index is unknown."""
    if not index:
        return key
    if previous and (RAW_THUMBS_DIR / previous).exists():       # our own earlier download: replace it
        return Path(previous).stem
    taken = any(RAW_THUMBS_DIR.glob(f"{index}.*")) or any(THUMBS_DIR.glob(f"{index}.*"))
    return f"{index}_{clean_name(game)}" if taken else str(index)


async def download_header(steam, url: str, stem: str):
    data = await steam.fetch(url)
    if not data:
        return None
    RAW_THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    for old in RAW_THUMBS_DIR.glob(f"{stem}.*"):          # a different extension from an earlier run
        old.unlink()
    path = RAW_THUMBS_DIR / f"{stem}{image_extension(data)}"
    path.write_bytes(data)
    return path.name


# --------------------------------------------------------------------------- #
# one post -> one record
# --------------------------------------------------------------------------- #
async def author_role_status(guild, owner_id):
    """True/False whether the post's author has REQUIRED_ROLE, None if unknown."""
    if not owner_id:
        return None
    try:
        member = guild.get_member(owner_id) or await guild.fetch_member(owner_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None
    return any(r.name == REQUIRED_ROLE for r in member.roles)


async def gather_thread(thread, guild, steam, game: str, studio: str, key: str, my_id: int = None,
                        index=None, previous_thumbnail=None) -> dict:
    my_id = my_id or MY_USER_ID
    messages = [m async for m in thread.history(limit=None, oldest_first=True)]

    tagged = {"feedback": [], "ai": [], "socials": [], "visibility": []}
    for m in messages:
        for reaction in m.reactions:
            tag = TAG_BY_EMOJI.get(emoji_key(reaction.emoji))
            if tag and await reacted_by(reaction, my_id):
                tagged[tag].append(m)

    def text_of(tag):
        """The tagged messages in order, labels removed, identical repeats dropped."""
        parts, seen = [], set()
        for m in tagged[tag]:
            text = strip_label(plain(m.clean_content), LABELS[tag])
            fingerprint = " ".join(text.lower().split())
            if text and fingerprint not in seen:
                seen.add(fingerprint)
                parts.append(text)
        return "\n\n".join(parts)

    visibility_text = plain(tagged["visibility"][-1].clean_content) if tagged["visibility"] else ""
    ids = find_app_ids(messages, getattr(thread, "owner_id", None))

    steam_info, thumbnail = None, None
    if ids:
        steam_info = await resolve_game(steam, ids[0])
        thumbnail = await download_header(steam, steam_info["header"],
                                          pick_thumbnail_stem(index, game, key, previous_thumbnail))

    return {
        "game": game, "studio": studio, "index": index,
        "thread_title": thread.name, "thread_url": getattr(thread, "jump_url", None),
        "steam_url": f"https://store.steampowered.com/app/{steam_info['appid']}/" if steam_info else "",
        "steam_appid": steam_info["appid"] if steam_info else None,
        "steam_name": steam_info["name"] if steam_info else None,
        "linked_appids": ids,
        "ai_declaration": text_of("ai"),
        "socials": text_of("socials"),
        "feedback": text_of("feedback"),
        "public": parse_public(visibility_text) if tagged["visibility"] else True,
        "visibility_answer": strip_label(visibility_text, LABELS["visibility"]),
        "author_has_role": await author_role_status(guild, getattr(thread, "owner_id", None)),
        "thumbnail": thumbnail,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "_notes": [steam_info["note"]] if steam_info and steam_info["note"] else [],
        "_counts": {k: len(v) for k, v in tagged.items()},
    }


def describe(record: dict) -> list[str]:
    """Human-readable result lines, including everything that looks like it is missing."""
    c = record["_counts"]
    lines = []
    lines.append(f"      post: {record['thread_title']}")
    lines += [f"      note: {n}" for n in record["_notes"]]
    lines.append(f"      steam: {record['steam_url'] or 'NO STEAM LINK FOUND'}"
                 + (f"  ({record['steam_name']})" if record["steam_name"] else ""))
    lines.append(f"      thumbnail: {record['thumbnail'] or 'none downloaded'}")
    lines.append(f"      feedback: {c['feedback']} message(s)   ai declaration: {c['ai']}   socials: {c['socials']}"
                 f"   visibility: {'public' if record['public'] else 'UNLISTED'}"
                 + (f" (answer: '{record['visibility_answer']}')" if c["visibility"] else " (no eye reaction, default)"))
    for tag, label, emoji in (("feedback", "feedback", EMOJI_FEEDBACK), ("ai", "AI declaration", EMOJI_AI),
                              ("socials", "socials", EMOJI_SOCIALS)):
        if not c[tag]:
            lines.append(f"      WARN no message of yours marked {emoji} ({label})")
    if record["author_has_role"] is False:
        lines.append(f"      WARN the author doesn't have the '{REQUIRED_ROLE}' role")
    return lines


# --------------------------------------------------------------------------- #
# data file
# --------------------------------------------------------------------------- #
def load_data() -> dict:
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return {}


def save_data(data: dict) -> None:
    tmp = DATA_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, DATA_PATH)


def key_for(game: str, studio: str) -> str:
    """Same name as the video file, without extension: '<Game> - <Studio>'."""
    return Path(output_filename({"Game Name": game, "Studio": studio})).stem


# --------------------------------------------------------------------------- #
# the bot
# --------------------------------------------------------------------------- #
async def load_threads(guild, forum):
    found = {t.id: t for t in await guild.active_threads() if t.parent_id == forum.id}
    async for t in forum.archived_threads(limit=None):
        found.setdefault(t.id, t)
    return list(found.values())


class Scraper(discord.Client):
    def __init__(self, jobs, args):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.jobs, self.args = jobs, args
        self.exit_code, self._started = 0, False

    async def on_ready(self):
        if self._started:
            return
        self._started = True
        try:
            await self.work()
        except Exception:
            traceback.print_exc()
            self.exit_code = 1
        finally:
            await self.close()

    async def wait_for_guild(self):
        """The server cache can fill a moment after on_ready, so look for a few seconds."""
        for _ in range(10):
            guild = self.get_guild(GUILD_ID)
            if guild is not None:
                return guild
            await asyncio.sleep(0.5)
        return None

    def explain_missing_guild(self):
        print(f"No server with ID {GUILD_ID} is visible to this bot.")
        print(f"Logged in as: {self.user} (bot ID {getattr(self.user, 'id', '?')})")
        if self.guilds:
            print("The servers this bot IS in:")
            for g in self.guilds:
                print(f"  {g.name}   ID {g.id}")
            print("-> Use the ID of your server from this list as GUILD_ID.")
        else:
            print("This bot is not in ANY server. Either the invite wasn't completed, or the token in your .env belongs "
                  "to a different application than the one you invited.")
            print("-> In the developer portal, the Application ID on 'General Information' must equal the bot ID above.")

    async def work(self):
        guild = await self.wait_for_guild()
        if guild is None:
            self.explain_missing_guild()
            self.exit_code = 1
            return
        forum = discord.utils.find(
            lambda c: isinstance(c, discord.ForumChannel) and FORUM_CHANNEL_NAME.lower() in c.name.lower(), guild.channels)
        if forum is None:
            print(f"No forum channel containing '{FORUM_CHANNEL_NAME}' visible to the bot.")
            self.exit_code = 1
            return

        print(f"Connected to '{guild.name}'. Loading posts from #{forum.name} (archived ones can take a moment)...")
        threads = await load_threads(guild, forum)
        print(f"{len(threads)} post(s) in #{forum.name}.")
        if self.args.list:
            for t in sorted(threads, key=lambda t: t.name.lower()):
                print(f"  {t.name}")
            return

        data = load_data()
        async with aiohttp.ClientSession(headers={"User-Agent": "playtest-scraper"}) as session:
            steam = Steam(session)
            for n, (game, studio) in enumerate(self.jobs, 1):
                label = f"({n}/{len(self.jobs)}) {game} - {studio}"
                # The data is stored under the CSV's own spelling, which is what upload_playtests.py looks up.
                row = find_row(game, studio)
                if row:
                    game, studio, index = row["Game Name"].strip(), row["Studio"].strip(), row["Index"].strip()
                else:
                    index = None
                try:
                    key = key_for(game, studio)
                except ValueError as e:
                    print(f"SKIP  {label}: {e}")
                    continue
                print(f"FETCH {label}" + (f"   (CSV Index {index})" if row else ""))
                if not row:
                    print(f"      WARN '{game}' / '{studio}' is not in the CSV (check spelling): saved by name, no Index yet. "
                          f"Run again after fixing it, or use --csv.")
                thread = await choose_thread(rank_threads(threads, game, studio), game, studio)
                if thread is None:
                    print("      SKIP no matching post found")
                    self.exit_code = 1
                    continue
                earlier, _ = find_record(data, index, key)
                record = await gather_thread(thread, guild, steam, game, studio, key, index=index,
                                             previous_thumbnail=(earlier or {}).get("thumbnail"))
                for old_key in [k for k in data if k != key and norm_key(k) == norm_key(key)]:
                    del data[old_key]                    # same game saved earlier under a different spelling
                data[key] = record
                save_data(data)
                print("\n".join(describe(record)))
        print(f"\nData file: {DATA_PATH}")


def build_jobs(args) -> list[tuple[str, str]]:
    if args.csv:
        _, rows = load_csv()
        data = load_data()
        jobs = []
        for row in rows:
            if not row["Index"].strip().isdigit():
                continue
            game, studio = row["Game Name"].strip(), row["Studio"].strip()
            try:
                if args.all or key_for(game, studio) not in data:
                    jobs.append((game, studio))
            except ValueError:
                continue
        return jobs
    return [(args.game, args.studio)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("game", nargs="?", help="game name")
    parser.add_argument("studio", nargs="?", help="studio / developer name")
    parser.add_argument("--csv", action="store_true", help="fetch every CSV row that has no data yet")
    parser.add_argument("--all", action="store_true", help="with --csv: also refresh rows that already have data")
    parser.add_argument("--list", action="store_true", help="just list the forum posts the bot can see")
    args = parser.parse_args()
    for field in ("game", "studio"):                     # forgive: game="..." studio="..."
        value = getattr(args, field)
        if value and value.lower().startswith(field + "="):
            setattr(args, field, value[len(field) + 1:].strip())
    if not (args.csv or args.list or (args.game and args.studio)):
        parser.error('give a game and a studio, or --csv, or --list')

    load_dotenv(ENV_PATH)
    token = os.getenv(TOKEN_VAR)
    if not token:
        print(f"{TOKEN_VAR} not found in {ENV_PATH} or the environment.")
        return 1
    if not (isinstance(GUILD_ID, int) and isinstance(MY_USER_ID, int)):
        print("GUILD_ID and MY_USER_ID must be plain numbers without quotes, e.g. GUILD_ID = 123456789012345678")
        return 1
    if not GUILD_ID or not MY_USER_ID:
        print("Fill in GUILD_ID and MY_USER_ID at the top of this file (right-click -> Copy ID, Developer Mode on).")
        return 1

    jobs = build_jobs(args)
    if args.csv and not jobs and not args.list:
        print("Nothing to do: every CSV row already has data (use --all to refresh).")
        return 0

    print("Connecting to Discord...")
    client = Scraper(jobs, args)
    client.run(token, log_handler=None)
    return client.exit_code


if __name__ == "__main__":
    sys.exit(main())
