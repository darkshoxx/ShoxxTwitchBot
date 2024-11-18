import asyncio
import os

import requests
from WhoDisPokemon.main import prepare_answer, prepare_question

HERE = os.path.abspath(os.path.dirname(__file__))
OUTPUT_FOLDER = os.path.join(HERE, "output")
OUTPUT_QUESTION = os.path.join(OUTPUT_FOLDER, "question.mp4")
OUTPUT_ANSWER = os.path.join(OUTPUT_FOLDER, "answer.mp4")

poketypes = [
    "normal",
    "fighting",
    "flying",
    "poison",
    "ground",
    "rock",
    "bug",
    "ghost",
    "steel",
    "fire",
    "water",
    "grass",
    "electric",
    "psychic",
    "ice",
    "dragon",
    "dark",
    "fairy",
    "unknown",
    "shadow"
]

dex = 22


async def get_pokemon_type_list(poke_type):
    base_url = "https://pokeapi.co/api/v2/type/"
    full_url = base_url + poke_type
    poke_type_request = await asyncio.to_thread(requests.get, full_url)
    type_types = poke_type_request.json()

    my_list = []
    for type_pokemon in type_types["pokemon"]:
        type_pokemon_url = type_pokemon['pokemon']['url']
        type_pokemon_request = await asyncio.to_thread(
            requests.get,
            type_pokemon_url,
            timeout=3
            )
        type_pokemon_json = type_pokemon_request.json()
        if type_pokemon_json['id'] < 1026:
            my_list.append(int(type_pokemon_json['id']))
    return my_list


def generate_question_video(dex):
    prepare_question(dex, OUTPUT_QUESTION)


def generate_answer_video(dex):
    prepare_answer(dex, OUTPUT_ANSWER)


async def run():
    return await get_pokemon_type_list("fire")


if __name__ == "__main__":
    print(asyncio.run(run()))
