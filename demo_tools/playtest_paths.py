"""Folders shared by make_thumbnails.py, discord_scraper.py and upload_playtests.py."""

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from playtest_editor import CSV_PATH

THUMBS_DIR = Path(r"D:\DANVID\darkshoxx\Demos + Puzzles\Thumbnails")   # finished 1280x720 thumbnails
RAW_THUMBS_DIR = THUMBS_DIR / "steam"                                  # raw Steam images (input for make_thumbnails.py)
DATA_PATH = CSV_PATH.with_name("discord_data.json")                    # written by discord_scraper.py, read by upload_playtests.py


def norm_key(text: str) -> str:
    """Lowercase, no accents, letters and digits only: 'Destroy The Moon' == 'destroy the moon!'."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def find_record(data: dict, index, stem: str):
    """Find a game's entry in discord_data.json -> (record or None, note).

    Tried in order: the CSV Index stored by the scraper (the names must still look alike), the exact
    key, the key ignoring case/punctuation/spacing. Deliberately no fuzzy matching: 'Slag Run' and
    'Slag Run 2' must never be mixed up. `note` says how it matched, or hints at the closest entry."""
    n = norm_key(stem)
    if index:
        for key, rec in data.items():
            if str(rec.get("index") or "") == str(index) and SequenceMatcher(None, n, norm_key(key)).ratio() >= 0.6:
                return rec, ("" if key == stem else f"found by Index {index} (entry '{key}')")
    if stem in data:
        return data[stem], ""
    for key, rec in data.items():
        if norm_key(key) == n:
            return rec, f"found as '{key}' (differs in case/spacing)"
    best = max(((SequenceMatcher(None, n, norm_key(k)).ratio(), k) for k in data), default=(0.0, None))
    return None, (f"closest entry in the data file: '{best[1]}' ({best[0]:.0%})" if best[1] else "the data file is empty")
