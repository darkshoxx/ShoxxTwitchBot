"""
Inspired by (and with permission from) the Online Ocarina Simulator by vaexenc
https://ocarina.toomuchofheaven.com/
https://github.com/vaexenc/ocarina
"""

import asyncio
import os
import random

import aiohttp
from dotenv import load_dotenv

HERE = os.path.abspath(os.path.dirname(__file__))
ENV = os.path.join(HERE, ".env")
load_dotenv(ENV)

scene_dict = {
    "loom": "7 1 6",
    "oot": "7 1 5",
    "shiv": "7 1 7",
    "myst": "7 1 8",
    "outtake": "7 1 9",
    "poke": "7 1 4",
    "where": "7 131",
    "what": "7 132",
    "welcome": "7 133",
}

OVERLAY_URL = "http://localhost:3000/event"


# ── Video folder roots (relative to the server's /assets/videos/) ────────────
# Index in each dict is the 1-based sorted position of the file in that folder.
# "0" means pick randomly.

oot_song_dict = {
    "<^><^>":    "OOT/ZelLul.mp4",
    ">v^>v^":    "OOT/SunSon.mp4",
    "vava>v>v":  "OOT/BolFir.mp4",
    "^<>^<>":    "OOT/EpoSon.mp4",
    "a^<><>":    "OOT/MinFor.mp4",
    "<>>a<>v":   "OOT/NocSha.mp4",
    "^>^><^":    "OOT/PreLig.mp4",
    "ava>va":    "OOT/ReqSpi.mp4",
    "v><v><":    "OOT/SarSon.mp4",
    "av>><":     "OOT/SerWat.mp4",
    "av^av^":    "OOT/SonSto.mp4",
    ">av>av":    "OOT/SonTin.mp4",
}

loom_song_dict = {
    "eced": "Loom/open.mp4",
    "cfgc": "Loom/transcend.mp4",
}

shiv_song_dict = {
    "ramtabobataramba": "Shivers/Drums.mp4",
}

myst_song_dict = {
    "c1c2d#2f1a#0": "Myst/Piano2.mp4",
}

poke_vid_dict = {
    "question": "Pokemon/question.mp4",
    "answer":   "Pokemon/answer.mp4",
}



# TomScott folders: value None means pick randomly from the folder.
# The server doesn't need to know the filenames — we resolve them here
# at import time so we can pick randomly without a server round-trip.



# Default sleep times (seconds) per category
_SLEEP = {
    "oot":     30,
    "loom":    30,
    "shiv":    30,
    "myst":    30,
    "poke":    30,
    "where":   30,
    "what":    30,
    "welcome": 30,
}


# ── Core helper ───────────────────────────────────────────────────────────────

async def _push(payload: dict):
    """Fire-and-forget POST to the overlay server."""
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                OVERLAY_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=2),
            )
    except Exception as exc:
        print(f"[overlay] push failed: {exc}")


async def play_video(src: str, duration: int = 30):
    """
    Tell the alerts overlay to play a video.
    src  — URL path served by the overlay server, e.g. '/assets/videos/OOT/BolFir.mp4'
    """
    await _push({"type": "video", "src": src, "duration": duration})


# ── Song / video play functions ───────────────────────────────────────────────

async def play_oot(sequence: str):
    path = oot_song_dict.get(sequence)
    if path:
        await play_video(f"/assets/videos/{path}", _SLEEP["oot"])


async def play_loom(sequence: str):
    path = loom_song_dict.get(sequence)
    if path:
        await play_video(f"/assets/videos/{path}", _SLEEP["loom"])


async def play_shiv(sequence: str):
    path = shiv_song_dict.get(sequence)
    if path:
        await play_video(f"/assets/videos/{path}", _SLEEP["shiv"])


async def play_myst(sequence: str):
    path = myst_song_dict.get(sequence)
    if path:
        await play_video(f"/assets/videos/{path}", _SLEEP["myst"])


async def play_pokemon(kind: str):
    """kind: 'question' or 'answer'"""
    path = poke_vid_dict.get(kind)
    if path:
        await play_video(f"/assets/videos/{path}", _SLEEP["poke"])


# async def play_tomscott(category: str):
#     """category: 'where' | 'what' | 'welcome'"""
#     pool = {"where": _where_files, "what": _what_files, "welcome": _welcome_files}.get(category, [])
#     if pool:
#         await play_video(random.choice(pool), _SLEEP[category])


# ── Webcam toggle (kept, still uses OBS websocket for the facecam source) ────
# If you want to remove the OBS dependency entirely, delete this.

async def toggle_webcam_active():
    from obswebsocket import obsws, requests as obs_requests
    OBS_PW = os.getenv("OBS_PW")
    ws = obsws("localhost", 4455, OBS_PW)
    ws.connect()
    await asyncio.sleep(10)
    ws.call(obs_requests.PressInputPropertiesButton(
        inputName="BGRemoved Facecam", propertyName="activate"
    ))
    await asyncio.sleep(1)
    ws.call(obs_requests.PressInputPropertiesButton(
        inputName="BGRemoved Facecam", propertyName="activate"
    ))
    ws.disconnect()


### legacy routing through video map, to be repalced

_ASSET_ROOT = os.path.join(HERE, "stream-overlay", "public", "assets", "videos")


def _list_folder(rel):
    folder = os.path.join(_ASSET_ROOT, rel)
    if not os.path.isdir(folder):
        return []
    return sorted(
        f"/assets/videos/{rel}/{f}"
        for f in os.listdir(folder)
        if f.lower().endswith(".mp4")
    )

# Indexed the same way as the old OBS scene item IDs:
# each dict maps the same integer key -> relative URL path under /assets/videos/
_video_map = {
    "7 1 5": {v: f"/assets/videos/{p}" for p, v in oot_song_dict.items()},
    "7 1 6": {v: f"/assets/videos/{p}" for p, v in loom_song_dict.items()},
    "7 1 7": {v: f"/assets/videos/{p}" for p, v in shiv_song_dict.items()},
    "7 1 8": {v: f"/assets/videos/{p}" for p, v in myst_song_dict.items()},
    "7 1 4": {v: f"/assets/videos/{p}" for p, v in poke_vid_dict.items()},
    "7 131": _list_folder("TomScott/Where"),
    "7 132": _list_folder("TomScott/What"),
    "7 133": _list_folder("TomScott/Welcome"),
    "7 1 9": _list_folder("Outtakes"),
}

async def play_me(index, scene_index: str, sleep_time=30):
    BASE = "/assets/videos/"
    ts_pools = {
        "7 131": _list_folder("TomScott/Where"),
        "7 132": _list_folder("TomScott/What"),
        "7 133": _list_folder("TomScott/Welcome"),
        "7 1 9": _list_folder("Outtakes"),
    }
    # print("+" + scene_index + "+")
    # ret = ts_pools[scene_index]
    # print(ret)
    if scene_index in ts_pools:
        pool = ts_pools[scene_index]
        src = random.choice(pool) if pool else None
    else:
        # index is already a relative path string e.g. "Loom/open.mp4"
        src = BASE + index if index else None
    if src:
        await _push({"type": "video", "src": src, "duration": sleep_time})

