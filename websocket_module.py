"""
Inspired by (and with permission from) the Online Ocarina Simulator by vaexenc
https://ocarina.toomuchofheaven.com/
https://github.com/vaexenc/ocarina
"""

import asyncio
import os
import random

from dotenv import load_dotenv
from obswebsocket import obsws, requests

HERE = os.path.abspath(os.path.dirname(__file__))
ENV = os.path.join(HERE, ".env")
load_dotenv(ENV)

OBS_IP = os.getenv("OBS_IP")
OBS_PW = os.getenv("OBS_PW")


host = "localhost"
port = 4455

ws = obsws(host, port, OBS_PW)
ws.connect()

oot_song_dict = {
    "<^><^>": 1,
    ">v^>v^": 2,
    "vava>v>v": 3,
    "^<>^<>": 4,
    "a^<><>": 5,
    "<>>a<>v": 6,
    "^>^><^": 7,
    "ava>va": 8,
    "v><v><": 9,
    "av>><": 10,
    "av^av^": 11,
    ">av>av": 12,
    }

loom_song_dict = {
    "eced": 1,
    "cfgc": 2
}

shiv_song_dict = {
    "ramtabobataramba": 1,
}

myst_song_dict = {
    "c1c2d#2f1a#0": 2
}

poke_vid_dict = {
    "question": 2,
    "answer": 1

}

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


async def toggle_webcam_active():
    # scenes = ws.call(requests.GetSceneList()).getScenes()
    # facecam_scene = [
    #     dicti
    #     for dicti in scenes
    #     if dicti['sceneName'][:5] == "5 MAI"
    #     ]
    # video_item_list = ws.call(
    #     requests.GetSceneItemList(**facecam_scene[0])
    #     ).getSceneItems()
    # print(video_item_list)
    press_call_once = ws.call(requests.PressInputPropertiesButton(
        inputName="BGRemoved Facecam",
        propertyName="activate"
    ))
    await asyncio.sleep(1)
    press_call_twice = ws.call(requests.PressInputPropertiesButton(
        inputName="BGRemoved Facecam",
        propertyName="activate"
    ))
    print(press_call_once)
    print(press_call_twice)


async def play_me(index: int, scene_index: str, sleep_time=30):

    scenes = ws.call(requests.GetSceneList()).getScenes()
    video_scene = [
        dicti
        for dicti in scenes
        if dicti['sceneName'][:5] == scene_index
        ]
    video_item_list = ws.call(
        requests.GetSceneItemList(**video_scene[0])
        ).getSceneItems()
    mylist = [
        (item['sceneItemId'], item['sourceName'])
        for item in video_item_list
        ]
    print("List of objects found:")
    print(mylist)
    if not index:
        index = random.sample([index for index, _ in mylist], 1)[0]

    the_call = ws.call(requests.SetSceneItemEnabled(
        sceneName=video_scene[0]['sceneName'],
        sceneItemId=index,
        sceneItemEnabled=False
        ))
    print(the_call)
    await asyncio.sleep(1)
    the_call = ws.call(requests.SetSceneItemEnabled(
        sceneName=video_scene[0]['sceneName'],
        sceneItemId=index,
        sceneItemEnabled=True
        ))
    await asyncio.sleep(sleep_time)
    the_call = ws.call(
        requests.SetSceneItemEnabled(
            sceneName=video_scene[0]['sceneName'],
            sceneItemId=index,
            sceneItemEnabled=False
            )
        )

if __name__ == "__main__":
    # asyncio.run(play_me(2, "7 1 5"))
    asyncio.run(toggle_webcam_active())
