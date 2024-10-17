import asyncio
import math
import os
import random
import socket
import time
from typing import List

import win32.win32gui as gui
import win32com.client as the_client
from dotenv import load_dotenv
from twitchAPI.chat import Chat, ChatCommand, ChatMessage, EventData
from twitchAPI.oauth import UserAuthenticationStorageHelper, UserAuthenticator
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope, ChatEvent
from unidecode import unidecode

from pokemon import (generate_answer_video, generate_question_video,
                     get_pokemon_type_list, poketypes)
from websocket_module import (loom_song_dict, myst_song_dict, oot_song_dict,
                              play_me, poke_vid_dict, scene_dict,
                              shiv_song_dict)

HERE = os.path.abspath(os.path.dirname(__file__))
ENV = os.path.join(HERE, ".env")
load_dotenv(ENV)


SONG_DICTS = [
    oot_song_dict,
    loom_song_dict,
    shiv_song_dict,
    myst_song_dict,
]

MUSIC_HINTS = [key + "\n" for dicti in SONG_DICTS for key, _ in dicti.items()]
MUSIC_HINTS = "".join(MUSIC_HINTS)
BOT_ACCOUNT = "BFTD"  # BFTD / SHOXX
if BOT_ACCOUNT == "BFTD":
    client_secret = os.getenv("CLIENT_SECRET_BFTD")
    client_id = os.getenv("CLIENT_ID_BFTD")
elif BOT_ACCOUNT == "SHOXX":
    client_secret = os.getenv("CLIENT_SECRET_SHOXX")
    client_id = os.getenv("CLIENT_ID_SHOXX")
else:
    raise Exception("Invalid Bot Account")

# Replace with the IP address of your Processing server if necessary
HOST = 'localhost'
# The port used by the Processing server
PORT = 5002

BROADCASTER_ID = os.getenv("BROADCASTER_ID")
MODERATOR_ID = os.getenv("MODERATOR_ID")

# I'm using my non-default browser here,
# because the default will log me in instead of my bot.
OPERA_PATH = os.getenv("OPERA_PATH")

USER_SCOPE = [
    AuthScope.CHAT_READ,
    AuthScope.CHAT_EDIT,
    AuthScope.MODERATOR_MANAGE_BANNED_USERS,
    AuthScope.MODERATOR_MANAGE_CHAT_MESSAGES
    ]
TARGET_CHANNEL = "darkshoxx"

ABORT = False
# Path for Grandomizer Shenanigans
INTERFACE = r"C:\Code\GithubRepos\Alt-Tab-Randomizer\interface.txt"

POKE_LOG = os.path.join(HERE, "pokelog.txt")
TOKEN_FILE = os.path.join(HERE, "user_token.json")
BAD_TERMS = ["bestviewers", "cheapviewer"]
BAN_TIMEOUT = 20


# Wheel section
def put_wheel_in_foreground():
    import pythoncom
    wheel_handles = get_wheel_handle_list()
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
    """Returns a list of all handles. Obtains curent foreground window and
    iterates through windows in front and behind."""
    # GetForegroundWindow() can return 0 in certain circumstances. In that
    # case it needs to be reloaded.
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
    """Helper function to iterate over all handles in front/behind the active
    window handle.
    Args:
        current_handle (List[int]): singleton list containing active window
        direction (str): next/previous for search direciton.
    Returns:
        half_handles_list (List[int]): collected list of handles."""
    if direction == "next":
        direction_int = 3
    elif direction == "previous":
        direction_int = 2
    else:
        raise Exception("Invalid search direction")
    got_a_new_window = True
    half_handles_list = []
    # filling the list using gui.GetWindow, which uses direction_int to specify
    # next or previous window.
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
    message_trunc = message_for_comparsion[:11]
    print("truncated message:", message_trunc)
    if (message_trunc in BAD_TERMS):
        return True
    return False


def test_for_bot(message):
    contains_best_viewers = test_for_best_viewers(message)
    return contains_best_viewers


async def begin_ban_countdown(message: ChatMessage):
    await message.reply(
        f"Warning! You ({message.user.name}) will be bonked " +
        f"in {BAN_TIMEOUT} seconds! To avoid ban, type 'abort' in chat!"
        )
    for i in range(BAN_TIMEOUT):
        index = BAN_TIMEOUT - i
        await asyncio.sleep(1)
        is_aborted = await get_abort()
        if (index < 4):
            await message.reply(str(index) + " " + message.user.name + " BOP")
    await asyncio.sleep(1)
    if (is_aborted):
        await message.reply("Your Life was spared!")
    else:
        await message.reply("YOUR FATE WAS SEALED! BONK BOP")
        if (message.first):
            return message.user


async def test_message_for_violations(bot: Chat, message: ChatMessage) -> bool:
    is_bot = test_for_bot(message.text)
    if (is_bot):
        to_ban = await begin_ban_countdown(message)
        if (to_ban):
            await bot.twitch.ban_user(
                BROADCASTER_ID,
                MODERATOR_ID,
                to_ban.id,
                "GET REKT"
                )
        return True
    return False


async def on_ready(ready_event: EventData):
    print('Bot is ready for work, joining channels')
    await ready_event.chat.join_room(TARGET_CHANNEL)


async def test_message_for_skip(bot: Chat, msg: ChatMessage):
    if (msg.text.lower() == "skip"):
        print("received SKIP")
        write_to_file(msg.user.name, INTERFACE)
        await asyncio.sleep(1)
        return True
    return False


def write_to_file(string: str, filename: str) -> None:
    """Helper function to overwrite the text in a file that exists, or create
    said file with that content
    Args:
        string (str): text to be written to file.
        filename (str): string of path to file, or just filename.
    Returns:
        None"""
    with open(filename, mode="w") as file_object:
        file_object.write(string)


async def test_message_for_abort(msg: ChatMessage):
    if (msg.text.lower() == "abort"):
        print("received ABORT")
        await set_abort(True)
        await asyncio.sleep(BAN_TIMEOUT)
        return True
    return False


async def test_message_for_music_hints(msg: ChatMessage):
    if msg.text[:5] == "hints":
        await msg.reply(f"Here are the music hints:{MUSIC_HINTS}")


async def set_abort(set_to: bool):
    global ABORT
    ABORT = set_to


async def get_abort():
    global ABORT
    return ABORT


# this will be called whenever the !reply command is issued
async def test_command(cmd: ChatCommand):
    if len(cmd.parameter) == 0:
        await cmd.reply('you did not tell me what to reply with')
    else:
        await cmd.reply(f'{cmd.user.name}: {cmd.parameter}')


def send_spin():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        s.sendall(b'Spin')


def get_opera():
    import webbrowser
    webbrowser.register(
        'opera', None, webbrowser.BackgroundBrowser(OPERA_PATH)
        )
    webbrowser.get("opera")


async def test_message_for_song(msg: ChatMessage):
    if msg.text in oot_song_dict.keys():
        await play_me(oot_song_dict[msg.text], scene_dict["oot"])
    elif msg.text in loom_song_dict.keys():
        await play_me(loom_song_dict[msg.text], scene_dict["loom"])
    elif msg.text in shiv_song_dict.keys():
        await play_me(shiv_song_dict[msg.text], scene_dict["shiv"])
    elif msg.text in myst_song_dict.keys():
        await play_me(myst_song_dict[msg.text], scene_dict["myst"])


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
    return random.sample(range(dex_min, dex_max), 1)[0]


def poke_logger(dex: int):
    with open(POKE_LOG, "a") as log_file:
        log_file.write(str(dex) + "\n")


async def test_message_for_pokemon(msg: ChatMessage):
    words = msg.text.split(" ")
    dex = None
    if "pokemon" in words or "Pokemon" in words:
        position = words.index("pokemon")
        if len(words) - 1 > position:
            next_word = words[position+1]
            if next_word in poketypes:
                print(next_word)
                poke_type_list = get_pokemon_type_list(next_word)
                dex = random.sample(poke_type_list, 1)[0]
                print(dex)
            elif len(next_word) == 4:
                if next_word[:3].lower() == "gen":
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
        generate_question_video(dex)
        await play_me(
            poke_vid_dict["question"],
            scene_dict["poke"],
            sleep_time=10
            )
        generate_answer_video(dex)
        await play_me(
            poke_vid_dict["answer"],
            scene_dict["poke"],
            sleep_time=10
            )


class InheritedBot(Chat):

    COOLDOWN_DICT = {}

    async def on_message(self, msg):
        is_invalid = await test_message_for_violations(self, msg)
        await test_message_for_skip(self, msg)
        await test_message_for_spin(self, msg)
        is_abort = await test_message_for_abort(msg)
        await test_message_for_song(msg)
        await test_message_for_music_hints(msg)
        await test_message_for_pokemon(msg)
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


def kill_inactive_players(bot: InheritedBot):
    players_to_kill = []
    for player, cooldown in bot.COOLDOWN_DICT.items():
        timedelta = abs(math.floor(time.time() - cooldown))
        if timedelta > 60*10:
            players_to_kill.append(player)
    for player in players_to_kill:
        bot.COOLDOWN_DICT.pop(player)


async def test_message_for_spin(bot: InheritedBot, msg: ChatMessage):
    if (msg.text.lower() == "spin"):
        print("received SPIN")
        kill_inactive_players(bot)
        if msg.user.name in bot.COOLDOWN_DICT.keys():
            timedelta = abs(math.floor(
                time.time() - bot.COOLDOWN_DICT[msg.user.name]
                ))
            if timedelta < 60:
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
                    spin = True
                else:
                    await msg.reply(
                        f"{msg.user.name} failed SPIN, better luck next time!"
                        )
                    spin = False
        else:
            bot.COOLDOWN_DICT[msg.user.name] = round(time.time())
            spin = True
        if spin:
            await msg.reply(f"{msg.user.name} Successfully redeemed SPIN")
            send_spin()
            # put_wheel_in_foreground()
            # hotkey("ctrl","alt","shift")
            spin = False


async def run():
    # Twitch Client (big Daddy)
    twitch = await Twitch(client_id, client_secret)

    get_opera()
    if BOT_ACCOUNT == "BFTD":
        browser_name = "opera"
    elif BOT_ACCOUNT == "SHOXX":
        browser_name = None
    else:
        raise Exception("How did you even get here??? INVALID BOT ACCOUNT!")

    async def my_user_auth_function(twitch, user_scope):
        # This function is required to force the usage of the opera browser
        auth = UserAuthenticator(twitch, user_scope, force_verify=False)

        return await auth.authenticate(browser_name=browser_name)
    # the Auth Helper ensures that the autentication is stored,
    # and needs only be done once.
    helper = UserAuthenticationStorageHelper(
        twitch,
        USER_SCOPE,
        storage_path=TOKEN_FILE,
        auth_generator_func=my_user_auth_function)
    await helper.bind()

    # Chat Client (little Daddy)
    chat = await InheritedBot(twitch)  # Chat(twitch)

    # listen to when the bot is done starting up and ready to join channels
    chat.register_event(ChatEvent.READY, on_ready)
    # listen to chat messages
    chat.register_event(ChatEvent.MESSAGE, chat.on_message)

    # you can directly register commands and their handlers,
    # this will register the !reply command
    chat.register_command('reply', test_command)

    chat.start()

    try:
        input('press ENTER to stop\n')
    finally:
        # now we can close the chat bot and the twitch api client
        chat.stop()
        await twitch.close()

if __name__ == "__main__":
    asyncio.run(run())
