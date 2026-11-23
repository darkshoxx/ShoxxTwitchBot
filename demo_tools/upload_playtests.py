#!/usr/bin/env python3
"""Upload cut playtest videos to YouTube.

Uploads every CSV row where Processed is True and Uploaded is not True, using the
file "<Game Name> - <Studio>.mp4" in the output folder configured in playtest_editor.py.
Uploaded is set to True right after YouTube has accepted the video.

If discord_scraper.py has collected data for a game (discord_data.json), the description gets the
Steam link, the dev's AI declaration and socials, and your feedback, and the video is uploaded as
public or unlisted depending on what the dev answered. Without data, the fields stay empty and
PRIVACY_STATUS is used.

Setup (once):
    pip install google-api-python-client google-auth-oauthlib python-dotenv
    Put the OAuth client ID and secret (type "Desktop app") in a .env file, see ENV_PATH below.

Usage:
    python upload_playtests.py --dry-run            # show titles/descriptions/thumbnails, upload nothing
    python upload_playtests.py --export-metadata    # write "<video>.txt" files for manual upload
    python upload_playtests.py --limit 1            # upload only one video (good first test)
    python upload_playtests.py                      # upload everything pending

IMPORTANT: until your Google Cloud project has passed YouTube's API audit, every video
uploaded through the API is locked to private and cannot be made public afterwards.

The YouTube API cannot set the specific "Game title" of a video. The script sets the
Gaming category and prints a checklist of Studio links at the end for that manual step.
"""

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import httplib2

from playtest_editor import (CSV_PATH, FFMPEG, OUT_DIR, is_true, load_csv,
                             output_filename, save_csv)
from playtest_paths import DATA_PATH, THUMBS_DIR, find_record

try:
    from dotenv import load_dotenv
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    GOOGLE_IMPORT_ERROR = None
except ImportError as e:
    GOOGLE_IMPORT_ERROR = e

# =========================================================================== #
# CUSTOMIZATION
# =========================================================================== #

# --- Authentication --------------------------------------------------------- #
SCRIPT_DIR = Path(__file__).resolve().parent
ENV_PATH = SCRIPT_DIR.parent / ".env"   # .env file containing the two variables below
CLIENT_ID_VAR = "GOOGLE_TOKEN"          # name of the variable holding the OAuth client ID
CLIENT_SECRET_VAR = "GOOGLE_SECRET"     # name of the variable holding the OAuth client secret
TOKEN_PATH = SCRIPT_DIR / "token.json"  # created on first login (contains a refresh token: keep it
                                        # private / out of git); delete it to log in again

# --- Video settings ----------------------------------------------------------- #
PRIVACY_STATUS = "private"       # used when there is no Discord data for the game
PRIVACY_PUBLIC = "public"        # the dev said Yes to a public video (or didn't say anything)
PRIVACY_NOT_PUBLIC = "unlisted"  # the dev said No: not searchable, but still shown in the playlist
# ("private" | "unlisted" | "public". While the Google project is unaudited, YouTube forces every API upload to private.)
CATEGORY_ID = "20"               # 20 = Gaming, 22 = People & Blogs, 24 = Entertainment, 27 = Education
DEFAULT_LANGUAGE = "en"          # language of title/description
DEFAULT_AUDIO_LANGUAGE = "en"    # spoken language
MADE_FOR_KIDS = False            # legally required declaration; True disables comments etc.
EMBEDDABLE = True
PUBLIC_STATS_VIEWABLE = True
LICENSE = "youtube"              # "youtube" | "creativeCommon"
NOTIFY_SUBSCRIBERS = False       # only relevant once a video is public

# --- Title / description / tags ------------------------------------------------ #
# Placeholders available in all templates:
#   {index}  the CSV "Index" column (1, 2, 3, ...): one number per playtest
#   {game}   Game Name from the CSV, unmodified (colons etc. kept)
#   {studio} Studio from the CSV
#   {date}   playtest date formatted with DATE_FORMAT
#   {raw_date} playtest date exactly as in the CSV (dd-mm-yy)
#   {video_index} VOD number (several playtests can share one VOD)
# From discord_scraper.py (empty if there is no data for the game):
#   {steam_url}  {ai_declaration}  {socials}  {feedback}
# Literal curly braces in a template must be doubled: {{ and }}.
# For anything fancier (conditions, per-game text), edit build_metadata() below.
DATE_FORMAT = "%d %B %Y"         # "05 September 2026"

TITLE_TEMPLATE = "{index} | {game} | Playtest | {studio}"   # YouTube limit: 100 characters

DESCRIPTION_TEMPLATE = """Playtest of "{game}" by {studio}, recorded live on {date}.

This is an unscripted first-impressions playtest of a game in development. Feedback was passed on to the developer.

Game: {game}
Steam: {steam_url}
Developer: {studio}

Dev's AI Declaration:
{ai_declaration}

Dev's socials:
{socials}

Feedback given:
{feedback}

Get Feedback:
Want feedback as well? Join the discord linked on my twitch page (not linking the discord here because bots...)
https://www.twitch.tv/darkshoxx
It's Free!
"""
# YouTube limits: 5000 bytes, and "<" / ">" are not allowed (they are removed).

TAG_TEMPLATES = ["{game}", "{studio}", "playtest", "gameplay", "indie game", "playtesting"]
# YouTube limit: about 500 characters of tags in total; extra tags are dropped.

# --- Thumbnails ------------------------------------------------------------------ #
# Order of preference:
#   1. A file in CUSTOM_THUMBNAILS_DIR named like the video, "<Game> - <Studio>.jpg" (what
#      make_thumbnails.py produces), or else named after the CSV Index, e.g. "1.jpg" for Index 1
#      (.jpg / .jpeg / .png). Set the directory to None to disable.
#   2. A frame grabbed from the video with ffmpeg (if FRAME_THUMBNAIL is True).
#   3. Nothing: YouTube picks one of its auto-generated frames.
# Custom thumbnails need a channel with phone verification, max 2 MB, 16:9 recommended (1280x720).
CUSTOM_THUMBNAILS_DIR = THUMBS_DIR     # see playtest_paths.py
FRAME_THUMBNAIL = True
FRAME_THUMBNAIL_AT_SECONDS = 60  # where in the video to grab the frame (falls back to 0s if too short)

# --- Optional: add every upload to a playlist ------------------------------------ #
# Needs a broader permission than plain uploading. If you set or change this after having
# logged in once, the script notices and asks you to log in again. None = disabled.
PLAYLIST_ID = "PLb3f9SzNBosg"               # e.g. "PLxxxxxxxxxxxxxxxx"


def build_metadata(row: dict, record: dict | None = None) -> dict:
    """Return {"title", "description", "tags"} for one CSV row (+ its Discord data, if any). Edit freely."""
    record = record or {}
    raw_date = row["Date"].strip()
    try:
        date = datetime.strptime(raw_date, "%d-%m-%y").strftime(DATE_FORMAT)
    except ValueError:
        date = raw_date

    fields = {
        "index": row["Index"].strip(),
        "game": row["Game Name"].strip(),
        "studio": row["Studio"].strip(),
        "date": date,
        "raw_date": raw_date,
        "video_index": row["Video Index"].strip(),
        "steam_url": record.get("steam_url") or "",
        "ai_declaration": record.get("ai_declaration") or "",
        "socials": record.get("socials") or "",
        "feedback": record.get("feedback") or "",
    }
    return {
        "title": TITLE_TEMPLATE.format(**fields),
        "description": DESCRIPTION_TEMPLATE.format(**fields),
        "tags": [t.format(**fields) for t in TAG_TEMPLATES],
    }


# =========================================================================== #
# End of customization
# =========================================================================== #

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
FULL_SCOPE = "https://www.googleapis.com/auth/youtube"
SCOPES = [UPLOAD_SCOPE]
if PLAYLIST_ID:
    SCOPES.append(FULL_SCOPE)

CHUNK_SIZE = 8 * 1024 * 1024  # must be a multiple of 256 KB
MAX_RETRIES = 6
RETRIABLE_STATUS = {500, 502, 503, 504}


class StopRun(Exception):
    """Raised for errors where continuing with further videos is pointless."""


def finalize_metadata(meta: dict) -> dict:
    """Apply YouTube's limits so the API doesn't reject the request."""
    title = meta["title"].replace("<", "").replace(">", "").strip()
    if len(title) > 100:
        print(f"      WARN title longer than 100 characters, truncated: {title}")
        title = title[:100].rstrip()

    description = meta["description"].replace("<", "").replace(">", "")
    while len(description.encode("utf-8")) > 5000:
        description = description[:-50]

    tags, total = [], 0
    for tag in meta["tags"]:
        tag = tag.replace("<", "").replace(">", "").replace(",", "").strip()
        cost = len(tag) + (2 if " " in tag else 0) + 1  # quotes around multi-word tags + separator
        if not tag or total + cost > 480:
            continue
        tags.append(tag)
        total += cost
    return {"title": title, "description": description, "tags": tags}


def find_custom_thumbnail(stem: str, index: str, saved_as: str | None = None) -> Path | None:
    """A file in CUSTOM_THUMBNAILS_DIR called '<video name>', '<Index>', '<Index>_<anything>' or the name the scraper
    recorded for it (.jpg / .jpeg / .png; case doesn't matter). If several exist, the most recently changed one wins."""
    if CUSTOM_THUMBNAILS_DIR is None or not CUSTOM_THUMBNAILS_DIR.is_dir():
        return None
    recorded = Path(saved_as).stem.lower() if saved_as else None
    found = []
    for f in CUSTOM_THUMBNAILS_DIR.iterdir():
        if not f.is_file() or f.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        name = f.stem.lower()
        if name == stem.lower() or name == index or name.startswith(f"{index}_") or name == recorded:
            found.append(f)
    return max(found, key=lambda f: f.stat().st_mtime) if found else None


def describe_thumbnail(stem: str, index: str, saved_as: str | None = None) -> str:
    custom = find_custom_thumbnail(stem, index, saved_as)
    if custom:
        return f"custom file {custom.name}"
    if FRAME_THUMBNAIL:
        return f"frame grab at {FRAME_THUMBNAIL_AT_SECONDS}s (no '{index}.jpg', '{index}_....jpg' or '{stem}.jpg' found)"
    return "none (YouTube will pick one)"


def grab_frame(video_path: Path, out_path: Path) -> bool:
    for seconds in (FRAME_THUMBNAIL_AT_SECONDS, 0):
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(seconds), "-i", str(video_path),
               "-frames:v", "1", "-vf", "scale=1280:720:force_original_aspect_ratio=decrease", "-q:v", "2",
               str(out_path)]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if out_path.exists() and out_path.stat().st_size > 0:
            return True
    return False


def choose_thumbnail(video_path: Path, index: str, tmp_dir: Path, saved_as: str | None = None) -> tuple[Path | None, str]:
    """Return (file, description) for the thumbnail to upload, or (None, reason)."""
    custom = find_custom_thumbnail(video_path.stem, index, saved_as)
    if custom:
        return custom, f"custom file {custom.name}"
    if FRAME_THUMBNAIL:
        frame = tmp_dir / "thumbnail.jpg"
        frame.unlink(missing_ok=True)
        if grab_frame(video_path, frame):
            return frame, "frame grab (no custom thumbnail found)"
    return None, "none"


def client_config(client_id: str, client_secret: str) -> dict:
    """The contents of a Desktop-app client_secret.json, built from the .env values."""
    return {"installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }}


def scopes_sufficient(granted) -> bool:
    """Does a saved token carry the permissions this configuration needs?"""
    if granted is None:  # unknown (old token file): assume yes, the API will say if not
        return True
    granted = set(granted)
    if PLAYLIST_ID:
        return FULL_SCOPE in granted
    return bool(granted & {UPLOAD_SCOPE, FULL_SCOPE})


def get_service():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))  # scopes as stored in the file
        if not scopes_sufficient(creds.scopes):
            print("      token.json has fewer permissions than needed now (playlist access). Logging in again...")
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            load_dotenv(ENV_PATH)
            client_id, client_secret = os.getenv(CLIENT_ID_VAR), os.getenv(CLIENT_SECRET_VAR)
            if not client_id or not client_secret:
                raise StopRun(f"{CLIENT_ID_VAR} / {CLIENT_SECRET_VAR} not found in {ENV_PATH} or the environment.")
            flow = InstalledAppFlow.from_client_config(client_config(client_id, client_secret), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def http_error_text(e: "HttpError") -> str:
    return e.content.decode("utf-8", errors="replace") if e.content else str(e)


def upload_video(youtube, path: Path, meta: dict, privacy: str) -> dict:
    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": CATEGORY_ID,
            "defaultLanguage": DEFAULT_LANGUAGE,
            "defaultAudioLanguage": DEFAULT_AUDIO_LANGUAGE,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": MADE_FOR_KIDS,
            "embeddable": EMBEDDABLE,
            "publicStatsViewable": PUBLIC_STATS_VIEWABLE,
            "license": LICENSE,
        },
    }
    media = MediaFileUpload(str(path), chunksize=CHUNK_SIZE, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media,
                                      notifySubscribers=NOTIFY_SUBSCRIBERS)

    response, retries, last_percent = None, 0, -1
    while response is None:
        try:
            status, response = request.next_chunk()
            retries = 0
            if status and int(status.progress() * 100) // 10 > last_percent // 10:
                last_percent = int(status.progress() * 100)
                print(f"      {last_percent}%")
        except HttpError as e:
            text = http_error_text(e)
            if "quotaExceeded" in text or "uploadLimitExceeded" in text:
                raise StopRun(f"YouTube refused further uploads (quota/upload limit): {text[:300]}")
            if e.resp.status not in RETRIABLE_STATUS or retries >= MAX_RETRIES:
                raise
            retries += 1
        except (ConnectionError, TimeoutError, httplib2.HttpLib2Error):
            if retries >= MAX_RETRIES:
                raise
            retries += 1
        if response is None and retries:
            delay = random.random() * 2 ** retries
            print(f"      transient error, retry {retries}/{MAX_RETRIES} in {delay:.1f}s")
            time.sleep(delay)
    return response


def set_thumbnail(youtube, video_id: str, thumb: Path) -> None:
    if thumb.stat().st_size > 2 * 1024 * 1024:
        print(f"      WARN thumbnail {thumb.name} is over 2 MB, YouTube will likely reject it")
    youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb))).execute()


def add_to_playlist(youtube, video_id: str) -> None:
    body = {"snippet": {"playlistId": PLAYLIST_ID, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
    youtube.playlistItems().insert(part="snippet", body=body).execute()


def load_discord_data() -> dict:
    """discord_data.json written by discord_scraper.py (empty if it doesn't exist)."""
    if not DATA_PATH.exists():
        return {}
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"WARN  could not read {DATA_PATH.name}: {e}")
        return {}


def privacy_for(record: dict | None) -> str:
    if not record:
        return PRIVACY_STATUS
    return PRIVACY_PUBLIC if record.get("public", True) else PRIVACY_NOT_PUBLIC


def print_checklist(uploaded: list[tuple[str, str, str]]) -> None:
    """The API can't set a video's game title, so list the Studio pages for the manual step."""
    if not uploaded:
        return
    print("\nStill to do by hand in Studio (Details -> Show more -> Category: Gaming -> Game title):")
    for index, game, video_id in uploaded:
        print(f"  [{index}] {game}\n        https://studio.youtube.com/video/{video_id}/edit")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="show what would be uploaded, upload nothing")
    parser.add_argument("--export-metadata", action="store_true",
                        help="write '<video>.txt' (title, description, tags) next to each pending video, upload nothing")
    parser.add_argument("--limit", type=int, default=None, help="upload at most N videos")
    args = parser.parse_args()
    offline = args.dry_run or args.export_metadata

    if not offline and GOOGLE_IMPORT_ERROR:
        print(f"Missing library ({GOOGLE_IMPORT_ERROR}). Run:\n"
              f"  pip install google-api-python-client google-auth-oauthlib python-dotenv")
        return 1

    fieldnames, rows = load_csv()
    if "Uploaded" not in fieldnames:
        print(f"No 'Uploaded' column in {CSV_PATH.name}.")
        return 1

    if CUSTOM_THUMBNAILS_DIR is not None and not CUSTOM_THUMBNAILS_DIR.is_dir():
        print(f"WARN  thumbnail folder not found: {CUSTOM_THUMBNAILS_DIR} (frame grabs will be used)")

    discord_data = load_discord_data()
    pending = [r for r in rows
               if is_true(r["Processed"]) and not is_true(r["Uploaded"]) and r["Index"].strip().isdigit()]
    print(f"{len(pending)} video(s) pending" + (f", uploading at most {args.limit}" if args.limit else "") + ".")

    youtube = None
    done = skipped = failed = 0
    uploaded: list[tuple[str, str, str]] = []  # (index, game, video id)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for pos, row in enumerate(pending, 1):
                if args.limit is not None and done >= args.limit:
                    break

                index = row["Index"].strip()
                label = f"({pos}/{len(pending)}) [{index}] {row['Game Name']}"
                try:
                    video_path = OUT_DIR / output_filename(row)
                    record, record_note = find_record(discord_data, index, video_path.stem)
                    privacy = privacy_for(record)
                    meta = finalize_metadata(build_metadata(row, record))
                except (ValueError, KeyError) as e:
                    print(f"SKIP  {label}: {e}")
                    skipped += 1
                    continue
                if not video_path.exists():
                    print(f"SKIP  {label}: {video_path.name} not found in {OUT_DIR}")
                    skipped += 1
                    continue

                if args.dry_run:
                    print(f"DRY   {label}: {video_path.name}\n      title: {meta['title']}\n"
                          f"      privacy: {privacy}   discord data: {('yes ' + record_note) if record else 'NO (' + record_note + ')'}\n"
                          f"      tags: {', '.join(meta['tags'])}\n"
                          f"      thumbnail: {describe_thumbnail(video_path.stem, index, (record or {}).get('thumbnail'))}\n"
                          f"      description:\n"
                          + "\n".join("        " + line for line in meta["description"].splitlines()))
                    done += 1
                    continue
                if args.export_metadata:
                    txt = video_path.with_suffix(".txt")
                    txt.write_text(f"{meta['title']}\n\n{meta['description']}\n\nTags: {', '.join(meta['tags'])}\n",
                                   encoding="utf-8")
                    print(f"EXPORT {label}: {txt.name}")
                    done += 1
                    continue

                if youtube is None:
                    youtube = get_service()

                print(f"UPLOAD {label}: {video_path.name} ({video_path.stat().st_size / 1e6:.0f} MB)")
                print(f"      title: {meta['title']}")
                print(f"      privacy: {privacy}")
                if record:
                    print("      discord data: found" + (f" ({record_note})" if record_note else ""))
                else:
                    print(f"      WARN no Discord data for '{video_path.stem}' ({record_note}). "
                          f"Run: python discord_scraper.py --csv")
                try:
                    response = upload_video(youtube, video_path, meta, privacy)
                except HttpError as e:
                    print(f"FAIL  {label}: {http_error_text(e)[:300]}")
                    failed += 1
                    continue
                except (ConnectionError, TimeoutError, httplib2.HttpLib2Error) as e:
                    print(f"FAIL  {label}: network error: {e}")
                    failed += 1
                    continue

                video_id = response["id"]
                print(f"      uploaded: https://youtu.be/{video_id} "
                      f"(privacy: {response.get('status', {}).get('privacyStatus', '?')})")
                uploaded.append((index, row["Game Name"].strip(), video_id))

                # Record the upload first, so a thumbnail/playlist problem never causes a re-upload.
                row["Uploaded"] = "True"
                try:
                    save_csv(fieldnames, rows)
                except PermissionError:
                    print(f"WARN  uploaded, but {CSV_PATH.name} is locked (open in Excel?). Set Uploaded=True for "
                          f"this row by hand, otherwise it will be uploaded again.")
                    print_checklist(uploaded)
                    return 1
                done += 1

                thumb, thumb_desc = choose_thumbnail(video_path, index, tmp_dir, (record or {}).get("thumbnail"))
                if thumb:
                    try:
                        set_thumbnail(youtube, video_id, thumb)
                        print(f"      thumbnail set ({thumb_desc})")
                    except HttpError as e:
                        print(f"      WARN thumbnail failed: {http_error_text(e)[:200]}")
                else:
                    print("      no thumbnail set")
                if PLAYLIST_ID:
                    try:
                        add_to_playlist(youtube, video_id)
                        print("      added to playlist")
                    except HttpError as e:
                        print(f"      WARN adding to playlist failed: {http_error_text(e)[:200]}")
    except StopRun as e:
        print(f"STOP  {e}")
        print_checklist(uploaded)
        return 1

    print(f"\nDone: {done} processed, {skipped} skipped, {failed} failed.")
    print_checklist(uploaded)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
