"""Make the App Store and Google Play images, laid out like docs/marketing.

    python tools/showcase/store.py screenshots PHONES_FOLDER OUTPUT_FOLDER
    python tools/showcase/store.py art OUTPUT_FOLDER

`screenshots` reads the raw screenshots phones.py took while filming (PHONES_FOLDER/store)
and puts each on a branded background under a headline, in ios/screenshots at 1206 x 2622
(6.3" iPhone, the size App Store Connect requires, scaled down for smaller iPhones) and
android/screenshots at 1080 x 1920 (Google Play rejects images more than twice as tall as
they are wide, as raw Pixel screenshots are). `art` draws the App Store header (ios/app-store-header.png,
3840 x 1646) and the Google Play feature graphic (android/feature-graphic.png, 1024 x 500)
from the app icon and wordmark. Needs Pillow.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
ICON = ROOT / "apps/ios/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png"
WORDMARK = ROOT / "docs/brand/nara-hem-wordmark.png"

# The showcase site's colours (site/style.css).
BACKGROUND = (11, 16, 25)
PANEL = (20, 29, 43)
LINE = (38, 51, 73)
TEXT = (231, 237, 246)
MUTED = (168, 181, 200)
ACCENT = (165, 240, 188)

BOLD = (
    "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
    "/Library/Fonts/Inter-Bold.otf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)
REGULAR = (
    "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
    "/Library/Fonts/Inter-Regular.otf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

# Screenshot name (taken by phones.py), headline and the line under it, in store order.
SHOTS = (
    ("map", "Your whole family on one map", "Live locations, on a server your household runs"),
    ("member", "Tap anyone to see where they are", "Only the people they choose can see them"),
    ("trip", "Every drive, start to finish", "Distance, top speed and the route"),
    ("trips", "Every drive, start to finish", "Distance, top speed and the route"),
    ("places", "Know when they get home", "Alerts when someone arrives or leaves a place"),
)

# Each platform's folder and the size of its store screenshots.
SIZES = {"ios": (1206, 2622), "android": (1080, 1920)}


def font(candidates, size):
    """Returns the first font that exists, at the given size."""
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def backdrop(size):
    """Returns the dark background with a faint grid, like the site's preview image."""
    width, height = size
    image = Image.new("RGB", size, BACKGROUND)
    glow = Image.new("RGB", size, PANEL)
    # A soft vertical fade from the panel colour at the top to the background below.
    mask = Image.linear_gradient("L").resize(size).point(lambda v: 255 - v)
    image.paste(glow, (0, 0), mask)
    draw = ImageDraw.Draw(image)
    step = max(width, height) // 24
    grid = tuple(int(a + (b - a) * 0.35) for a, b in zip(BACKGROUND, LINE))
    for x in range(0, width, step):
        draw.line([(x, 0), (x, height)], fill=grid, width=1)
    for y in range(0, height, step):
        draw.line([(0, y), (width, y)], fill=grid, width=1)
    return image


def wrap(draw, text, face, width):
    """Splits text into lines that fit the width."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and draw.textlength(trial, font=face) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line] if line else lines


def rounded(image, radius):
    """Returns the image with rounded corners as transparency."""
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), image.size], radius, fill=255)
    result = image.convert("RGBA")
    result.putalpha(mask)
    return result


def store_screenshot(raw, headline, subline, size):
    """Puts a raw phone screenshot under a headline on a canvas of the given size."""
    width, height = size
    image = backdrop(size)
    draw = ImageDraw.Draw(image)
    margin = round(width * 0.08)
    title = font(BOLD, round(width * 0.07))
    small = font(REGULAR, round(width * 0.037))
    y = round(height * 0.05)
    for line in wrap(draw, headline, title, width - 2 * margin):
        draw.text((width / 2, y), line, font=title, fill=TEXT, anchor="mt")
        y += round(title.size * 1.18)
    y += round(small.size * 0.5)
    for line in wrap(draw, subline, small, width - 2 * margin):
        draw.text((width / 2, y), line, font=small, fill=MUTED, anchor="mt")
        y += round(small.size * 1.3)
    y += round(height * 0.035)
    # The whole phone screen, tab bar included, as large as the space below the text allows.
    shot = Image.open(raw).convert("RGB")
    scale = min(width * 0.84 / shot.width, (height - y - round(height * 0.04)) / shot.height)
    shot = shot.resize((round(shot.width * scale), round(shot.height * scale)), Image.LANCZOS)
    border = max(4, width // 220)
    frame = Image.new("RGB", (shot.width + 2 * border, shot.height + 2 * border), LINE)
    frame.paste(shot, (border, border))
    frame = rounded(frame, round(width * 0.06))
    image.paste(frame, ((width - frame.width) // 2, y), frame)
    return image


def screenshots(phones, output):
    """Writes the store screenshots for every raw screenshot phones.py took."""
    raw = Path(phones) / "store"
    written = []
    for platform, size in SIZES.items():
        folder = Path(output) / platform / "screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        number = 0
        for name, headline, subline in SHOTS:
            source = raw / f"{platform}-{name}.png"
            if not source.exists():
                continue
            number += 1
            target = folder / f"{number:02d}-{name}.png"
            store_screenshot(source, headline, subline, size).save(target, optimize=True)
            written.append(f"{platform}/screenshots/{target.name}")
    print("Store screenshots:", ", ".join(written) or "none (no raw screenshots found)")
    return written


def banner(size, tagline, footer):
    """Draws the app icon, wordmark and tagline centred on the dark background."""
    width, height = size
    image = backdrop(size)
    draw = ImageDraw.Draw(image)
    scale = min(width / 3840, height / 1646)
    # Two places in the accent colour, as on the site's preview, in corners the text avoids.
    for cx, cy in ((0.07, 0.84), (0.93, 0.18)):
        x, y = cx * width, cy * height
        r, dot = 150 * scale, 34 * scale
        draw.ellipse(
            [x - r, y - r, x + r, y + r], outline=(52, 92, 72), width=max(2, round(5 * scale))
        )
        draw.ellipse([x - dot, y - dot, x + dot, y + dot], fill=ACCENT)
    icon_size = round(560 * scale)
    icon = rounded(
        Image.open(ICON).convert("RGB").resize((icon_size,) * 2, Image.LANCZOS), 0.22 * icon_size
    )
    wordmark = Image.open(WORDMARK).convert("RGBA")
    mark_height = round(icon_size * 0.5)
    wordmark = wordmark.resize(
        (round(wordmark.width * mark_height / wordmark.height), mark_height), Image.LANCZOS
    )
    gap = round(icon_size * 0.22)
    title = font(BOLD, round(132 * scale))
    small = font(REGULAR, round(96 * scale))
    row_width = icon_size + gap + wordmark.width
    block = icon_size + round(130 * scale) + title.size + round(60 * scale) + small.size
    top = (height - block) // 2
    left = (width - row_width) // 2
    image.paste(icon, (left, top), icon)
    image.paste(wordmark, (left + icon_size + gap, top + (icon_size - mark_height) // 2), wordmark)
    y = top + icon_size + round(130 * scale)
    draw.text((width / 2, y), tagline, font=title, fill=TEXT, anchor="mt")
    y += title.size + round(60 * scale)
    draw.text((width / 2, y), footer, font=small, fill=MUTED, anchor="mt")
    return image


def art(output):
    """Writes the App Store header and the Google Play feature graphic."""
    output = Path(output)
    tagline = "Family location sharing on your own server"
    for platform in SIZES:
        (output / platform).mkdir(parents=True, exist_ok=True)
    # Each store rejects metadata that names the other's platform (App Store guideline 2.3.10).
    banner((3840, 1646), tagline, "iPhone · Web · Open source").save(
        output / "ios/app-store-header.png", optimize=True
    )
    banner((1024, 500), tagline, "Android · Web · Open source").save(
        output / "android/feature-graphic.png", optimize=True
    )
    print("Store art: ios/app-store-header.png, android/feature-graphic.png")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "screenshots":
        screenshots(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 3 and sys.argv[1] == "art":
        art(sys.argv[2])
    else:
        sys.exit(__doc__)
