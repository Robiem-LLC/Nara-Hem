"""Build the static showcase site.

    python site/build.py MEDIA_FOLDER OUTPUT_FOLDER

site.json holds the product name and contact, and LINKS names the environment
variables with its addresses; every page uses {{key}} placeholders for them.
MEDIA_FOLDER is what tools/showcase/clips.py produced. OUTPUT_FOLDER is ready to
upload to any static host.
"""

import datetime
import html
import json
import os
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ICON = HERE.parent / "apps/ios/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png"
STACK = HERE.parent / "deploy/portainer-stack.yaml"
WEB = HERE.parent / "apps/webapp"

DEMO_FILES = {
    "app.css": WEB / "frontend/public/style.css",
    "app-icon.png": WEB / "frontend/public/app-icon.png",
    "nara-hem-wordmark.png": WEB / "frontend/public/nara-hem-wordmark.png",
    "leaflet.css": WEB / "frontend/node_modules/leaflet/dist/leaflet.css",
    "leaflet.js": WEB / "frontend/node_modules/leaflet/dist/leaflet.js",
    "demo.js": HERE / "demo/demo.js",
    "demo.css": HERE / "demo/demo.css",
}

SETUP_VIDEOS = {
    "setup-server": "Creating the household",
    "setup-email": "Connecting email",
    "setup-invite": "Inviting the family",
}

PHONE_SETUP = (("ios-setup", "iPhone"), ("android-setup", "Android"))


# Addresses come from the build environment, not the repository: the site's own domain, the app
# downloads and the source code.
LINKS = {
    "domain": "SITE_DOMAIN",
    "testflight": "NARAHEM_IOS_APP_URL",
    "android": "NARAHEM_ANDROID_APP_URL",
    "github": "SITE_GITHUB",
}


def button(link, label):
    """Returns a button-styled link, or an empty string if there is no link."""
    if link:
        return f'<a class="button" href="{html.escape(link)}">{label}</a>'
    return f'<span class="button disabled">{label}: opening soon</span>'


def phones_section(media, product):
    """Returns the phone video section if the videos exist, otherwise an empty string."""
    phones = [
        (name, label)
        for name, label in (("ios", "iPhone"), ("android", "Android"))
        if (media / f"{name}.mp4").exists()
    ]
    if not phones:
        return ""
    frames = "".join(
        f'<figure class="phone"><video src="media/{name}.mp4" poster="media/{name}.png" muted loop '
        f"playsinline "
        f'preload="none" data-autoplay aria-label="{html.escape(product)} on '
        f'{label}"></video><figcaption>{label}</figcaption></figure>'
        for name, label in phones
    )
    return (
        '<section id="phones" class="phones"><h2>On your phone</h2>'
        '<p class="lead narrow">The same household in the iPhone and Android apps: live locations, '
        "the household list, "
        "trips and places. Each phone here is driving its own route with simulated GPS.</p>"
        f'<div class="phone-row">{frames}</div></section>'
    )


def setup_video(media, name, label):
    """Returns a captioned setup video for the setup page, or nothing if it wasn't filmed."""
    if not (media / f"{name}.mp4").exists():
        return ""
    return (
        f'<figure class="setup-video"><video src="media/{name}.mp4" controls muted playsinline '
        f'preload="metadata" aria-label="{html.escape(label)}"></video>'
        f"<figcaption>{html.escape(label)}</figcaption></figure>"
    )


def phone_setup_videos(media):
    """Returns the iPhone and Android setup videos side by side, if they were filmed."""
    frames = "".join(
        f'<figure class="phone"><video src="media/{name}.mp4" controls muted playsinline '
        f'preload="metadata" aria-label="Setting up {label}"></video>'
        f"<figcaption>{label}</figcaption></figure>"
        for name, label in PHONE_SETUP
        if (media / f"{name}.mp4").exists()
    )
    return f'<div class="phone-row">{frames}</div>' if frames else ""


def main(media, output):
    """Builds the static download site from site.json and the media directory."""
    media, output = Path(media), Path(output)
    config = json.loads((HERE / "site.json").read_text())
    for key, name in LINKS.items():
        config[key] = os.environ.get(name, "").strip()
    values = {key: html.escape(value) for key, value in config.items()}
    # The public server image, e.g. ghcr.io/<owner>/narahem; CI passes it in.
    values["image"] = html.escape(os.environ.get("SITE_IMAGE", "ghcr.io/<owner>/narahem"))
    values["testflight_button"] = button(config["testflight"], "Join on TestFlight")
    values["android_button"] = button(config["android"], "Download for Android")
    values["updated"] = datetime.date.today().strftime("%B %-d, %Y")
    values["stack_yaml"] = html.escape(STACK.read_text())
    values["phones_section"] = phones_section(media, config["name"])
    for name, label in SETUP_VIDEOS.items():
        values["video_" + name.replace("-", "_")] = setup_video(media, name, label)
    values["video_setup_phones"] = phone_setup_videos(media)

    if output.exists():
        shutil.rmtree(output)
    (output / "media").mkdir(parents=True)
    for page in ("index.html", "privacy.html", "terms.html", "setup.html", "demo.html"):
        text = (HERE / page).read_text()
        text = re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], text)
        (output / page).write_text(text)
    shutil.copy(HERE / "style.css", output)
    shutil.copy(STACK, output / "narahem-stack.yaml")
    icon = Image.open(ICON).convert("RGB")
    for size in (64, 256):
        icon.resize((size, size), Image.LANCZOS).save(output / f"icon-{size}.png", optimize=True)
    shutil.copy(media / "live.mp4", output / "media")
    for name in ("live", "map"):
        Image.open(media / f"{name}.png").convert("RGB").save(
            output / "media" / f"{name}.png", optimize=True
        )
    (output / "demo").mkdir()
    for name, source in DEMO_FILES.items():
        shutil.copy(source, output / "demo" / name)
    demo = {
        "snapshots": json.loads((media / "snapshots.json").read_text()),
        "data": json.loads((media / "demo.json").read_text()),
    }
    # What the page needs from site.json, and which phone videos this build has.
    demo["site"] = {
        **{k: config.get(k, "") for k in ("name", "github", "testflight", "android", "contact")},
        "alexa_name": config.get("alexa_name") or config["name"],
        "install": "setup.html",
        "media": {name: (media / f"{name}.mp4").exists() for name in ("ios", "android")},
    }
    (output / "demo" / "data.js").write_text("window.NARAHEM_DEMO = " + json.dumps(demo) + ";\n")
    for name in ("ios", "android"):
        if (media / f"{name}.mp4").exists():
            shutil.copy(media / f"{name}.mp4", output / "media")
            Image.open(media / f"{name}.png").convert("RGB").save(
                output / "media" / f"{name}.png", optimize=True
            )
    for name in [*SETUP_VIDEOS, *(name for name, _ in PHONE_SETUP)]:
        if (media / f"{name}.mp4").exists():
            shutil.copy(media / f"{name}.mp4", output / "media")
    print("Site built in", output)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
