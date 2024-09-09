from twitchAPI.twitch import Twitch
from twitchAPI.helper import first
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.type import AuthScope
from twitchAPI.type import AuthScope, ChatEvent
from twitchAPI.chat import Chat, EventData, ChatMessage, ChatCommand
from unidecode import unidecode
import asyncio

from dotenv import load_dotenv
import os
load_dotenv()

client_secret = os.getenv("CLIENT_SECRET_BFTD")
client_ID = os.getenv("CLIENT_ID_BFTD")

#
BROADCASTER_ID = os.getenv("BROADCASTER_ID")
MODERATOR_ID = os.getenv("MODERATOR_ID")

# I'm using my non-default browser here, because the default will log me in instead of my bot.
OPERA_PATH = os.getenv("OPERA_PATH")

USER_SCOPE = [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT, AuthScope.MODERATOR_MANAGE_BANNED_USERS]
TARGET_CHANNEL = "darkshoxx"

ABORT = False
# Path for Grandomizer Shenanigans
INTERFACE = r"C:\Code\GithubRepos\Alt-Tab-Randomizer\interface.txt"
BAD_TERMS = ["bestviewers","cheapviewer"]
BAN_TIMEOUT = 20

def test_for_best_viewers(message:str):
    message_stripped = message.replace('"', "").replace("'", "").replace(" ", "")
    message_normalized = unidecode(message_stripped)
    message_for_comparsion = message_normalized.lower()
    message_trunc = message_for_comparsion[:11]
    print("truncated message:", message_trunc)
    if(message_trunc in BAD_TERMS):
        return True
    return False

def test_for_bot(message):
    contains_best_viewers = test_for_best_viewers(message)
    return contains_best_viewers

async def begin_ban_countdown(message: ChatMessage):
    await message.reply(f"Warning! You ({message.user.name}) will be bonked in {BAN_TIMEOUT} seconds!")
    for i in range(BAN_TIMEOUT):
        index = BAN_TIMEOUT - i
        await asyncio.sleep(1)
        is_aborted = await get_abort()
        if (index < 4):
            await message.reply(str(index)+ message.user.name + " BOP")
    await asyncio.sleep(1)
    if (is_aborted):
         await message.reply("Your Life was spared!")
    else:
        await message.reply("YOUR FATE WAS SEALED! BONK BOP")
        if (message.first):
            return message.user

async def test_message_for_violations(bot: Chat, message:ChatMessage) -> bool:
    is_bot = test_for_bot(message.text)
    if (is_bot):
        to_ban = await begin_ban_countdown(message)
        if (to_ban):
            await bot.twitch.ban_user(BROADCASTER_ID, MODERATOR_ID, to_ban.id, "GET REKT")
        return True
    return False



async def on_ready(ready_event: EventData):
    print('Bot is ready for work, joining channels') 
    await ready_event.chat.join_room(TARGET_CHANNEL)

async def test_message_for_skip(msg: ChatMessage):
    if (msg.text.lower() =="skip"):
        print("received SKIP")
        write_to_file("Skip", INTERFACE)
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
    if (msg.text.lower() =="abort"):
        print("received ABORT")
        await set_abort(True)
        await asyncio.sleep(BAN_TIMEOUT)
        return True
    return False


async def set_abort(set_to:bool):
    global ABORT
    ABORT = set_to

async def get_abort():
    global ABORT
    return ABORT    

async def on_message(bot:Chat, msg: ChatMessage):
    is_invalid = await test_message_for_violations(bot, msg)
    is_skip = await test_message_for_skip(msg)
    is_abort = await test_message_for_abort(msg)
    print("is abort:" + str(is_abort))
    if (is_abort):
        print("ABORTED")
        await set_abort(False)
    if (not is_invalid):
        print(f"in {msg.room.name}, {msg.user.name} said {msg.text}")
    else:
        print(f" {msg.user.name} Sent an NAUGHTY message in {msg.room.name} !")


# this will be called whenever the !reply command is issued
async def test_command(cmd: ChatCommand):
    if len(cmd.parameter) == 0:
        await cmd.reply('you did not tell me what to reply with')
    else:
        await cmd.reply(f'{cmd.user.name}: {cmd.parameter}')

def get_opera():
    import webbrowser
    

    webbrowser.register('opera', None,webbrowser.BackgroundBrowser(OPERA_PATH))

    _ = webbrowser.get("opera")

class InheritedBot(Chat):

    async def on_message(self, msg):
        is_invalid = await test_message_for_violations(self, msg)
        is_skip = await test_message_for_skip(msg)
        is_abort = await test_message_for_abort(msg)
        print("is abort:" + str(is_abort))
        if (is_abort):
            print("ABORTED")
            await set_abort(False)
        if (not is_invalid):
            print(f"in {msg.room.name}, {msg.user.name} said {msg.text}")
        else:
            print(f" {msg.user.name} Sent an NAUGHTY message in {msg.room.name} !")

async def run():
    # Twitch Client (big Daddy)
    twitch = await Twitch(client_ID, client_secret)

    get_opera()

    auth = UserAuthenticator(twitch, USER_SCOPE, force_verify=False)
    token, refresh_token = await auth.authenticate(browser_name="opera")
    await twitch.set_user_authentication(token, USER_SCOPE, refresh_token)

    # Chat Client (little Daddy)
    chat = await InheritedBot(twitch) #Chat(twitch)
    
    # register the handlers for the events you want
    # from functools import partial

    # async def curried_on_message(twitch):
    #     partial(on_message, twitch)

    # listen to when the bot is done starting up and ready to join channels
    chat.register_event(ChatEvent.READY, on_ready)
    # listen to chat messages
    chat.register_event(ChatEvent.MESSAGE, chat.on_message)    


    # you can directly register commands and their handlers, this will register the !reply command
    chat.register_command('reply', test_command)

    chat.start()

    try:
        input('press ENTER to stop\n')
    finally:
        # now we can close the chat bot and the twitch api client
        chat.stop()
        await twitch.close()

asyncio.run(run())


# async def twitch_example():
#     # Twitch Client (big Daddy)
#     twitch = await Twitch(client_ID, client_secret)

#     # Authentication
#     target_scope = [AuthScope.BITS_READ]
#     auth = UserAuthenticator(twitch, target_scope, force_verify=False)
#     token, refresh_token = await auth.authenticate()
#     await twitch.set_user_authentication(token, target_scope, refresh_token)

#     # Simple user ID call
#     user = await first(twitch.get_users(logins='bot_from_the_dark'))
#     print(user.id)

# asyncio.run(twitch_example())