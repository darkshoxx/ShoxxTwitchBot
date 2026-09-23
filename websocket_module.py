import asyncio
import os
import random
import aiohttp
from dotenv import load_dotenv
from pokemon import generate_question_video, generate_answer_video

HERE = os.path.abspath(os.path.dirname(__file__))
ENV = os.path.join(HERE, ".env")
load_dotenv(ENV)

OVERLAY_URL = "http://localhost:3000/event"

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

_SLEEP = {
    "oot":     10,
    "loom":    10,
    "shiv":    10,
    "myst":    10,
    "poke":    30,
    "where":   10,
    "what":    10,
    "welcome": 10,
}

_video_queue: asyncio.Queue = None
_consumer_task: asyncio.Task = None
_session: aiohttp.ClientSession = None
_main_loop: asyncio.AbstractEventLoop = None

async def _get_session() -> aiohttp.ClientSession:
    """Returns an aiohttp session bound to the active running loop."""
    global _session
    current_loop = asyncio.get_running_loop()
    if _session is None or _session.closed or getattr(_session, '_loop', None) is not current_loop:
        _session = aiohttp.ClientSession()
    return _session

async def push_overlay_event(payload: dict):
    """POST to overlay server with stream draining to flush TCP buffers immediately."""
    print(f"[WS LOG] Pushing overlay event payload to {OVERLAY_URL}: {payload}")
    try:
        session = await _get_session()
        async with session.post(
            OVERLAY_URL,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=2),
        ) as resp:
            print(f"[WS LOG] POST response status code: {resp.status}")
            await resp.read()
    except Exception as exc:
        print(f"[WS ERROR LOG] push_overlay_event failed: {exc}")

def _enqueue_payload(payload: dict):
    """Safely adds a payload to the video queue across thread boundaries."""
    if _video_queue is not None and _main_loop is not None:
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is _main_loop:
            print(f"[WS LOG] Direct put to queue on main loop: {payload}")
            _video_queue.put_nowait(payload)
        else:
            print(f"[WS LOG] Threadsafe scheduling put to queue from secondary thread: {payload}")
            _main_loop.call_soon_threadsafe(_video_queue.put_nowait, payload)
    else:
        print("[WS WARNING LOG] _video_queue or _main_loop is None! Cannot enqueue item.")

async def queue_pokemon(dex: int):
    """Enqueues a Pokémon event payload for sequential processing."""
    print(f"[WS LOG] Enqueuing pokemon event for dex #{dex}")
    _enqueue_payload({"type": "pokemon", "dex": dex})

async def _video_consumer():
    """Single consumer — handles sequential playback and on-demand video generation."""
    print("[WS LOG] _video_consumer task loop started.")
    while True:
        try:
            print("[WS LOG] Worker waiting on _video_queue.get()...")
            payload = await _video_queue.get()
            print(f"[WS LOG] Worker retrieved item from queue: {payload}")
            
            event_type = payload.get("type", "video")
            
            if event_type == "pokemon":
                dex = payload["dex"]
                
                # 1. Generate Question Video on demand
                print(f"[WS LOG] Consumer generating question video for dex #{dex}")
                await asyncio.to_thread(generate_question_video, dex)
                await asyncio.sleep(0.5)
                
                # Push Question Video
                q_src = f"/assets/videos/{poke_vid_dict['question']}"
                print(f"[WS LOG] Pushing question video alert: {q_src}")
                await push_overlay_event({"type": "video", "src": q_src, "duration": 10})
                
                # 2. Wait display delay before generating answer
                print("[WS LOG] Sleeping 12 seconds for chat guessing window...")
                await asyncio.sleep(12)
                
                # 3. Generate Answer Video on demand
                print(f"[WS LOG] Consumer generating answer video for dex #{dex}")
                await asyncio.to_thread(generate_answer_video, dex)
                await asyncio.sleep(0.5)
                
                # Push Answer Video
                a_src = f"/assets/videos/{poke_vid_dict['answer']}"
                print(f"[WS LOG] Pushing answer video alert: {a_src}")
                await push_overlay_event({"type": "video", "src": a_src, "duration": 10})
                await asyncio.sleep(10)
                
            else:
                await push_overlay_event(payload)
                duration = payload.get("duration", 30)
                print(f"[WS LOG] Sleeping for duration of video: {duration}s")
                await asyncio.sleep(duration)
                
            _video_queue.task_done()
            print("[WS LOG] Video task completed. Task_done called.")
        except Exception as exc:
            print(f"[WS ERROR LOG] Exception inside _video_consumer loop: {exc}")

async def start_video_queue():
    """Call once inside the running event loop to initialize queue and consumer."""
    global _video_queue, _consumer_task, _main_loop
    _main_loop = asyncio.get_running_loop()
    print(f"[WS LOG] start_video_queue called inside loop ID: {id(_main_loop)}")
    _video_queue = asyncio.Queue()
    _consumer_task = asyncio.create_task(_video_consumer())
    print(f"[WS LOG] Queue initialized and _consumer_task created: {_consumer_task}")

async def play_video(src: str, duration: int = 30):
    """Tell the alerts overlay to play a video through the queue."""
    print(f"[WS LOG] play_video called with src='{src}', duration={duration}")
    _enqueue_payload({"type": "video", "src": src, "duration": duration})

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
    path = poke_vid_dict.get(kind)
    if path:
        await play_video(f"/assets/videos/{path}", _SLEEP["poke"])

async def toggle_webcam_active():
    from obswebsocket import obsws, requests as obs_requests
    OBS_PW = os.getenv("OBS_PW")
    try:
        ws = obsws("localhost", 4455, OBS_PW)
        ws.connect()
        await asyncio.sleep(1)
        ws.call(obs_requests.PressInputPropertiesButton(
            inputName="BGRemoved Facecam", propertyName="activate"
        ))
        await asyncio.sleep(1)
        ws.call(obs_requests.PressInputPropertiesButton(
            inputName="BGRemoved Facecam", propertyName="activate"
        ))
        ws.disconnect()
    except Exception as exc:
        print(f"[WS ERROR LOG] toggle_webcam_active failed: {exc}")

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

async def play_me(index, scene_index: str, sleep_time=30):
    BASE = "/assets/videos/"
    if scene_index in ("7 131", "7 132", "7 133", "7 1 9"):
        ts_pools = {
            "7 131": lambda: _list_folder("TomScott/Where"),
            "7 132": lambda: _list_folder("TomScott/What"),
            "7 133": lambda: _list_folder("TomScott/Welcome"),
            "7 1 9":  lambda: _list_folder("Outtakes"),
        }
        pool = ts_pools[scene_index]()
        src = random.choice(pool) if pool else None
    else:
        src = BASE + index if index else None

    if src:
        await play_video(src, sleep_time)

FILTER_SOURCE_NAME = "5 Facecam Import for Server"
FILTER_NAME = "Phase-E"

FILTER_PARAMS = {
    "cells_h":    {"type": "int",   "default": 160, "min": 1,   "max": 320},
    "cells_v":    {"type": "int",   "default": 40,  "min": 1,   "max": 180},
    "num_colours":{"type": "int",   "default": 4,   "min": 1,   "max": 20},
    "tol_x":      {"type": "float", "default": 0.7, "min": 0.0, "max": 2.0},
    "tol_y":      {"type": "float", "default": 0.7, "min": 0.0, "max": 2.0},
    "tol_sat":    {"type": "float", "default": 0.1, "min": 0.0, "max": 1.0},
    "dyn_sat":    {"type": "bool",  "default": True},
    "dyn_val":    {"type": "bool",  "default": False},
}

async def set_filter_param(param: str, value):
    from obswebsocket import obsws, requests as obs_req
    OBS_PW = os.getenv("OBS_PW")
    try:
        ws = obsws("localhost", 4455, OBS_PW)
        ws.connect()
        try:
            ws.call(obs_req.SetSourceFilterSettings(
                sourceName=FILTER_SOURCE_NAME,
                filterName=FILTER_NAME,
                filterSettings={param: value},
                overlay=True,
            ))
        finally:
            ws.disconnect()
    except Exception as exc:
        print(f"[WS ERROR LOG] set_filter_param failed: {exc}")