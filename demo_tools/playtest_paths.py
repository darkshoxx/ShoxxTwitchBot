"""Folders shared by make_thumbnails.py, discord_scraper.py and upload_playtests.py."""

from pathlib import Path

from playtest_editor import CSV_PATH

THUMBS_DIR = Path(r"D:\DANVID\darkshoxx\Demos + Puzzles\Thumbnails")   # finished 1280x720 thumbnails
RAW_THUMBS_DIR = THUMBS_DIR / "steam"                                  # raw Steam images (input for make_thumbnails.py)
DATA_PATH = CSV_PATH.with_name("discord_data.json")                    # written by discord_scraper.py, read by upload_playtests.py
