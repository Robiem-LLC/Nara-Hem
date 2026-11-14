"""Checks that a request to the Alexa skill really comes from Amazon.

Amazon signs each request body and says where its certificate is. The certificate must come
from Amazon's own address, be valid for echo-api.amazon.com and chain to a trusted root, and the
request must be recent. See Amazon's "Host a custom skill as a web service".
"""

import base64
import posixpath
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

import certifi
import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

AMAZON_HOST = "echo-api.amazon.com"
TOLERANCE_SECONDS = 150
_certificates = {}


class NotFromAmazon(Exception):
    """The request is not a genuine, recent request from Amazon."""


def certificate_url(url):
    """Returns the URL if it is where Amazon keeps its signing certificates, or raises."""
    parts = urlsplit(url or "")
    path = posixpath.normpath(parts.path) if parts.path else ""
    if (
        parts.scheme.lower() != "https"
        or (parts.hostname or "").lower() != "s3.amazonaws.com"
        or parts.port not in (None, 443)
        or not path.startswith("/echo.api/")
        or parts.username
        or parts.password
    ):
        raise NotFromAmazon("Untrusted certificate address")
    return url


def roots():
    """Returns the trusted root certificates."""
    with open(certifi.where(), "rb") as bundle:
        return Store(x509.load_pem_x509_certificates(bundle.read()))


def fetch(url):
    """Downloads a certificate chain."""
    try:
        response = httpx.get(url, timeout=3, follow_redirects=False)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise NotFromAmazon("Certificate unavailable") from error
    return response.content


def signing_key(url, now=None, store=None, download=fetch):
    """Returns the public key of Amazon's signing certificate at url, after checking the
    certificate and its chain. Valid chains are remembered until the certificate expires.
    """
    when = datetime.fromtimestamp(now or time.time(), UTC)
    cached = _certificates.get(url)
    if cached and cached[1] > when:
        return cached[0]
    try:
        chain = x509.load_pem_x509_certificates(download(certificate_url(url)))
    except ValueError as error:
        raise NotFromAmazon("Unreadable certificate") from error
    verifier = (
        PolicyBuilder()
        .store(store or roots())
        .time(when)
        .build_server_verifier(x509.DNSName(AMAZON_HOST))
    )
    try:
        verifier.verify(chain[0], chain[1:])
    except VerificationError as error:
        raise NotFromAmazon("Certificate is not Amazon's") from error
    key = chain[0].public_key()
    _certificates[url] = (key, chain[0].not_valid_after_utc)
    return key


def check(headers, body, request, now=None, key_for=signing_key):
    """Raises NotFromAmazon unless the body carries a valid Amazon signature and a timestamp
    within 150 seconds.
    """
    url = headers.get("signaturecertchainurl")
    signature = headers.get("signature-256")
    if not url or not signature:
        raise NotFromAmazon("Missing signature")
    try:
        key_for(url).verify(base64.b64decode(signature), body, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError) as error:
        raise NotFromAmazon("Bad signature") from error
    recent(request, now)


def recent(request, now=None):
    """Raises NotFromAmazon unless the request's timestamp is within 150 seconds."""
    try:
        stamp = datetime.fromisoformat(request["request"]["timestamp"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise NotFromAmazon("Missing timestamp") from error
    if abs((now or time.time()) - stamp.timestamp()) > TOLERANCE_SECONDS:
        raise NotFromAmazon("Request is too old")
