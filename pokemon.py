import asyncio
import os
from pathlib import Path
import requests
from WhoDisPokemon.main import prepare_answer, prepare_question

HERE = Path(os.path.dirname(__file__))
OUTPUT_FOLDER = HERE / "stream-overlay" / "public" / "assets" / "videos" / "Pokemon"
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
    "shadow"
]

dex = 22


async def get_pokemon_type_list(poke_type: str):
    """Fetches list of Dex IDs for a given type in a single fast HTTP call."""
    base_url = f"https://pokeapi.co/api/v2/type/{poke_type.lower().strip()}"
    try:
        response = await asyncio.to_thread(requests.get, base_url, timeout=5)
        if response.status_code != 200:
            print(f"[POKEMON ERROR LOG] PokéAPI returned status {response.status_code}")
            return []
            
        data = response.json()
        my_list = []
        for entry in data.get("pokemon", []):
            url = entry['pokemon']['url']
            # Parse ID directly from URL string (e.g., 'https://pokeapi.co/api/v2/pokemon/25/')
            poke_id = int(url.rstrip("/").split("/")[-1])
            if poke_id < 1026:
                my_list.append(poke_id)
        return my_list
    except Exception as exc:
        print(f"[POKEMON ERROR LOG] Failed to fetch type list for '{poke_type}': {exc}")
        return []


def generate_question_video(dex):
    prepare_question(dex, OUTPUT_QUESTION)


def generate_answer_video(dex):
    prepare_answer(dex, OUTPUT_ANSWER)


async def run():
    return await get_pokemon_type_list("fire")


if __name__ == "__main__":
    print(asyncio.run(run()))