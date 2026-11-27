"""Build the static showcase site.

    python site/build.py MEDIA_FOLDER OUTPUT_FOLDER

site.json holds the product name and contact, and LINKS names the environment
variables with its addresses; every page uses {{key}} placeholders for them.
MEDIA_FOLDER is what tools/showcase/clips.py produced. OUTPUT_FOLDER is ready to
upload to any static host.
"""

import datetime
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

HERE = Path(__file__).resolve().parent
ICON = HERE.parent / "apps/ios/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png"
STACK = HERE.parent / "deploy/portainer-stack.yaml"
WEB = HERE.parent / "apps/webapp"
BADGES = HERE.parent / "docs/marketing/badges"

# The official store badges (docs/marketing/badges), shown in place of a plain button once an
# app link points at its store: the store's address, the badge and its words.
STORES = {
    "testflight": ("apps.apple.com", "app-store.svg", "Download on the App Store"),
    "android": ("play.google.com", "google-play.png", "Get it on Google Play"),
}

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
# With a Google Maps browser key (restricted to the site's domain), the demo map uses Google Maps
# in the web app's dark style; without one, OpenStreetMap.
GOOGLE_KEY = "SITE_GOOGLE_MAPS_API_KEY"
MAP_STYLE = WEB / "frontend/src/mapstyle.mjs"


def social_tags(text, page):
    """Adds the link-preview tags chat apps and social sites read (Open Graph, and X's card),
    from the page's own title and description, with the shared 1200x630 preview picture.
    Redirect pages are left alone.
    """
    if 'http-equiv="refresh"' in text:
        return text
    title = re.search(r"<title>(.*?)</title>", text, re.S).group(1).strip()
    found = re.search(r'name="description"\s+content="([^"]*)"', text)
    description = " ".join(found.group(1).split()) if found else ""
    tags = {
        "og:type": "website",
        "og:site_name": "{{name}}",
        "og:title": title,
        "og:description": description,
        "og:url": "https://{{domain}}/" + ("" if page == "index.html" else page),
        "og:image": "https://{{domain}}/preview.png",
        "og:image:width": "1200",
        "og:image:height": "630",
        "og:image:alt": "{{name}}: a self-hosted family tracking ecosystem",
    }
    block = "".join(f'    <meta property="{k}" content="{v}" />\n' for k, v in tags.items() if v)
    block += '    <meta name="twitter:card" content="summary_large_image" />\n'
    return text.replace("  </head>", block + "  </head>", 1)


def versioned(output):
    """Adds each local script and style's content hash to its address in every page, so no cache,
    Cloudflare's or a browser's, ever serves an old copy after an update.
    """
    for page in output.glob("*.html"):
        text = page.read_text()

        def stamp(match):
            asset = output / match.group(2)
            if not asset.is_file():
                return match.group(0)
            digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:10]
            return f'{match.group(1)}="{match.group(2)}?v={digest}"'

        page.write_text(re.sub(r'(src|href)="([\w./-]+\.(?:js|css))"', stamp, text))


def google_styles():
    """Returns the web app's dark Google Maps style, read from its source with Node."""
    script = (
        f"import({json.dumps(MAP_STYLE.as_uri())})"
        ".then((m) => console.log(JSON.stringify(m.GOOGLE_DARK_STYLES)))"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def button(link, label):
    """Returns a button-styled link, or an empty string if there is no link."""
    if link:
        return f'<a class="button" href="{html.escape(link)}">{label}</a>'
    return f'<span class="button disabled">{label}: opening soon</span>'


def in_store(link, platform):
    """Returns True if the app link is the app's App Store or Google Play page."""
    return urlsplit(link).hostname == STORES[platform][0]


def store_badge(link, platform):
    """Returns the store's official badge linking to the app's page, unchanged as each store's
    rules ask, or an empty string if the link isn't a store page.
    """
    if not in_store(link, platform):
        return ""
    _, image, words = STORES[platform]
    return (
        f'<a class="store-badge" href="{html.escape(link)}">'
        f'<img src="badges/{image}" alt="{words}" height="40" /></a>'
    )


def install_apps(config):
    """Returns the setup page's app links: each store's badge once the app is in it, otherwise
    a plain link to TestFlight or the Android download.
    """
    plain = {"testflight": "iPhone (TestFlight)", "android": "Android"}
    links = [
        store_badge(config[platform], platform)
        or f'<a href="{html.escape(config[platform])}">{label}</a>'
        for platform, label in plain.items()
        if config[platform]
    ]
    return f'<span class="store-badges">{"".join(links)}</span>' if links else ""


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
    values["install_apps"] = install_apps(config)
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
        if values["domain"]:  # previews need the site's full address
            text = social_tags(text, page)
        text = re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], text)
        (output / page).write_text(text)
    shutil.copy(HERE / "style.css", output)
    shutil.copy(HERE / "preview.png", output)
    shutil.copytree(BADGES, output / "badges")
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
        "store": {name: in_store(config[name], name) for name in STORES},
        **(
            {"google_maps_key": key, "google_styles": google_styles()}
            if (key := os.environ.get(GOOGLE_KEY, "").strip())
            else {}
        ),
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
    versioned(output)
    print("Site built in", output)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
