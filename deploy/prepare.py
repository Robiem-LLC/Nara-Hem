"""Generate local Compose secrets once. Never overwrite an existing .env."""

import argparse
import ipaddress
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument(
    "--url", required=True, help="Exact browser origin, e.g. https://narahem.example.com"
)
parser.add_argument("--bind", default="127.0.0.1", help="Host bind IP for port 8186")
parser.add_argument(
    "--image",
    required=True,
    help="Published server image without a tag, e.g. ghcr.io/OWNER/nara-hem",
)
parser.add_argument(
    "--allow-http", action="store_true", help="Explicit private development use only"
)
args = parser.parse_args()
url = urlsplit(args.url.rstrip("/"))
if (
    url.scheme not in ("https", "http")
    or not url.hostname
    or url.path
    or url.query
    or url.fragment
    or url.username
    or url.password
):
    parser.error("Use a bare HTTPS origin with no path or credentials")
if url.scheme == "http" and not args.allow_http:
    parser.error("HTTP needs --allow-http for private development")

try:
    ipaddress.IPv4Address(args.bind)
except ValueError:
    parser.error("--bind must be an IPv4 address")
if any(char in args.url for char in ("\n", "\r", "$", "#", "'", '"')):
    parser.error("Unsupported URL characters")
if not re.fullmatch(r"[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)+", args.image):
    parser.error("--image must be a lowercase image name without a tag")
content = (
    f"NARAHEM_IMAGE={args.image}\n"
    f"NARAHEM_PUBLIC_URL={args.url.rstrip('/')}\n"
    f"NARAHEM_BIND_ADDRESS={args.bind}\n"
    f"NARAHEM_ALLOW_HTTP={int(args.allow_http)}\n"
    f"NARAHEM_DB_PASSWORD={secrets.token_hex(32)}\n"
)
try:
    fd = os.open(Path(".env"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    parser.exit(1, ".env already exists; no settings changed.\n")
with os.fdopen(fd, "w") as output:
    output.write(content)
print("Created private .env. Next: docker compose pull && docker compose up -d")
