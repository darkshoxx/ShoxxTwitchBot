import asyncio
import math
import os
import random
import socket
import threading
import time
import webbrowser
from typing import List
import win32.win32gui as gui
import win32com.client as the_client
from dotenv import load_dotenv
from twitchAPI.chat import Chat, ChatCommand, ChatMessage, EventData
from twitchAPI.oauth import UserAuthenticationStorageHelper, UserAuthenticator
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope, ChatEvent
from websocket_module import (FILTER_PARAMS, set_filter_param, start_video_queue,
                              push_overlay_event, queue_pokemon)
from unidecode import unidecode
import aiohttp

HERE = os.path.abspath(os.path.dirname(__file__))
from pokemon import get_pokemon_type_list, poketypes

try:
    import obspython as obs
    IN_OBS = True
    print("[MAIN LOG] OBS Python module loaded successfully. IN_OBS = True")
except ImportError:
    obs = None
    IN_OBS = False
    print("[MAIN LOG] Running outside OBS context. IN_OBS = False")

if obs:
    try:
        obs.script_log(obs.LOG_INFO, "Import phase start")
        import sys
        obs.script_log(obs.LOG_INFO, f"Python exe: {sys.executable}")
    except Exception as e:
        obs.script_log(obs.LOG_ERROR, str(e))

STREAMING_SOFTWARE = "OBS"

if STREAMING_SOFTWARE == "OBS":
    from websocket_module import (loom_song_dict, myst_song_dict,
                                  oot_song_dict, poke_vid_dict,
                                  shiv_song_dict, play_me, scene_dict,
                                  toggle_webcam_active)
elif STREAMING_SOFTWARE == "SLOBS":
    from websocket_module_SLOBS import (loom_song_dict, myst_song_dict,
                                        oot_song_dict, play_me, poke_vid_dict,
                                        scene_dict, shiv_song_dict,
                                        toggle_webcam_active)

BANFILE = os.path.join(HERE, "banned_terms.txt")
ENV = os.path.join(HERE, ".env")
load_dotenv(ENV)

SE_DASH = "https://streamelements.com/dashboard"
MUSIC_REQUEST_WINDOW_URL = SE_DASH + "/mediarequest/general"
SE_ACTIVITY_FEED_URL = SE_DASH + "/5e9a2c08f268f86e34384b19/activity/popout"
BACKUP_PLAYLIST = (
    "https://www.youtube.com/" +
    "watch?v=ugo6ASPVu9g&list=PL81qmzvK51I2odHo1sarrsWtOtHAQ1hag"
    )

SONG_DICTS = [
    oot_song_dict,
    loom_song_dict,
    shiv_song_dict,
    myst_song_dict,
]

MUSIC_HINTS = [key + "\n" for dicti in SONG_DICTS for key, _ in dicti.items()]
MUSIC_HINTS = "".join(MUSIC_HINTS)
BOT_ACCOUNT = "SHOXX"
if BOT_ACCOUNT == "BFTD":
    client_secret = os.getenv("CLIENT_SECRET_BFTD")
    client_id = os.getenv("CLIENT_ID_BFTD")
elif BOT_ACCOUNT == "SHOXX":
    client_secret = os.getenv("CLIENT_SECRET_SHOXX")
    client_id = os.getenv("CLIENT_ID_SHOXX")
else:
    raise Exception("Invalid Bot Account")

HOST = 'localhost'
PORT = 5003
BROADCASTER_ID = os.getenv("BROADCASTER_ID")
if BOT_ACCOUNT == "BFTD":
    MODERATOR_ID = os.getenv("MODERATOR_ID")
elif BOT_ACCOUNT == "SHOXX":
    MODERATOR_ID = os.getenv("BROADCASTER_ID")
else:
    raise Exception("Invalid Bot Account")

OPERA_PATH = os.getenv("OPERA_PATH")

USER_SCOPE = [
    AuthScope.CHAT_READ,
    AuthScope.CHAT_EDIT,
    AuthScope.MODERATOR_MANAGE_BANNED_USERS,
    AuthScope.MODERATOR_MANAGE_CHAT_MESSAGES
    ]
TARGET_CHANNEL = "darkshoxx"

ABORT = False
auto_spin = False
INTERFACE = r"C:\Code\GithubRepos\Alt-Tab-Randomizer\interface.txt"
POKE_LOG = os.path.join(HERE, "pokelog.txt")
TOKEN_FILE = os.path.join(HERE, "user_token.json")
BAD_TERMS_START = ["aiviewersst", "aiviewerstw", "wantpopular", "wannamorevi", "topviewerss","bestviewers", "cheapviewer", "cheapfollow", "bestfollowe", "viewersstre", "estviewersm"]
BAD_TERMS_END = ["realviewers", "heapviewers", "apfollowers", "stfollowers", "op58.online", "eamboo.live", "vethespace)", "reamboo.org", "xadsxonline", "reamboo.com", "wichmax.com"]
BAD_WITH_APPENDAGE = [shoxxword + starter for shoxxword in ["darkshoxx", "@darkshoxx"] for starter in BAD_TERMS_START]
BAN_TIMEOUT = 5

def render_emotes(text: str, emotes: dict) -> str:
    print(f"[MAIN LOG] Rendering emotes for text: '{text}' | Emotes dict: {emotes}")
    if not emotes:
        import html
        return html.escape(text)
 
    ranges = []
    for emote_id, positions in emotes.items():
        for pos in positions:
            ranges.append((int(pos['start_position']), int(pos['end_position']), emote_id))
    ranges.sort(key=lambda x: x[0])
 
    import html
    result = []
    cursor = 0
    for start, end, emote_id in ranges:
        result.append(html.escape(text[cursor:start]))
        result.append(
            f'<img src="https://static-cdn.jtvnw.net/emoticons/v2/{emote_id}'
            f'/default/dark/1.0" class="emote" alt="{html.escape(text[start:end+1])}">'
        )
        cursor = end + 1
    result.append(html.escape(text[cursor:]))
    rendered = ''.join(result)
    print(f"[MAIN LOG] Emote rendering result: '{rendered}'")
    return rendered

def put_wheel_in_foreground():
    print("[MAIN LOG] Putting Wheel window in foreground...")
    import pythoncom
    wheel_handles = get_wheel_handle_list()
    print(f"[MAIN LOG] Found wheel handles: {wheel_handles}")
    for handle in wheel_handles:
        shell = the_client.Dispatch("WScript.Shell", pythoncom.CoInitialize())
        shell.SendKeys("%")
        gui.SetForegroundWindow(handle)

def get_wheel_handle_list() -> List[int]:
    all_handles_list = get_all_handles()
    returned_handles = []
    for handle in all_handles_list:
        if "WheelV1" in gui.GetWindowText(handle) and (
                "Processing" not in gui.GetWindowText(handle)
                ):
            returned_handles.append(handle)
    return returned_handles

def get_all_handles() -> List:
    current_handle = 0
    while current_handle == 0:
        current_handle = gui.GetForegroundWindow()
    list_of_handles = [current_handle]
    next_handles = get_half_handles(current_handle, "next")
    previous_handles = get_half_handles(current_handle, "previous")
    list_of_handles += next_handles
    list_of_handles += previous_handles
    return list_of_handles

def get_half_handles(current_handle: List[int], direction: str) -> List[int]:
    if direction == "next":
        direction_int = 3
    elif direction == "previous":
        direction_int = 2
    else:
        raise Exception("Invalid search direction")
    got_a_new_window = True
    half_handles_list = []
    while got_a_new_window:
        current_handle = gui.GetWindow(current_handle, direction_int)
        if (current_handle not in half_handles_list) and current_handle != 0:
            half_handles_list.append(current_handle)
        else:
            got_a_new_window = False
    return half_handles_list

def test_for_best_viewers(message: str):
    message_stripped = message.replace('"', "").replace("'", "").replace(
        " ",
        ""
        )
    message_normalized = unidecode(message_stripped)
    message_for_comparsion = message_normalized.lower()
    message_trunc_start = message_for_comparsion[:11]
    message_trunc_end = message_for_comparsion[-11:]
    print("truncated message:", message_trunc_start)
    if (message_trunc_start in BAD_TERMS_START):
        print(f"[MAIN LOG] Match found in BAD_TERMS_START for: {message_trunc_start}")
        return True
    if (message_trunc_start in BAD_WITH_APPENDAGE):
        print(f"[MAIN LOG] Match found in BAD_WITH_APPENDAGE for: {message_trunc_start}")
        return True
    if (message_trunc_end in BAD_TERMS_END):
        print(f"[MAIN LOG] Match found in BAD_TERMS_END for: {message_trunc_end}")
        return True
    return False

def test_for_bot(message):
    contains_best_viewers = test_for_best_viewers(message)
    print(f"[MAIN LOG] Bot check result for message '{message}': {contains_best_viewers}")
    return contains_best_viewers

async def begin_ban_countdown(message: ChatMessage):
    print(f"[MAIN LOG] Starting ban countdown for user: {message.user.name}")
    await message.reply(
        f"Warning! You ({message.user.name}) will be bonked " +
        f"in {BAN_TIMEOUT} seconds! To avoid ban, type 'abort' in chat!"
        )
    for i in range(BAN_TIMEOUT):
        index = BAN_TIMEOUT - i
        await asyncio.sleep(1)
        is_aborted = await get_abort()
        print(f"[MAIN LOG] Ban countdown tick: {index}s remaining | Aborted status: {is_aborted}")
        if (index < 4):
            await message.reply(str(index) + " " + message.user.name + " BOP")
    await asyncio.sleep(1)
    if (is_aborted):
        print(f"[MAIN LOG] Ban countdown aborted for user: {message.user.name}")
        await message.reply("Your Life was spared!")
    else:
        print(f"[MAIN LOG] Ban countdown completed. User {message.user.name} fate sealed.")
        await message.reply("YOUR FATE WAS SEALED! BONK BOP")
        if (message.first):
            return message.user

async def test_message_for_violations(bot: Chat, message: ChatMessage) -> bool:
    is_bot = test_for_bot(message.text)
    if (is_bot):
        print(f"[MAIN LOG] Violation detected in message: '{message.text}' by user: {message.user.name}")
        to_ban = await begin_ban_countdown(message)
        if (to_ban):
            print(f"[MAIN LOG] Banning user via Twitch API: {to_ban.name} (ID: {to_ban.id})")
            await bot.twitch.ban_user(
                BROADCASTER_ID,
                MODERATOR_ID,
                to_ban.id,
                "GET REKT"
                )
            await push_overlay_event({"type": "ban", "user": to_ban.name})
        return True
    return False

async def auto_spinner(spin):
    print(f"[MAIN LOG] auto_spinner task started. Initial spin arg: {spin}")
    if spin:
        AUTO_SLEEP = 3*60
        while True:
            await asyncio.sleep(1)

            if auto_spin:
                print("[MAIN LOG] auto_spin is enabled. Sending spin...")
                send_spin()
                await asyncio.sleep(AUTO_SLEEP)

async def on_ready(ready_event: EventData):
    print('Bot is ready for work, joining channels')
    print(f"[MAIN LOG] Joining room: {TARGET_CHANNEL}")
    await ready_event.chat.join_room(TARGET_CHANNEL)

async def test_message_for_skip(bot: Chat, msg: ChatMessage):
    if (msg.text.lower() == "skip"):
        print(f"[MAIN LOG] received SKIP command from user {msg.user.name}")
        write_to_file(msg.user.name, INTERFACE)
        await asyncio.sleep(1)
        return True
    return False

def write_to_file(string: str, filename: str) -> None:
    print(f"[MAIN LOG] Writing string '{string}' to file: {filename}")
    with open(filename, mode="w") as file_object:
        file_object.write(string)

async def test_message_for_abort(msg: ChatMessage):
    if (msg.text.lower() == "abort"):
        print(f"[MAIN LOG] received ABORT command from user {msg.user.name}")
        await set_abort(True)
        await asyncio.sleep(BAN_TIMEOUT)
        return True
    return False

async def test_message_for_music_hints(msg: ChatMessage):
    if msg.text[:5] == "hints":
        print(f"[MAIN LOG] hints requested by {msg.user.name}")
        await msg.reply(f"Here are the music hints:{MUSIC_HINTS}")

async def test_message_for_filter(msg: ChatMessage):
    text = msg.text.strip()
    if text.lower() == "!ascii":
        print(f"[MAIN LOG] ASCII filter params requested by {msg.user.name}")
        parts = []
        for name, p in FILTER_PARAMS.items():
            if p["type"] == "bool":
                parts.append(f"{name}={'on' if p['default'] else 'off'}")
            else:
                parts.append(f"{name}={p['default']} [{p['min']}-{p['max']}]")
        await msg.reply("ASCII filter params: " + "  |  ".join(parts))
        return
    if text.lower() == "!asciidefault":
        print(f"[MAIN LOG] Resetting ASCII filter parameters to defaults via request from {msg.user.name}")
        for name, p in FILTER_PARAMS.items():
            await set_filter_param(name, p["default"])
        await msg.reply("ASCII filter reset to defaults.")
        return
    if not text.lower().startswith("!filter "):
        return
    parts = text.split()
    if len(parts) != 3:
        await msg.reply("Usage: !filter <variable> <value>")
        return

    _, param, raw_value = parts
    param = param.lower()

    if param not in FILTER_PARAMS:
        await msg.reply(f"Unknown param '{param}'. Use !ascii to see all params.")
        return

    p = FILTER_PARAMS[param]

    try:
        if p["type"] == "int":
            value = int(raw_value)
            if not (p["min"] <= value <= p["max"]):
                await msg.reply(f"{param} must be between {p['min']} and {p['max']}.")
                return
        elif p["type"] == "float":
            value = float(raw_value)
            if not (p["min"] <= value <= p["max"]):
                await msg.reply(f"{param} must be between {p['min']} and {p['max']}.")
                return
        elif p["type"] == "bool":
            if raw_value.lower() in ("true", "on", "1", "yes"):
                value = True
            elif raw_value.lower() in ("false", "off", "0", "no"):
                value = False
            else:
                await msg.reply(f"{param} must be on/off.")
                return
    except ValueError:
        await msg.reply(f"Invalid value '{raw_value}' for {param}.")
        return

    print(f"[MAIN LOG] Setting filter param '{param}' to {value}")
    await set_filter_param(param, value)
    await msg.reply(f"ASCII filter: {param} set to {value}.")

async def set_abort(set_to: bool):
    global ABORT
    print(f"[MAIN LOG] Global ABORT set to: {set_to}")
    ABORT = set_to

async def get_abort():
    global ABORT
    return ABORT

async def test_command(cmd: ChatCommand):
    print(f"[MAIN LOG] Received chat command: !{cmd.name} with params: {cmd.parameter}")
    if len(cmd.parameter) == 0:
        await cmd.reply('you did not tell me what to reply with')
    else:
        await cmd.reply(f'{cmd.user.name}: {cmd.parameter}')

def send_spin():
    print(f"[MAIN LOG] Connecting to socket {HOST}:{PORT} to send spin trigger...")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((HOST, PORT))
            s.sendall(b'Spin Wheel of Ixupi')
            print(f"[MAIN LOG] Successfully sent 'Spin Wheel of Ixupi' socket message.")
    except Exception as exc:
        print(f"[MAIN LOG ERROR] Socket send_spin failed: {exc}")

def get_opera():
    print(f"[MAIN LOG] Registering Opera browser at path: {OPERA_PATH}")
    import webbrowser
    webbrowser.register(
        'opera', None, webbrowser.BackgroundBrowser(OPERA_PATH)
        )
    webbrowser.get("opera")

async def test_message_for_song(msg: ChatMessage):
    clean_text = msg.text.lower().replace(" ", "")
    print(f"[MAIN LOG] Testing message for song trigger: '{clean_text}'")
    if clean_text in oot_song_dict.keys():
        print(f"[MAIN LOG] Matched OOT song: {clean_text}")
        await play_me(oot_song_dict[clean_text], scene_dict["oot"])
    elif clean_text in loom_song_dict.keys():
        print(f"[MAIN LOG] Matched Loom song: {clean_text}")
        await play_me(loom_song_dict[clean_text], scene_dict["loom"])
    elif clean_text in shiv_song_dict.keys():
        print(f"[MAIN LOG] Matched Shivers song: {clean_text}")
        await play_me(shiv_song_dict[clean_text], scene_dict["shiv"])
    elif clean_text in myst_song_dict.keys():
        print(f"[MAIN LOG] Matched Myst song: {clean_text}")
        await play_me(myst_song_dict[clean_text], scene_dict["myst"])

GEN_POKE_DICT = {
    1: (1, 151),
    2: (152, 251),
    3: (252, 386),
    4: (387, 493),
    5: (494, 649),
    6: (650, 721),
    7: (722, 809),
    8: (810, 905),
    9: (906, 1025),
    }

def random_pokemon(dex_min, dex_max):
    chosen = random.sample(range(dex_min, dex_max), 1)[0]
    print(f"[MAIN LOG] Selected random pokemon index {chosen} between {dex_min} and {dex_max}")
    return chosen

def poke_logger(dex: int):
    print(f"[MAIN LOG] Logging pokemon dex #{dex} to file {POKE_LOG}")
    with open(POKE_LOG, "a") as log_file:
        log_file.write(str(dex) + "\n")

async def test_message_for_pokemon(msg: ChatMessage):
    words = msg.text.split(" ")
    dex = None
    if "pokemon" in words or "Pokemon" in words:
        position = words.index("pokemon") if "pokemon" in words else words.index("Pokemon")
        if len(words) - 1 > position:
            next_word = words[position+1]
            if next_word in poketypes:
                poke_type_list = await get_pokemon_type_list(next_word)
                dex = random.sample(poke_type_list, 1)[0]
            elif len(next_word) == 4 and next_word[:3].lower() == "gen":
                try:
                    generation = int(words[position+1][3:])
                    dex_min, dex_max = GEN_POKE_DICT[generation]
                    dex = random_pokemon(dex_min, dex_max)
                except ValueError:
                    dex = None
            if not dex:
                try:
                    dex = int(words[position+1])
                except ValueError:
                    dex = None
        if dex not in range(1, 1025):
            dex = random_pokemon(1, 1025)
        poke_logger(dex)
        
        print(f"[MAIN LOG] Enqueuing Pokémon event for dex #{dex}")
        await queue_pokemon(dex)

async def test_message_for_submission(msg: ChatMessage):
    words = msg.text.split(" ")
    if words[0] in ["!add", "add", "submit", "!submit", "queue", "!queue"]:
        print(f"[MAIN LOG] Submission trigger detected from {msg.user.name}")
        await msg.reply("No viewerlevels!")

async def test_message_for_banned_terms(bot: Chat, msg: ChatMessage):
    words = msg.text.split(" ")
    with open(BANFILE) as banned_terms_file:
        content = banned_terms_file.read()
        lines = content.split("\n")

    for word in words:
        if word in lines:
            print(f"[MAIN LOG] Banned word found: '{word}'. Deleting message ID: {msg.id}")
            await bot.twitch.delete_chat_message(
                BROADCASTER_ID,
                MODERATOR_ID,
                msg.id
                )

async def test_message_for_tom_scott(msg: ChatMessage):
    words = msg.text.split(" ")
    if words[0].lower() == "where":
        print("WHERE MSG for tom scott")
        await play_me(None, scene_dict["where"])
    if words[0].lower() == "what":
        print("WHAT MSG for tom scott")
        await play_me(None, scene_dict["what"])
    if "welcome" in words or words[0].lower() == "welcome":
        print("WELCOME MSG for tom scott")
        await play_me(None, scene_dict["welcome"])

async def test_message_for_outtake(msg: ChatMessage):
    words = msg.text.split(" ")
    if words[0].lower() == "outtake":
        if msg.user.name.lower() == "darkshoxx":
            print("Status: Outtake")
            await play_me(None, scene_dict["outtake"])

class InheritedBot(Chat):
    COOLDOWN_DICT = {}

    async def on_message(self, msg):
        print(f"[MAIN LOG] Received message event: [{msg.room.name}] {msg.user.name}: '{msg.text}'")
        is_invalid = await test_message_for_violations(self, msg)
        await test_message_for_skip(self, msg)
        await test_message_for_spin(self, msg)
        await toggle_autospin(msg=msg)
        is_abort = await test_message_for_abort(msg)
        await test_message_for_filter(msg)
        await test_message_for_song(msg)
        await test_message_for_music_hints(msg)
        await test_message_for_pokemon(msg)
        await test_message_for_submission(msg)
        await test_message_for_tom_scott(msg)
        await test_message_for_outtake(msg)
        print("is abort:" + str(is_abort))
        if (is_abort):
            print("ABORTED")
            await set_abort(False)
        if (not is_invalid):
            print(f"in {msg.room.name}, {msg.user.name} said {msg.text}")
        else:
            print(
                f"{msg.user.name} Sent an NAUGHTY message in {msg.room.name}!"
                )
        if not is_invalid:
            print(f"[MAIN LOG] Pushing valid chat message to overlay: {msg.user.name}")
            await push_overlay_event({
                "type": "chat",
                "user": msg.user.name,
                "text": render_emotes(msg.text, getattr(msg, 'emotes', None) or {}),
                "isHtml": True,
                "color": getattr(msg.user, 'color', None),
                "badges": list(msg.user.badges.keys()) if msg.user.badges else [],
            })

def kill_inactive_players(bot: InheritedBot):
    players_to_kill = []
    for player, cooldown in bot.COOLDOWN_DICT.items():
        timedelta = abs(math.floor(time.time() - cooldown))
        if timedelta > 60*10:
            players_to_kill.append(player)
    print(f"[MAIN LOG] Removing inactive cooldown players: {players_to_kill}")
    for player in players_to_kill:
        bot.COOLDOWN_DICT.pop(player)

async def toggle_autospin(msg: ChatMessage):
    global auto_spin
    if msg.user.name.lower() == "darkshoxx":
        if msg.text.lower() == "auto":
            if auto_spin:
                print(f"[MAIN LOG] {msg.user.name} turned off Autospin.")
                await msg.reply(
                    f"{msg.user.name} has turned off Autospin!"
                    )
            else:
                print(f"[MAIN LOG] {msg.user.name} turned on Autospin.")
                await msg.reply(
                    f"{msg.user.name} has turned on Autospin!"
                    )
            auto_spin = not auto_spin

async def test_message_for_spin(bot: InheritedBot, msg: ChatMessage):
    if (msg.text.lower() == "spin"):
        print("received SPIN")
        kill_inactive_players(bot)
        if msg.user.name in bot.COOLDOWN_DICT.keys():
            timedelta = abs(math.floor(
                time.time() - bot.COOLDOWN_DICT[msg.user.name]
                ))
            if timedelta < 60:
                print(f"[MAIN LOG] {msg.user.name} failed spin due to cooldown ({60 - timedelta}s remaining)")
                await msg.reply(
                    f"{msg.user.name} failed SPIN, still on " +
                    f"cooldown for {60 - timedelta} s"
                    )
                spin = False
            else:
                sample_list = [True] + [False]*len(bot.COOLDOWN_DICT)
                success = random.sample(sample_list, 1)[0]
                bot.COOLDOWN_DICT[msg.user.name] = round(time.time())
                if success:
                    print(f"[MAIN LOG] {msg.user.name} succeeded spin roll!")
                    spin = True
                else:
                    print(f"[MAIN LOG] {msg.user.name} failed spin roll.")
                    await msg.reply(
                        f"{msg.user.name} failed SPIN, better luck next time!"
                        )
                    spin = False
        else:
            bot.COOLDOWN_DICT[msg.user.name] = round(time.time())
            spin = True
        if spin:
            print(f"[MAIN LOG] {msg.user.name} successfully redeemed spin.")
            await msg.reply(f"{msg.user.name} Successfully redeemed SPIN")
            send_spin()
            await push_overlay_event({"type":"spin", "user": msg.user.name})
            spin = False

stop_event = None

async def run():
    global stop_event
    stop_event = asyncio.Event()
    
    print("Bot starting in 2 seconds...")
    print("MSG for tom scott")
    await asyncio.sleep(2)
    print(f"[MAIN LOG] Initializing Twitch client with Client ID: {client_id[:5]}...")
    twitch = await Twitch(client_id, client_secret)

    get_opera()
    if BOT_ACCOUNT == "BFTD":
        browser_name = "opera"
    elif BOT_ACCOUNT == "SHOXX":
        browser_name = None
    else:
        raise Exception("How did you even get here??? INVALID BOT ACCOUNT!")

    async def my_user_auth_function(twitch, user_scope):
        print(f"[MAIN LOG] Authenticating user via browser: {browser_name}")
        auth = UserAuthenticator(twitch, user_scope, force_verify=False)

        return await auth.authenticate(browser_name=browser_name)

    helper = UserAuthenticationStorageHelper(
        twitch,
        USER_SCOPE,
        storage_path=TOKEN_FILE,
        auth_generator_func=my_user_auth_function)
    print(f"[MAIN LOG] Binding UserAuthenticationStorageHelper with token path: {TOKEN_FILE}")
    await helper.bind()

    chat = await InheritedBot(twitch)

    chat.register_event(ChatEvent.READY, on_ready)
    chat.register_event(ChatEvent.MESSAGE, chat.on_message)

    chat.register_command('reply', test_command)

    print("[MAIN LOG] Starting Chat Client...")
    chat.start()

    print("[MAIN LOG] Initializing video queue in websocket module...")
    await start_video_queue()
    
    print("[MAIN LOG] Toggling webcam active status...")
    await toggle_webcam_active()
    
    print(f"[MAIN LOG] Opening activity feed: {SE_ACTIVITY_FEED_URL}")
    webbrowser.open(SE_ACTIVITY_FEED_URL)
    
    print(f"[MAIN LOG] Opening playlist: {BACKUP_PLAYLIST}")
    webbrowser.open(BACKUP_PLAYLIST)

    spin = False

    print("[MAIN LOG] Launching auto_spinner task...")
    asyncio.create_task(auto_spinner(spin))

    try:
        if IN_OBS:
            print("[MAIN LOG] Waiting on stop_event (IN_OBS mode)...")
            await stop_event.wait()
        else:
            print("[MAIN LOG] Running in CLI mode. Waiting for user ENTER key...")
            input('press ENTER to stop\n')
    finally:
        print("[MAIN LOG] Cleanup started: stopping chat client and closing Twitch connection.")
        chat.stop()
        await twitch.close()


bot_thread = None
running = False
node_process = None
import subprocess

def start_bot():
    global bot_thread
    print("[MAIN LOG] start_bot() called.")
    if bot_thread and bot_thread.is_alive():
        print("[MAIN LOG] bot_thread is already alive. Skipping start_bot().")
        return
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("[MAIN LOG] Launched bot_thread.")

def stop_bot():
    global bot_thread, stop_event
    print("[MAIN LOG] stop_bot() called.")
    if loop and loop.is_running() and stop_event is not None:
        print("[MAIN LOG] Signaling stop_event threadsafe...")
        loop.call_soon_threadsafe(stop_event.set)
    
    if bot_thread and bot_thread.is_alive():
        print("[MAIN LOG] Joining bot_thread with timeout=3s...")
        bot_thread.join(timeout=3)
        print("[MAIN LOG] bot_thread join finished.")

def run_bot():
    global loop
    print("[MAIN LOG] run_bot() starting new event loop...")
    local_loop = asyncio.new_event_loop()
    loop = local_loop
    asyncio.set_event_loop(local_loop)
    
    try:
        local_loop.run_until_complete(run())
    finally:
        print("[MAIN LOG] Closing local event loop in run_bot().")
        local_loop.close()

def script_load(settings):
    global node_process
    print("[MAIN LOG] OBS script_load() called.")
    server_dir = os.path.join(HERE, "stream-overlay")
    print(f"[MAIN LOG] Starting node server process in {server_dir}...")
    node_process = subprocess.Popen(["node", "server.js"], cwd=server_dir)
    print(f"[MAIN LOG] Node process PID: {node_process.pid}")
    start_bot()

def script_unload():
    print("[MAIN LOG] OBS script_unload() called.")
    stop_bot()
    global node_process
    if node_process:
        print(f"[MAIN LOG] Terminating node process PID: {node_process.pid}")
        node_process.terminate()
        node_process.wait()
        print("[MAIN LOG] Node process terminated.")

if __name__ == "__main__" and not IN_OBS:
    print("[MAIN LOG] Running main script directly.")
    asyncio.run(run())