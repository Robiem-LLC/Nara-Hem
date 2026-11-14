"""Record the Nära Hem showcase: a fake family on a real server, filmed in real apps.

    python tools/showcase/run.py web OUTPUT_FOLDER       the web app, in a real browser
    python tools/showcase/run.py phones OUTPUT_FOLDER    the iPhone and Android apps (Mac only)
    python tools/showcase/run.py setup OUTPUT_FOLDER     the web setup steps on a new server

Needs the backend's Python requirements plus Pillow, and the web frontend's
node_modules (for Playwright and the built browser bundle). Set
NARAHEM_SHOWCASE_MAPS_KEY to film Google Maps instead of OpenStreetMap.

`phones` also needs cloudflared (the apps only connect over HTTPS, so the server is
reached through a temporary Cloudflare quick tunnel), a booted iPhone simulator and
built ShowcaseTour UI test (SHOWCASE_SIMULATOR, SHOWCASE_XCTESTRUN), and a booted
Android emulator with the app installed (adb on PATH).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
from household import ShowcaseServer, avatar
from phone import FakePhone
from scenario import (
    APP_MEMBERS,
    HISTORY,
    HOUSEHOLD,
    LIVE,
    MEMBERS,
    OWNER,
    PARKED,
    PASSWORD,
    PHONE_ROUTES,
    PLACES,
    ROUTES,
    now_ms,
    road_path,
)

HERE = Path(__file__).resolve().parent


def recorder(stage, server, profile, output, **extra):
    """Runs the browser recorder for one stage."""
    env = dict(
        os.environ,
        SHOWCASE_ORIGIN=server.origin,
        SHOWCASE_PROFILE=str(profile),
        SHOWCASE_OUTPUT=str(output),
        SHOWCASE_EMAIL=OWNER[0],
        SHOWCASE_PASSWORD=PASSWORD,
        **{key: str(value) for key, value in extra.items()},
    )
    subprocess.run(["node", str(HERE / "record.cjs"), stage], env=env, check=True)


def drive(phone, path, seconds, stop):
    """Moves a fake phone along a path over the given time, reporting like a phone in a car."""
    step = seconds / (len(path) - 1)
    for index, (lat, lon) in enumerate(path):
        if stop.is_set():
            return
        speed = 0 if index == 0 else 12.0
        try:
            phone.location(lat, lon, speed=speed, battery=78 - index // 20)
        except RuntimeError as error:
            # The server allows 120 records per device per minute; a real phone retries later.
            print(error, file=sys.stderr)
        time.sleep(step)


def household(folder, output, public_url=None):
    """Starts the server and creates the showcase family, places and trips."""
    server = ShowcaseServer(
        folder / "server",
        int(os.environ.get("SHOWCASE_PORT", "18900")),
        os.environ.get("NARAHEM_SHOWCASE_MAPS_KEY", ""),
        public_url,
    )
    device_token = server.setup(HOUSEHOLD, OWNER[0], PASSWORD)
    accounts = {name: server.add_member(email, name, PASSWORD) for name, email, *_ in MEMBERS}
    app_accounts = [server.add_member(email, name, PASSWORD) for name, email in APP_MEMBERS]

    profile = folder / "browser"
    recorder("bootstrap", server, profile, output, SHOWCASE_DEVICE_TOKEN=device_token)
    for _ in range(100):
        if server.enrollment_ready():
            break
        time.sleep(0.2)
    else:
        raise RuntimeError("The owner browser did not activate phone enrollment")

    owner = server.owner_id()
    phones = {}
    for name, email, _initials, _color, platform in MEMBERS:
        phones[name] = FakePhone(server, accounts[name], email, name, PASSWORD, platform)
    for name, phone in phones.items():
        phone.share_with(
            [owner] + app_accounts + [a for other, a in accounts.items() if other != name]
        )
        initials, color = next((m[2], m[3]) for m in MEMBERS if m[0] == name)
        phone.profile(avatar(initials, color))
    for place, (lat, lon) in PLACES.items():
        phones["Alex"].place(place, lat, lon)

    demo = {
        "recorded_at": now_ms(),
        "places": [{"name": n, "lat": p[0], "lon": p[1], "radius": 120} for n, p in PLACES.items()],
        "trips": [],
        "live": [],
        "parked": PARKED,
    }
    for name, origin, destination, hours_ago, minutes in HISTORY:
        started = now_ms() - int(hours_ago * 3_600_000)
        path = road_path(PLACES[origin], PLACES[destination], 30)
        phones[name].trip(path, started, started + minutes * 60_000, origin_name=origin)
        demo["trips"].append(
            {
                "member": name,
                "origin": origin,
                "destination": destination,
                "path": [
                    [round(a, 5), round(b, 5)]
                    for a, b in road_path(PLACES[origin], PLACES[destination], 120)
                ],
            }
        )
    for name, place in PARKED.items():
        phones[name].location(*PLACES[place], battery=64)
    for name, origin, destination, seconds in LIVE:
        phones[name].location(*PLACES[origin], battery=81)
        demo["live"].append(
            {
                "member": name,
                "origin": origin,
                "destination": destination,
                "seconds": seconds,
                "path": [
                    [round(a, 5), round(b, 5)]
                    for a, b in road_path(PLACES[origin], PLACES[destination], 120)
                ],
            }
        )
    return server, phones, profile, demo


def start_drives(phones, seconds):
    """Starts the fake phones driving in background threads."""
    stop = threading.Event()
    for name, a, b, _ in LIVE:
        threading.Thread(
            target=drive,
            args=(phones[name], road_path(PLACES[a], PLACES[b], 40), seconds, stop),
            daemon=True,
        ).start()
    return stop


def summarize(output):
    """Prints a summary of the generated files."""
    tiles = (
        (output / "tiles.txt").read_text().strip()
        if (output / "tiles.txt").exists()
        else "not filmed"
    )
    summary = (
        f"routes on streets {ROUTES['street']}, straight {ROUTES['straight']}; map tiles {tiles}"
    )
    (output / "summary.txt").write_text(summary + "\n")
    print(
        "Showcase videos:",
        ", ".join(sorted(p.name for p in output.iterdir() if p.suffix in (".webm", ".mp4"))),
        "|",
        summary,
    )


def web(output):
    """Records the web app showcase with a temporary server."""
    with tempfile.TemporaryDirectory(prefix="narahem-showcase-") as folder:
        server, phones, profile, demo = household(Path(folder), output)
        (output / "demo.json").write_text(json.dumps(demo))
        stop = start_drives(phones, 45)
        try:
            recorder("tour", server, profile, output)
        finally:
            stop.set()
            server.stop()
    summarize(output)


def copy_inbox(server, inbox, stop):
    """Keeps a JSON copy of the server's captured email for the recorder's inbox panel."""
    while not stop.is_set():
        mail = [{"to": m[1], "subject": m[2], "body": m[3]} for m in server.mail]
        partial = inbox.with_suffix(".part")
        partial.write_text(json.dumps(mail))
        partial.replace(inbox)
        time.sleep(0.25)


def family_joins(server, signals, stop):
    """Once the filmed invitation is accepted, the family's phones join and start sharing."""
    invited = MEMBERS[0]
    phones = {}
    while not (signals / "invited").exists() or not server.enrollment_ready():
        if stop.is_set():
            return
        time.sleep(0.25)
    owner = server.owner_id()
    accounts = {invited[0]: server.account_id(invited[1])}
    for name, email, *_ in MEMBERS[1:]:
        accounts[name] = server.add_member(email, name, PASSWORD)
    for name, email, _initials, _color, platform in MEMBERS:
        phones[name] = FakePhone(server, accounts[name], email, name, PASSWORD, platform)
    for name, phone in phones.items():
        phone.share_with([owner] + [a for other, a in accounts.items() if other != name])
        initials, color = next((m[2], m[3]) for m in MEMBERS if m[0] == name)
        phone.profile(avatar(initials, color))
    for place, (lat, lon) in PLACES.items():
        phones[invited[0]].place(place, lat, lon)
    for name, place in PARKED.items():
        phones[name].location(*PLACES[place], battery=64)
    for name, origin, _destination, _seconds in LIVE:
        phones[name].location(*PLACES[origin], battery=81)
    for name, a, b, _ in LIVE:
        threading.Thread(
            target=drive,
            args=(phones[name], road_path(PLACES[a], PLACES[b], 40), 60, stop),
            daemon=True,
        ).start()
    (signals / "family-ready").write_text("")


def setup_series(output):
    """Records the web setup steps on a brand-new server, from setup token to invited family."""
    with tempfile.TemporaryDirectory(prefix="narahem-setup-") as folder:
        folder = Path(folder)
        server = ShowcaseServer(
            folder / "server",
            int(os.environ.get("SHOWCASE_PORT", "18900")),
            os.environ.get("NARAHEM_SHOWCASE_MAPS_KEY", ""),
            mail_worker=True,
        )
        signals, inbox = folder / "signals", folder / "inbox.json"
        signals.mkdir()
        stop = threading.Event()
        threading.Thread(target=copy_inbox, args=(server, inbox, stop), daemon=True).start()
        threading.Thread(target=family_joins, args=(server, signals, stop), daemon=True).start()
        try:
            env = dict(
                os.environ,
                SHOWCASE_ORIGIN=server.origin,
                SHOWCASE_PROFILE=str(folder / "browser"),
                SHOWCASE_OUTPUT=str(output),
                SHOWCASE_EMAIL=OWNER[0],
                SHOWCASE_PASSWORD=PASSWORD,
                SHOWCASE_HOUSEHOLD=HOUSEHOLD,
                SHOWCASE_SETUP_TOKEN=(folder / "server/bootstrap-token").read_text().strip(),
                SHOWCASE_INBOX=str(inbox),
                SHOWCASE_SIGNALS=str(signals),
                SHOWCASE_INVITE_NAME=MEMBERS[0][0],
                SHOWCASE_INVITE_EMAIL=MEMBERS[0][1],
            )
            subprocess.run(["node", str(HERE / "setup.cjs")], env=env, check=True)
        finally:
            stop.set()
            server.stop()
    print("Setup video:", ", ".join(sorted(p.name for p in output.glob("setup*"))))


def quick_tunnel(port):
    """Returns a temporary public HTTPS URL for the local server using a Cloudflare quick tunnel."""
    log = open(Path(tempfile.gettempdir()) / "narahem-showcase-tunnel.log", "w+")
    tunnel = subprocess.Popen(
        ["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    for _ in range(120):
        log.seek(0)
        # Skip api.trycloudflare.com, which cloudflared names while it asks for a tunnel.
        found = re.search(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com", log.read())
        if found:
            return tunnel, found.group(0)
        time.sleep(0.5)
    tunnel.terminate()
    raise RuntimeError("cloudflared did not report a quick tunnel address")


def phones_mode(output):
    """Records the real Android and iPhone apps."""
    from phones import film_android, film_iphone

    port = int(os.environ.get("SHOWCASE_PORT", "18900"))
    tunnel, public_url = quick_tunnel(port)
    try:
        with tempfile.TemporaryDirectory(prefix="narahem-showcase-") as folder:
            server, phones, _, _ = household(Path(folder), output, public_url)
            # A new quick tunnel can take a moment to resolve publicly.
            for _ in range(60):
                try:
                    if httpx.get(public_url + "/healthz", timeout=5).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(2)
            failures = []
            for platform, film, account in (
                ("ios", film_iphone, OWNER[0]),
                ("android", film_android, APP_MEMBERS[0][1]),
            ):
                if platform not in os.environ.get("SHOWCASE_PHONES", "ios,android").split(","):
                    continue
                route = road_path(*(PLACES[p] for p in PHONE_ROUTES[platform]), 50)
                stop = start_drives(phones, 75)
                try:
                    if platform == "ios":
                        film(
                            server,
                            account,
                            PASSWORD,
                            route,
                            output,
                            os.environ["SHOWCASE_SIMULATOR"],
                            os.environ["SHOWCASE_XCTESTRUN"],
                        )
                    else:
                        film(server, account, PASSWORD, route, output)
                except Exception as error:  # Film the other phone anyway; report both at the end.
                    failures.append(f"{platform}: {error}")
                    print(f"{platform} filming failed: {error}", file=sys.stderr)
                finally:
                    stop.set()
            server.stop()
    finally:
        tunnel.terminate()
    summarize(output)
    if failures:
        raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    modes = {"web": web, "phones": phones_mode, "setup": setup_series}
    if len(sys.argv) != 3 or sys.argv[1] not in modes:
        sys.exit(__doc__)
    destination = Path(sys.argv[2]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    modes[sys.argv[1]](destination)
