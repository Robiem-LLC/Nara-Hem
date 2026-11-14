"""Cut the recorded tour into web-ready clips for the showcase site.

    python tools/showcase/clips.py RECORDING_FOLDER SITE_MEDIA_FOLDER

Reads web-tour.webm and chapters.json from the recording and writes an H.264
MP4 per chapter (plays everywhere, including iPhone Safari), the full tour,
and the stills, all of which the site references by name. When they were
filmed, it also cuts the setup clips: one per web setup step (setup.webm) and
each phone's setup with its captions burned in.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ENCODE = [
    "-an",
    "-c:v",
    "libx264",
    "-preset",
    "slow",
    "-crf",
    "24",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    "-vf",
    "scale=1280:-2",
]

PORTRAIT = [
    "-an",
    "-c:v",
    "libx264",
    "-preset",
    "slow",
    "-crf",
    "26",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
]

FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def ffmpeg(*args):
    """Runs ffmpeg quietly and raises if it fails."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError("ffmpeg: " + (result.stderr.strip().splitlines() or ["failed"])[-1])


def caption_filter(captions, folder, offset=0.0):
    """Returns drawtext filters that show each caption at the bottom of a portrait video."""
    font = next((f for f in FONTS if Path(f).exists()), None)
    filters = []
    for index, caption in enumerate(captions):
        start, end = caption["start"] - offset, caption["end"] - offset
        if end <= 0:
            continue
        text = folder / f"caption-{index}.txt"
        # A text file, so quotes and colons in the caption need no escaping.
        text.write_text("\n".join(textwrap.wrap(caption["text"], 28)))
        filters.append(
            "drawtext="
            + (f"fontfile={font}:" if font else "")
            + f"textfile={text}:fontcolor=white:fontsize=w/24:line_spacing=8:"
            + "box=1:boxcolor=0x06143A@0.9:boxborderw=18:"
            + "x=(w-text_w)/2:y=h-text_h-h/9:"
            + f"enable='between(t,{max(start, 0):.2f},{end:.2f})'"
        )
    return filters


def phone_setup(recording, media, platform):
    """Cuts a phone's setup clip, with its captions burned in."""
    marks = recording / f"{platform}-captions.json"
    if platform == "ios":
        video, chapters = recording / "ios-tour.mp4", recording / "ios-chapters.json"
        if not video.exists() or not chapters.exists():
            return
        signin = [c for c in json.loads(chapters.read_text()) if c["name"] == "signin"]
        if not signin:
            return
        start, length = signin[0]["start"], signin[0]["end"] - signin[0]["start"] + 3
    else:
        video, start, length = recording / "android-setup.mp4", 0.0, None
        if not video.exists():
            return
    captions = json.loads(marks.read_text()) if marks.exists() else []
    output = media / f"{platform}-setup.mp4"
    with tempfile.TemporaryDirectory() as folder:
        filters = ["scale=-2:1280", "fps=30", *caption_filter(captions, Path(folder), start)]
        cut = ["-ss", f"{start:.2f}", "-i", str(video)] + (
            ["-t", f"{length:.2f}"] if length else []
        )
        try:
            ffmpeg(*cut, *PORTRAIT, "-vf", ",".join(filters), str(output))
        except RuntimeError as error:
            # Without captions rather than without a video.
            print(f"::warning title={platform} setup captions skipped::{error}", file=sys.stderr)
            ffmpeg(*cut, *PORTRAIT, "-vf", "scale=-2:1280,fps=30", str(output))


def web_setup(recording, media):
    """Cuts the web setup recording into one clip per step."""
    video, chapters = recording / "setup.webm", recording / "setup-chapters.json"
    if not video.exists() or not chapters.exists():
        return
    for chapter in json.loads(chapters.read_text()):
        start, length = chapter["start"] + 0.3, chapter["end"] - chapter["start"] - 0.3
        ffmpeg(
            "-ss",
            f"{start:.2f}",
            "-i",
            str(video),
            "-t",
            f"{length:.2f}",
            *ENCODE,
            str(media / f"{chapter['name']}.mp4"),
        )


def phone(recording, media, platform):
    """Cuts a phone recording from the point it reaches the map."""
    video, marks = recording / f"{platform}-tour.mp4", recording / f"{platform}-chapters.json"
    if not video.exists() or not marks.exists():
        return
    chapters = json.loads(marks.read_text())
    tour = [c for c in chapters if c["name"] != "signin"]
    if not tour:
        return
    start, end = tour[0]["start"] + 0.5, tour[-1]["end"]
    portrait = [
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "26",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-vf",
        "scale=-2:1280,fps=30",
    ]
    ffmpeg(
        "-ss",
        f"{start:.2f}",
        "-i",
        str(video),
        "-t",
        f"{end - start:.2f}",
        *portrait,
        str(media / f"{platform}.mp4"),
    )
    ffmpeg(
        "-ss",
        f"{start + 6:.2f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        "scale=-2:1280",
        str(media / f"{platform}.png"),
    )


def main(recording, media):
    """Cuts the showcase recording into the clips the site uses."""
    recording, media = Path(recording), Path(media)
    media.mkdir(parents=True, exist_ok=True)
    tour = recording / "web-tour.webm"
    for chapter in json.loads((recording / "chapters.json").read_text()):
        # Skip the first half second of each chapter: the page is still drawing.
        start, length = chapter["start"] + 0.5, chapter["end"] - chapter["start"] - 0.5
        ffmpeg(
            "-ss",
            f"{start:.2f}",
            "-i",
            str(tour),
            "-t",
            f"{length:.2f}",
            *ENCODE,
            str(media / f"{chapter['name']}.mp4"),
        )
    ffmpeg("-i", str(tour), *ENCODE, str(media / "tour.mp4"))
    for platform in ("ios", "android"):
        try:
            phone(recording, media, platform)
        except Exception as error:  # The site still builds, just without this phone.
            for leftover in media.glob(f"{platform}.*"):
                leftover.unlink()
            print(f"::warning title={platform} clip skipped::{error}", file=sys.stderr)
        try:
            phone_setup(recording, media, platform)
        except Exception as error:  # Likewise for its setup clip.
            (media / f"{platform}-setup.mp4").unlink(missing_ok=True)
            print(f"::warning title={platform} setup clip skipped::{error}", file=sys.stderr)
    web_setup(recording, media)
    for still in recording.glob("*.png"):
        shutil.copy(still, media / still.name)
    # The interactive demo's screens and data (see site/demo.js).
    for name in ("snapshots.json", "demo.json"):
        if (recording / name).exists():
            shutil.copy(recording / name, media / name)
    print("Site media:", ", ".join(sorted(p.name for p in media.iterdir())))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
