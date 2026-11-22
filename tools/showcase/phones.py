"""Film the real iPhone and Android apps against the showcase household.

Runs on the Mac build runner: the iPhone app in the iPhone Simulator (driven by the
ShowcaseTour UI test in apps/ios/Showcase) and the Android app in the Android emulator
(driven here over adb). Both phones follow a route with simulated GPS while recording.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ANDROID_PACKAGE = "com.robiem.narahem"
# Bottom tabs never move, so a remembered position is safe to tap.
TABS = ("Map", "Trips", "Places", "Settings")
# Screenshots for the app stores (tools/showcase/store.py): chapter, and seconds into it to take
# it, once the screen has settled.
STORE_SHOTS = {"map": 10, "member": 5, "trip": 4, "places": 4, "live": 12}


def chapters_from(marks, started):
    """Converts [(name, epoch)] marks into [{name, start, end}] chapters in seconds from started.
    A mark named "end" closes the last chapter.
    """
    chapters = []
    for name, at in marks:
        if chapters:
            chapters[-1]["end"] = round(at - started, 2)
        if name != "end":
            chapters.append({"name": name, "start": round(at - started, 2)})
    return [c for c in chapters if "end" in c]


# ---------------------------------------------------------------------------- iPhone


def film_iphone(server, email, password, route, output, device, xctestrun, seconds_per_point=1.5):
    """Runs the ShowcaseTour UI test while recording the simulator, writing ios-tour.mp4."""
    control = Path(output) / "ios-control"
    shutil.rmtree(control, ignore_errors=True)
    control.mkdir(parents=True)
    video = Path(output) / "ios-tour.mp4"
    simctl = ["xcrun", "simctl"]
    subprocess.run(
        [
            *simctl,
            "status_bar",
            device,
            "override",
            "--time",
            "9:41",
            "--batteryState",
            "charged",
            "--batteryLevel",
            "100",
            "--cellularBars",
            "4",
            "--wifiBars",
            "3",
        ],
        check=False,
    )
    subprocess.run(
        [*simctl, "location", device, "set", f"{route[0][0]},{route[0][1]}"], check=False
    )
    env = dict(
        os.environ,
        TEST_RUNNER_SHOWCASE_SERVER=server.origin,
        TEST_RUNNER_SHOWCASE_EMAIL=email,
        TEST_RUNNER_SHOWCASE_PASSWORD=password,
        TEST_RUNNER_SHOWCASE_CONTROL=str(control),
    )
    mail_mark = len(server.mail)
    test = subprocess.Popen(
        [
            "xcodebuild",
            "test-without-building",
            "-xctestrun",
            str(xctestrun),
            "-destination",
            f"platform=iOS Simulator,id={device}",
            "-resultBundlePath",
            str(Path(output) / "ios-tour.xcresult"),
        ],
        env=env,
        stdout=open(Path(output) / "ios-test.log", "w"),
        stderr=subprocess.STDOUT,
    )
    recording, started, code_sent, driving = None, None, False, False
    shots_due, shots_taken = {}, set()
    (Path(output) / "store").mkdir(exist_ok=True)
    try:
        while test.poll() is None:
            if recording is None and (control / "ready").exists():
                recording = subprocess.Popen(
                    [*simctl, "io", device, "recordVideo", "--codec=h264", "--force", str(video)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                started = time.time()
            if not code_sent and (control / "code-wanted").exists():
                (control / "code").write_text(server.code_for(email, mail_mark))
                code_sent = True
            if (
                not driving
                and (control / "chapters.txt").exists()
                and "map" in (control / "chapters.txt").read_text()
            ):
                waypoints = [f"{lat},{lon}" for lat, lon in route]
                subprocess.run(
                    [
                        *simctl,
                        "location",
                        device,
                        "start",
                        f"--interval={seconds_per_point}",
                        *waypoints,
                    ],
                    check=False,
                )
                driving = True
            if (control / "chapters.txt").exists():
                for line in (control / "chapters.txt").read_text().splitlines():
                    name = line.split()[0]
                    if name in STORE_SHOTS and name not in shots_due and name not in shots_taken:
                        shots_due[name] = time.time() + STORE_SHOTS[name]
            for name, at in list(shots_due.items()):
                if time.time() >= at:
                    del shots_due[name]
                    shots_taken.add(name)
                    subprocess.run(
                        [*simctl, "io", device, "screenshot", "--type=png"]
                        + [str(Path(output) / "store" / f"ios-{name}.png")],
                        check=False,
                        capture_output=True,
                    )
            time.sleep(0.3)
    finally:
        if recording:
            recording.send_signal(signal.SIGINT)
            recording.wait(timeout=30)
        subprocess.run([*simctl, "location", device, "clear"], check=False)
        if test.poll() is None:
            test.terminate()
    marks = (
        [
            (n, float(t))
            for n, t in (
                line.split() for line in (control / "chapters.txt").read_text().splitlines()
            )
        ]
        if (control / "chapters.txt").exists()
        else []
    )
    (Path(output) / "ios-chapters.json").write_text(
        json.dumps(chapters_from(marks, started or 0), indent=2)
    )
    if (control / "captions.txt").exists() and started:
        captions = [
            (float(at), text)
            for at, _, text in (
                line.partition("\t") for line in (control / "captions.txt").read_text().splitlines()
            )
        ]
        write_captions(captions, started, Path(output) / "ios-captions.json")
    if (control / "typed").exists():
        (Path(output) / "ios-typed.log").write_text((control / "typed").read_text())
    if (control / "screen").exists():
        lines = [
            line.strip()
            for line in (control / "screen").read_text().splitlines()
            if any(kind in line for kind in ("Button", "StaticText", "TextField", "Alert", "Sheet"))
        ]
        (Path(output) / "ios-screen.log").write_text("\n".join(lines[:80]) + "\n")
    if test.returncode != 0 or not (control / "done").exists():
        raise RuntimeError(
            f"iPhone tour failed (xcodebuild exit {test.returncode}); see ios-test.log"
        )


# ---------------------------------------------------------------------------- Android


class Android:
    """Drives an Android emulator through adb by finding text on screen, tapping and typing."""

    def __init__(self, serial=None):
        """Targets the given device serial, or the only connected device."""
        self.adb = ["adb"] + (["-s", serial] if serial else [])
        # Where each label was last seen: the dump can fail while the live map animates.
        self.seen = {}

    def run(self, *args, check=True):
        """Runs an adb command."""
        return subprocess.run(
            [*self.adb, *args], check=check, capture_output=True, text=True
        ).stdout

    def shell(self, *args, check=True):
        """Runs a shell command on the device."""
        return self.run("shell", *args, check=check)

    def screen(self):
        """Returns the current UI hierarchy, or None if the dump failed."""
        self.last_dump = self.shell(
            "uiautomator", "dump", "/sdcard/showcase-ui.xml", check=False
        ).strip()
        try:
            root = ElementTree.fromstring(
                self.run("exec-out", "cat", "/sdcard/showcase-ui.xml", check=False)
            )
        except ElementTree.ParseError:
            return None
        self.last_screen = root
        return root

    def dismiss_not_responding(self, root):
        """Waits out a "System UI isn't responding" dialog."""
        if root is None or not any(
            "isn't responding" in node.get("text", "") for node in root.iter("node")
        ):
            return False
        for node in root.iter("node"):
            if node.get("text") == "Wait":
                x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds")))
                self.shell("input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
                time.sleep(2)
                return True
        return False

    def describe(self):
        """Returns the visible text on screen, for error reports."""
        lines = [
            f"uiautomator: {getattr(self, 'last_dump', '')}",
            "focus: "
            + self.shell("dumpsys", "window", check=False)
            .split("mCurrentFocus=")[-1]
            .split("\n")[0],
        ]
        root = getattr(self, "last_screen", None)
        for node in root.iter("node") if root is not None else []:
            text, desc = node.get("text", ""), node.get("content-desc", "")
            if text or desc:
                lines.append(f"{node.get('class', '').split('.')[-1]}: {text or desc}")
        return "\n".join(lines[:60])

    def find(self, label, timeout=30, exact=True):
        """Returns the screen position of the text, waiting up to timeout seconds, or None."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            root = self.screen()
            if self.dismiss_not_responding(root):
                continue
            for node in root.iter("node") if root is not None else []:
                for value in (node.get("text", ""), node.get("content-desc", "")):
                    if value == label or (not exact and label in value):
                        x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds")))
                        self.seen[label] = (x1 + x2) // 2, (y1 + y2) // 2
                        return self.seen[label]
            if root is None and label in TABS and label in self.seen:
                return self.seen[label]
            time.sleep(1)
        return self.seen.get(label) if label in TABS else None

    def tap(self, label, timeout=30, exact=True, required=True):
        """Taps the text on screen."""
        point = self.find(label, timeout, exact)
        if point is None:
            if required:
                Path(os.environ.get("SHOWCASE_ANDROID_SCREEN", "android-screen.log")).write_text(
                    self.describe() + "\n"
                )
                raise RuntimeError(f"Android: '{label}' never appeared on screen")
            return False
        self.shell("input", "tap", str(point[0]), str(point[1]))
        time.sleep(0.8)
        return True

    def type(self, text, settle=0.5):
        """Types text into the focused field."""
        self.shell("input", "text", "'" + text.replace(" ", "%s").replace("'", "") + "'")
        time.sleep(settle)

    def fill(self, label, text, secret=False):
        """Types into a field and retries if keystrokes were dropped."""
        for attempt in range(3):
            self.tap(label)
            # Ctrl+A then Delete: empty the field, whatever an earlier attempt left in it.
            self.shell("input", "keycombination", "KEYCODE_CTRL_LEFT", "KEYCODE_A", check=False)
            self.shell("input", "keyevent", "KEYCODE_DEL")
            time.sleep(0.5)
            size = 3 if attempt == 0 else 1
            for start in range(0, len(text), size):
                self.type(text[start : start + size], settle=0.35)
            if self.holds(text, secret):
                return
        Path(os.environ.get("SHOWCASE_ANDROID_SCREEN", "android-screen.log")).write_text(
            self.describe() + "\n"
        )
        raise RuntimeError(f"Android: could not type into '{label}'")

    def holds(self, text, secret):
        """Returns True if a text field on screen contains the text."""
        root = self.screen()
        for node in root.iter("node") if root is not None else []:
            if node.get("class", "").endswith("EditText"):
                value = node.get("text", "")
                if value == text or (secret and len(value) == len(text)):
                    return True
        return False

    def screenshot(self, path):
        """Saves the screen as a PNG, if the device gives one."""
        png = subprocess.run([*self.adb, "exec-out", "screencap", "-p"], capture_output=True).stdout
        if png.startswith(b"\x89PNG"):
            Path(path).parent.mkdir(exist_ok=True)
            Path(path).write_bytes(png)

    def clean_status_bar(self):
        """Shows a tidy status bar (9:41, full battery and signal, no notifications)."""
        self.shell("settings", "put", "global", "sysui_demo_allowed", "1", check=False)
        demo = ["am", "broadcast", "-a", "com.android.systemui.demo", "-e", "command"]
        for extra in (
            ["enter"],
            ["clock", "-e", "hhmm", "0941"],
            ["battery", "-e", "level", "100", "-e", "plugged", "false"],
            ["network", "-e", "wifi", "show", "-e", "level", "4"],
            ["network", "-e", "mobile", "show", "-e", "level", "4", "-e", "datatype", "none"],
            ["notifications", "-e", "visible", "false"],
        ):
            self.shell(*demo, *extra, check=False)

    def back(self):
        """Presses Back."""
        self.shell("input", "keyevent", "KEYCODE_BACK")

    def hide_keyboard(self):
        """Closes the on-screen keyboard if open."""
        if "mInputShown=true" in self.shell("dumpsys", "input_method", check=False):
            self.back()
            time.sleep(0.5)

    def geo(self, lat, lon):
        """Sets the emulator's GPS position."""
        self.run("emu", "geo", "fix", str(lon), str(lat), check=False)


def film_android(server, email, password, route, output, seconds_per_point=1.5):
    """Signs in to the app on the emulator and records a tour, writing android-tour.mp4."""
    phone = Android(os.environ.get("ANDROID_SERIAL"))
    os.environ["SHOWCASE_ANDROID_SCREEN"] = str(Path(output) / "android-screen.log")
    remote = "/sdcard/showcase-tour.mp4"
    phone.shell("am", "force-stop", ANDROID_PACKAGE, check=False)
    phone.shell("pm", "clear", ANDROID_PACKAGE, check=False)
    for permission in (
        "ACCESS_FINE_LOCATION",
        "ACCESS_COARSE_LOCATION",
        "ACCESS_BACKGROUND_LOCATION",
        "POST_NOTIFICATIONS",
    ):
        phone.shell("pm", "grant", ANDROID_PACKAGE, "android.permission." + permission, check=False)
    for setting in (
        "window_animation_scale",
        "transition_animation_scale",
        "animator_duration_scale",
    ):
        phone.shell("settings", "put", "global", setting, "0", check=False)
    # Let a freshly booted emulator settle, clearing any "isn't responding" dialogs.
    for _ in range(20):
        if not phone.dismiss_not_responding(phone.screen()):
            break
    phone.geo(*route[0])
    phone.shell("rm", "-f", remote, check=False)
    # screenrecord stops by itself after 180 seconds, so filming starts at the map, after
    # sign-in (which the site skips anyway); the tour itself takes about a minute.
    recording, started = None, time.time()
    marks = []
    mark = lambda name: marks.append((name, time.time()))  # noqa: E731
    stop = threading.Event()
    # Setup is filmed on its own (screenrecord stops by itself after 180 seconds), with captions.
    setup_remote = "/sdcard/showcase-setup.mp4"
    phone.shell("rm", "-f", setup_remote, check=False)
    setup = subprocess.Popen(
        [*phone.adb, "shell", "screenrecord", "--bit-rate", "8000000", setup_remote],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    setup_started, captions = time.time(), []
    caption = lambda text: captions.append((time.time(), text))  # noqa: E731
    try:
        time.sleep(1.5)
        phone.shell("am", "start", "-W", "-n", f"{ANDROID_PACKAGE}/.MainActivity")
        mark("signin")
        caption("Open Nära Hem and enter your server's address, your email and password.")
        phone.fill("Server address", server.origin)
        phone.fill("Email or phone number", email)
        phone.hide_keyboard()
        phone.tap("Continue")
        phone.fill("Password", password, secret=True)
        phone.hide_keyboard()
        phone.tap("Sign in")
        # A brand-new tunnel address can take a minute to resolve inside the emulator.
        for _ in range(8):
            if not phone.find("Server address could not be found", timeout=4, exact=False):
                break
            time.sleep(10)
            phone.tap("Sign in")

        phone.tap("Continue", timeout=20, required=False)
        # Head for registration, whichever screen the app is on; a tap can land while
        # the slow emulator is still drawing, so look again after every step.
        for _ in range(12):
            if phone.find("Send verification code", timeout=3):
                break
            for step in ("Register this phone", "Complete setup", "Settings"):
                if phone.find(step, timeout=2):
                    phone.tap(step, timeout=2, required=False)
                    time.sleep(2)
                    break
        caption("Register this phone. Your server emails you a six-digit code.")
        # The setup screen shows while the app is still busy signing in, and its buttons stay
        # disabled until then, so ask again if no code comes.
        code = None
        for _ in range(4):
            time.sleep(2)
            mail_mark = len(server.mail)
            phone.tap("Send verification code")
            try:
                code = server.code_for(email, mail_mark, timeout=25)
                break
            except RuntimeError:
                continue
        if code is None:
            raise RuntimeError(f"No code was emailed to {email}")
        phone.fill("Six-digit code", code)
        phone.hide_keyboard()
        caption("Enter the code from the email.")
        phone.tap("Verify and register this phone")
        time.sleep(3)
        film_sharing_choices(phone, caption)
        caption("")
        time.sleep(1)
        setup = stop_recording(phone, setup, setup_remote, Path(output) / "android-setup.mp4")
        write_captions(captions, setup_started, Path(output) / "android-captions.json")

        phone.clean_status_bar()
        shot = lambda name: phone.screenshot(Path(output) / "store" / f"android-{name}.png")  # noqa: E731
        recording = subprocess.Popen(
            [*phone.adb, "shell", "screenrecord", "--bit-rate", "8000000", remote],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        started = time.time()
        marks.clear()
        time.sleep(1)
        phone.tap("Map")
        phone.tap("Open household map", timeout=4, required=False)
        phone.tap("Continue", timeout=4, required=False)
        threading.Thread(
            target=drive_emulator, args=(phone, route, seconds_per_point, stop), daemon=True
        ).start()
        mark("map")
        time.sleep(10)
        shot("map")
        time.sleep(4)
        if phone.tap("Alex", timeout=5, exact=False, required=False):
            mark("member")
            time.sleep(5)
            shot("member")
            time.sleep(3)
            # Back would leave the app here; the member details live on the map screen.
            phone.tap("Map", required=False)
            time.sleep(2)
        mark("trips")
        phone.tap("Trips")
        time.sleep(3)
        phone.tap("Alex", timeout=5, required=False)
        time.sleep(4)
        shot("trips")
        time.sleep(2)
        mark("places")
        phone.tap("Places")
        time.sleep(4)
        shot("places")
        time.sleep(3)
        mark("live")
        phone.tap("Map")
        time.sleep(12)
        shot("live")
        time.sleep(4)
        mark("end")
    finally:
        stop.set()
        if setup:
            stop_recording(phone, setup, setup_remote, Path(output) / "android-setup.mp4")
        if recording:
            phone.shell("pkill", "-INT", "screenrecord", check=False)
            recording.wait(timeout=30)
        time.sleep(2)
        phone.run("pull", remote, str(Path(output) / "android-tour.mp4"), check=False)
        (Path(output) / "android-chapters.json").write_text(
            json.dumps(chapters_from(marks, started), indent=2)
        )


def film_sharing_choices(phone, caption):
    """Shows who can see this phone: Settings, Permissions, then the sharing list."""
    caption("Choose who can see this phone in Settings, under Permissions.")
    phone.tap("Settings", required=False)
    time.sleep(2)
    phone.tap("Permissions", required=False)
    time.sleep(2)
    if phone.tap("Who can see this phone?", timeout=8, exact=False, required=False):
        caption("Everyone is ticked. New members are added automatically; untick anyone to stop.")
        time.sleep(7)
        phone.tap("Cancel", required=False)
        time.sleep(1.5)


def stop_recording(phone, recording, remote, local):
    """Stops an emulator screen recording and copies it here. Returns None."""
    phone.shell("pkill", "-INT", "screenrecord", check=False)
    try:
        recording.wait(timeout=30)
    except subprocess.TimeoutExpired:
        recording.kill()
    time.sleep(2)
    phone.run("pull", remote, str(local), check=False)
    return None


def write_captions(captions, started, path):
    """Writes [(epoch, text)] captions as [{text, start, end}] seconds into the recording."""
    timed = [
        {"text": text, "start": round(at - started, 2), "end": round(after - started, 2)}
        for (at, text), (after, _next) in zip(captions, captions[1:])
        if text
    ]
    path.write_text(json.dumps(timed, indent=2))


def drive_emulator(phone, route, seconds_per_point, stop):
    """Moves the emulator's GPS along a route until stopped."""
    for lat, lon in route:
        if stop.is_set():
            return
        phone.geo(lat, lon)
        time.sleep(seconds_per_point)
