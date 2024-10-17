import os

from WhoDisPokemon.main import prepare_answer, prepare_question

HERE = os.path.abspath(os.path.dirname(__file__))
OUTPUT_FOLDER = os.path.join(HERE, "output")
OUTPUT_QUESTION = os.path.join(OUTPUT_FOLDER, "question.mp4")
OUTPUT_ANSWER = os.path.join(OUTPUT_FOLDER, "answer.mp4")

dex = 22


def generate_question_video(dex):
    prepare_question(dex, OUTPUT_QUESTION)


def generate_answer_video(dex):
    prepare_answer(dex, OUTPUT_ANSWER)
