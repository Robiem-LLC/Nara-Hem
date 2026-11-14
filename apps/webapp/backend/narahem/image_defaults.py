"""Settings built into official images by CI (ci/relay_defaults.py), so a server works without
setting them: the push and Alexa relay addresses, the store Alexa skill's ID and the app download
links. Other builds have none. Environment variables always win, and tokens are never built in.
"""

import json
import os
from pathlib import Path

NAMES = (
    "NARAHEM_PUSH_RELAY_URL",
    "NARAHEM_FCM_RELAY_URL",
    "NARAHEM_ALEXA_RELAY_URL",
    "NARAHEM_ALEXA_STORE_SKILL_ID",
    "NARAHEM_IOS_APP_URL",
    "NARAHEM_ANDROID_APP_URL",
)


def built_in():
    """Returns the settings built into this image ({} if there are none)."""
    default = Path(__file__).with_name("relay-defaults.json")
    path = Path(os.environ.get("NARAHEM_RELAY_DEFAULTS_FILE", default))
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {k: v.strip() for k, v in value.items() if k in NAMES and isinstance(v, str)}


def setting(name):
    """Returns a setting from the environment, or the one built into the image ("" if neither)."""
    return os.environ.get(name, "").strip() or built_in().get(name, "")
