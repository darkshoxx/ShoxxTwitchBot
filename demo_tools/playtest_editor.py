#!/usr/bin/env python3
"""Cut playtest segments out of Twitch VODs based on Timestamps.csv.

For every row where Processed is not True and Index is a number, the matching
VOD is located, the [Timestamp IN, Timestamp OUT] section is cut with ffmpeg,
the intro is put in front and the outro behind it, and the result is saved as
"<Game Name> - <Studio>.mp4". The Processed flag is set to True in the CSV right
after each successful cut, so re-running only does the remaining rows.

VOD filenames look like "<index> <flags...> <dd-mm-yy>.mp4", e.g. "10 B P 13-10-26.mp4":
  - first whitespace-separated part  = video index (must equal "Video Index")
  - last whitespace-separated part   = date        (must equal "Date")
  - parts in between                 = flags       (must contain "P")

upload_playtests.py imports the configuration and helpers from this file, so keep
both scripts in the same folder.
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
CSV_PATH = Path(r"D:\DANVID\darkshoxx\Demos + Puzzles\Playtesting Videos\Timestamps.csv")
VODS_DIR = Path(r"D:\DANVID\darkshoxx\Demos + Puzzles\VODs")
OUT_DIR = Path(r"D:\DANVID\darkshoxx\Demos + Puzzles\Playtesting Videos")

ASSETS_DIR = Path(r"D:\DANVID\darkshoxx\Demos + Puzzles\Assets")
INTRO_PATH = ASSETS_DIR / "Intro.mp4"
OUTRO_PATH = ASSETS_DIR / "outro.mkv"
USE_INTRO = True
USE_OUTRO = True

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# Encoder used whenever the video is re-encoded (always the case with intro/outro).
# For an NVIDIA GPU you could try ["-c:v", "h264_nvenc", "-cq", "19", "-preset", "p5"].
VIDEO_ENCODER_ARGS = ["-c:v", "libx264", "-crf", "18", "-preset", "fast"]
AUDIO_ENCODER_ARGS = ["-c:a", "aac", "-b:a", "192k"]

# Only used when BOTH intro and outro are disabled:
# False: stream copy. Fast and lossless, but the cut snaps to the nearest
#        keyframe before the IN point (typically up to ~2s early for Twitch VODs).
# True:  re-encode. Frame-accurate, but much slower.
REENCODE = False

REQUIRED_FLAG = "P"
# --------------------------------------------------------------------------- #

AUDIO_RATE = 48000


def is_true(value) -> bool:
    return (value or "").strip().lower() == "true"


def parse_time(value: str) -> float:
    """'1:14:34' / '14:34' / '34' -> seconds."""
    seconds = 0.0
    for part in value.strip().split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def clean_name(name: str) -> str:
    """Keep only letters and whitespace, then collapse runs of whitespace."""
    kept = "".join(ch for ch in name if ch.isalpha() or ch.isspace())
    return " ".join(kept.split())


def output_filename(row: dict) -> str:
    """'<Game Name> - <Studio>.mp4' with everything but letters/whitespace removed."""
    game, studio = clean_name(row["Game Name"]), clean_name(row["Studio"])
    if not game or not studio:
        raise ValueError(f"game or studio name is empty after cleaning ({row['Game Name']!r} / {row['Studio']!r})")
    return f"{game} - {studio}.mp4"


def find_vod(video_index: int, date: str) -> Path:
    """Find '<index> <flags> <date>.mp4' and verify date and P flag."""
    matches = []
    for path in VODS_DIR.iterdir():
        if path.suffix.lower() != ".mp4":
            continue
        parts = path.stem.split()
        if len(parts) >= 2 and parts[0].isdigit() and int(parts[0]) == video_index:
            matches.append((path, parts))

    if not matches:
        raise LookupError(f"no VOD with index {video_index} in {VODS_DIR}")
    if len(matches) > 1:
        raise LookupError(f"multiple VODs with index {video_index}: " + ", ".join(p.name for p, _ in matches))

    path, parts = matches[0]
    if parts[-1] != date:
        raise LookupError(f"{path.name}: date in filename is {parts[-1]}, CSV says {date}")
    if REQUIRED_FLAG not in {flag.upper() for flag in parts[1:-1]}:
        raise LookupError(f"{path.name}: no '{REQUIRED_FLAG}' flag in filename")
    return path


# --------------------------------------------------------------------------- #
# ffprobe helpers
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=None)
def probe(path: Path) -> dict:
    """Return {'width','height','fps','duration','has_audio'} for a media file."""
    cmd = [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise ValueError(f"could not run '{FFPROBE}': {e}")
    if result.returncode != 0:
        raise ValueError(f"ffprobe failed for {path.name}: {result.stderr.strip()[-200:]}")

    data = json.loads(result.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError(f"{path.name} has no video stream")

    try:
        fps = Fraction(video.get("r_frame_rate", "0/1"))
    except (ValueError, ZeroDivisionError):
        fps = Fraction(0)
    if not 1 <= fps <= 240:
        fps = Fraction(60)

    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": fps,
        "duration": float(data["format"].get("duration", 0)),
        "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
    }


# --------------------------------------------------------------------------- #
# ffmpeg command construction
# --------------------------------------------------------------------------- #
def build_ffmpeg_cmd(src: Path, start: float, end: float, dst: Path) -> list[str]:
    if not (USE_INTRO or USE_OUTRO):
        return build_simple_cmd(src, start, end, dst)
    return build_concat_cmd(src, start, end, dst)


def build_simple_cmd(src: Path, start: float, end: float, dst: Path) -> list[str]:
    cmd = [FFMPEG, "-hide_banner", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{end - start:.3f}"]
    if REENCODE:
        cmd += VIDEO_ENCODER_ARGS + AUDIO_ENCODER_ARGS
    else:
        cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    cmd += ["-movflags", "+faststart", str(dst)]
    return cmd


def build_concat_cmd(src: Path, start: float, end: float, dst: Path) -> list[str]:
    """intro + cut segment + outro, all normalised to the VOD's resolution/fps and re-encoded once."""
    vod = probe(src)
    width, height, fps = vod["width"], vod["height"], vod["fps"]

    # Each segment: (file, options placed before -i, has_audio, duration)
    segments = []
    if USE_INTRO:
        info = probe(INTRO_PATH)
        segments.append((INTRO_PATH, [], info["has_audio"], info["duration"]))
    segments.append((src, ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}"], vod["has_audio"], end - start))
    if USE_OUTRO:
        info = probe(OUTRO_PATH)
        segments.append((OUTRO_PATH, [], info["has_audio"], info["duration"]))

    video_chain = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},"
                   f"format=yuv420p,setpts=PTS-STARTPTS")

    cmd = [FFMPEG, "-hide_banner", "-y"]
    filters = []
    for i, (path, options, has_audio, duration) in enumerate(segments):
        cmd += options + ["-i", str(path)]
        filters.append(f"[{i}:v:0]{video_chain}[v{i}]")
        if has_audio:
            filters.append(f"[{i}:a:0]aformat=sample_rates={AUDIO_RATE}:channel_layouts=stereo,"
                           f"asetpts=PTS-STARTPTS[a{i}]")
        else:  # silent asset: generate silence so concat has audio for every segment
            filters.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=duration={duration:.3f},"
                           f"asetpts=PTS-STARTPTS[a{i}]")

    n = len(segments)
    filters.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]")

    cmd += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]"]
    cmd += VIDEO_ENCODER_ARGS + ["-pix_fmt", "yuv420p"] + AUDIO_ENCODER_ARGS
    cmd += ["-movflags", "+faststart", str(dst)]
    return cmd


# --------------------------------------------------------------------------- #
# CSV helpers
# --------------------------------------------------------------------------- #
def load_csv() -> tuple[list[str], list[dict]]:
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        fieldnames = [name.strip() for name in reader.fieldnames]
        reader.fieldnames = fieldnames
        rows = list(reader)
    return fieldnames, rows


def save_csv(fieldnames: list[str], rows: list[dict]) -> None:
    """Write via a temp file so a crash can't leave a half-written CSV."""
    tmp = CSV_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, CSV_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print what would be done, run nothing")
    args = parser.parse_args()

    needed = [FFPROBE] if (USE_INTRO or USE_OUTRO) else []
    if not args.dry_run:
        needed.append(FFMPEG)
    for tool in needed:
        if shutil.which(tool) is None:
            print(f"'{tool}' not found. Install ffmpeg or set FFMPEG/FFPROBE to the full path.")
            return 1

    for enabled, asset in ((USE_INTRO, INTRO_PATH), (USE_OUTRO, OUTRO_PATH)):
        if enabled and not asset.exists():
            print(f"Asset not found: {asset}")
            return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames, rows = load_csv()

    done = skipped = failed = 0
    for row in rows:
        index = row["Index"].strip()
        label = f"[{index}] {row['Game Name']}"

        if is_true(row["Processed"]):
            continue
        if not index.isdigit():
            continue  # "None" rows: LiveSplit mishaps, nothing to cut

        try:
            start = parse_time(row["Timestamp IN"])
            end = parse_time(row["Timestamp OUT"])
            if end <= start:
                raise ValueError(f"OUT ({row['Timestamp OUT']}) is not after IN ({row['Timestamp IN']})")
            src = find_vod(int(row["Video Index"]), row["Date"].strip())
            dst = OUT_DIR / output_filename(row)
            if dst.exists():
                raise ValueError(f"output already exists ({dst.name})")
            tmp_dst = dst.with_name(dst.stem + ".part.mp4")
            cmd = build_ffmpeg_cmd(src, start, end, tmp_dst)
        except (ValueError, LookupError) as e:
            print(f"SKIP  {label}: {e}")
            skipped += 1
            continue

        if args.dry_run:
            print(f"DRY   {label}: {src.name} -> {dst.name}\n      {subprocess.list2cmdline(cmd)}")
            continue

        print(f"CUT   {label}: {src.name} -> {dst.name}")
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                encoding="utf-8", errors="replace")
        if result.returncode != 0:
            tmp_dst.unlink(missing_ok=True)
            print(f"FAIL  {label}: ffmpeg exited with {result.returncode}\n{result.stderr[-500:]}")
            failed += 1
            continue

        tmp_dst.replace(dst)
        row["Processed"] = "True"
        try:
            save_csv(fieldnames, rows)
        except PermissionError:
            print(f"WARN  cut succeeded, but {CSV_PATH.name} is locked (open in Excel?). "
                  f"Close it, otherwise this row will be skipped as 'output exists' next run.")
            return 1
        done += 1

    print(f"\nDone: {done} cut, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())