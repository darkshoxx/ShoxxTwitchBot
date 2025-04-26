"""
Inspired by (and with permission from) the Online Ocarina Simulator by vaexenc
https://ocarina.toomuchofheaven.com/
https://github.com/vaexenc/ocarina
"""
import asyncio
import logging
import random

from pyslobs import (ScenesService, SlobsConnection, SourcesService,
                     config_from_ini)

logging.basicConfig(level=logging.WARNING)


oot_song_dict = {
    "<^><^>": 12,
    ">v^>v^": 11,
    "vAvA>v>v": 10,
    "^<>^<>": 9,
    "A^<><>": 8,
    "<>>A<>v": 7,
    "^>^><^": 6,
    "AvA>vA": 5,
    "v><v><": 4,
    "Av>><": 3,
    "Av^Av^": 2,
    ">Av>Av": 1,
    }


loom_song_dict = {
    "eced": 2,
    "Cfgc": 1
}

shiv_song_dict = {
    "ramtabobataramba": 1,
}

myst_song_dict = {
    "C1C2D#2F1A#0": 1
}

poke_vid_dict = {
    "question": 1,
    "answer": 2
}

scene_dict = {
    "loom": "7 1 6",
    "oot": "7 1 5",
    "shiv": "7 1 7",
    "myst": "7 1 8",
    "poke": "7 1 4",
    "where": "7 131",
    "what": "7 132",
    "welcome": "7 133",
}


async def _toggle_webcam_active(conn):
    scene_service = ScenesService(conn)
    sources_service = SourcesService(conn)
    scenes = await scene_service.get_scenes()
    for scene in scenes:
        if scene.name == "5 MAIN FACECAM":
            items = await scene.get_items()
            camera_item = items[0]
            source_id = camera_item.source_id
            camera_source = await sources_service.get_source(source_id)
            await camera_source.update_settings({'active': False})
            await camera_source.update_settings({'active': True})
    conn.close()


async def _play_me(conn, index: int, scene_index: str, sleep_time=30):
    scene_service = ScenesService(conn)
    scenes = await scene_service.get_scenes()
    video_scene = [
        dicti
        for dicti in scenes
        if dicti.name[:5] == scene_index
    ][0]
    video_item_list = await video_scene.get_items()
    mylist = [
        (item, item.name)
        for item in video_item_list
        ]
    if not index:
        scene_item = random.sample([index for index, _ in mylist], 1)[0]
    else:
        scene_item = mylist[index-1][0]
    await scene_item.set_visibility(False)
    await asyncio.sleep(1)
    await scene_item.set_visibility(True)
    await asyncio.sleep(sleep_time)
    await scene_item.set_visibility(False)
    conn.close()


async def toggle_webcam_active():
    connection = SlobsConnection(config_from_ini())
    await asyncio.gather(
        connection.background_processing(),
        _toggle_webcam_active(connection)
        )


async def play_me(index: int, scene_index: str, sleep_time=30):
    connection = SlobsConnection(config_from_ini())
    await asyncio.gather(
        connection.background_processing(),
        _play_me(connection, index, scene_index, sleep_time)
        )


if __name__ == "__main__":
    asyncio.run(toggle_webcam_active())
    asyncio.run(play_me(2, "7 1 5"))
