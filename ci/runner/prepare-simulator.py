#!/usr/bin/env python3
"""Run once as narahemci after approval; create a compatible simulator if absent."""

import json
import os
import subprocess

env = dict(os.environ, DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer")
state = json.loads(subprocess.check_output(["/usr/bin/xcrun", "simctl", "list", "-j"], env=env))
phones = [
    d
    for group in state["devices"].values()
    for d in group
    if d.get("isAvailable") and d["name"].startswith("iPhone")
]
if phones:
    print("Existing simulator:", phones[0]["name"], phones[0]["udid"])
else:
    runtimes = [r for r in state["runtimes"] if r.get("isAvailable") and ".iOS-" in r["identifier"]]
    if not runtimes:
        raise SystemExit("Install an iOS runtime in Xcode Settings > Components, then retry.")
    runtime = max(runtimes, key=lambda r: tuple(int(n) for n in r["version"].split(".")))
    version = [int(n) for n in runtime["version"].split(".")]
    encoded = sum(n << shift for n, shift in zip((version + [0, 0])[:3], [16, 8, 0]))
    types = [
        t
        for t in state["devicetypes"]
        if t["name"].startswith("iPhone")
        and t.get("minRuntimeVersion", 0) <= encoded <= t.get("maxRuntimeVersion", 0xFFFFFFFF)
    ]
    if not types:
        raise SystemExit("No compatible iPhone device type for installed runtime")
    device = max(types, key=lambda t: t.get("minRuntimeVersion", 0))
    subprocess.run(
        [
            "/usr/bin/xcrun",
            "simctl",
            "create",
            "iPhone NaraHem CI",
            device["identifier"],
            runtime["identifier"],
        ],
        env=env,
        check=True,
    )
