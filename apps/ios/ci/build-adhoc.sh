#!/usr/bin/env bash
# Builds an Ad Hoc IPA with secrets injected from GitHub Actions.
# Never copy signing assets into the repository or upload them as artifacts.
set -euo pipefail

: "${RUNNER_TEMP:?GitHub-hosted macOS runner required}"
: "${GITHUB_RUN_NUMBER:?GitHub run number required}"
: "${IOS_P12_BASE64:?Set IOS_P12_BASE64 in Actions secrets}"
: "${IOS_P12_PASSWORD:?Set IOS_P12_PASSWORD in Actions secrets}"
: "${IOS_PROFILE_BASE64:?Set IOS_PROFILE_BASE64 in Actions secrets}"

ROOT="$PWD"
SIGNING_DIR="$(mktemp -d "$RUNNER_TEMP/narahem-signing.XXXXXX")"
KEYCHAIN="$SIGNING_DIR/ios-signing.keychain-db"
KEYCHAIN_PASSWORD="$(uuidgen)-$(uuidgen)"
PROFILE_INSTALLED=""
cleanup() {
  security delete-keychain "$KEYCHAIN" > /dev/null 2>&1 || true
  if [[ -n "$PROFILE_INSTALLED" ]]; then rm -f "$PROFILE_INSTALLED"; fi
  rm -rf "$SIGNING_DIR"
}
trap cleanup EXIT

umask 077
printf '%s' "$IOS_P12_BASE64" | base64 -D > "$SIGNING_DIR/distribution.p12"
printf '%s' "$IOS_PROFILE_BASE64" | base64 -D > "$SIGNING_DIR/profile.mobileprovision"
unset IOS_P12_BASE64 IOS_PROFILE_BASE64
security cms -D -i "$SIGNING_DIR/profile.mobileprovision" > "$SIGNING_DIR/profile.plist"

# Reject mismatched/expired/non-Ad-Hoc profiles before importing credentials.
python3 - "$SIGNING_DIR/profile.plist" "$SIGNING_DIR/signing.env" "$SIGNING_DIR/export-options.plist" << 'PY'
import datetime
import os
import pathlib
import plistlib
import re
import sys

source, environment, destination = [pathlib.Path(arg) for arg in sys.argv[1:]]
profile = plistlib.loads(source.read_bytes())
bundle_id = "com.robiem.narahem"
team_id = profile["TeamIdentifier"][0]
uuid = profile["UUID"]
app_identifier = profile["Entitlements"].get("application-identifier")
expiry = profile["ExpirationDate"]
if not re.fullmatch(r"[A-Z0-9]{10}", team_id) or not re.fullmatch(r"[0-9a-fA-F-]{36}", uuid):
    raise SystemExit("Invalid Apple team or provisioning profile UUID")
if app_identifier != team_id + "." + bundle_id:
    raise SystemExit("Provisioning profile does not match com.robiem.narahem")
if profile["Entitlements"].get("aps-environment") != "production":
    raise SystemExit("Ad Hoc profile must support Production APNs; regenerate after enabling Push Notifications")
if not profile.get("ProvisionedDevices") or profile.get("ProvisionsAllDevices"):
    raise SystemExit("Expected an Ad Hoc profile containing registered test iPhones")
if expiry.replace(tzinfo=datetime.timezone.utc) <= datetime.datetime.now(datetime.timezone.utc):
    raise SystemExit("The Ad Hoc provisioning profile has expired")
environment.write_text("TEAM_ID=" + team_id + "\nPROFILE_UUID=" + uuid + "\n")
plistlib.dump({
    "method": "release-testing",
    "destination": "export",
    "signingStyle": "manual",
    "teamID": team_id,
    "signingCertificate": "Apple Distribution",
    "provisioningProfiles": {bundle_id: uuid},
    "thinning": "<none>",
}, destination.open("wb"))
PY

# Only read trusted values extracted from the Apple-signed profile.
# shellcheck source=/dev/null  # written at run time by the signing step
source "$SIGNING_DIR/signing.env"
PROFILE_INSTALLED="$HOME/Library/MobileDevice/Provisioning Profiles/$PROFILE_UUID.mobileprovision"
mkdir -p "$(dirname "$PROFILE_INSTALLED")"
cp "$SIGNING_DIR/profile.mobileprovision" "$PROFILE_INSTALLED"

security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security list-keychains -d user -s "$KEYCHAIN"
security default-keychain -s "$KEYCHAIN"
# Verify the uploaded P12 with OpenSSL before handing it to Apple's Security.framework.
# OpenSSL 3's modern PKCS#12 defaults are valid but can fail Apple's importer with
# the misleading "MAC verification failed (wrong password?)" error.
# Rewrap only in the runner's private, short-lived directory. We use an
# independently encrypted intermediate PEM because OpenSSL's exporter needs
# a seekable input file; no plaintext private key is written to disk.
OPENSSL="$(brew --prefix openssl@3)/bin/openssl"
if ! "$OPENSSL" pkcs12 -in "$SIGNING_DIR/distribution.p12" \
  -passin env:IOS_P12_PASSWORD -noout; then
  echo "::error::P12 cannot be opened with IOS_P12_PASSWORD. Start a NEW workflow run after changing Actions secrets; rerunning an old run can reuse its original secret values."
  exit 1
fi
echo "P12/password verified by OpenSSL; adapting container for macOS keychain."
TEMP_PEM_PASSWORD="$(uuidgen)-$(uuidgen)"
export TEMP_PEM_PASSWORD
"$OPENSSL" pkcs12 -in "$SIGNING_DIR/distribution.p12" \
  -passin env:IOS_P12_PASSWORD -passout env:TEMP_PEM_PASSWORD \
  -out "$SIGNING_DIR/encrypted-keypair.pem"
"$OPENSSL" pkcs12 -export -in "$SIGNING_DIR/encrypted-keypair.pem" \
  -out "$SIGNING_DIR/distribution-apple.p12" \
  -passin env:TEMP_PEM_PASSWORD -passout env:IOS_P12_PASSWORD \
  -legacy -macalg sha1 -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES
unset TEMP_PEM_PASSWORD
rm -f "$SIGNING_DIR/encrypted-keypair.pem"
security import "$SIGNING_DIR/distribution-apple.p12" -k "$KEYCHAIN" -P "$IOS_P12_PASSWORD" -T /usr/bin/codesign -T /usr/bin/security
unset IOS_P12_PASSWORD
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN" > /dev/null
if ! security find-identity -v -p codesigning "$KEYCHAIN" | grep -q 'Apple Distribution'; then
  echo "::error::No valid Apple Distribution signing identity was imported"
  exit 1
fi

# Inject only ordinary substitution variables via xcconfig. The signing values
# apply to Nära Hem Release in project.yml, NOT the Google Maps package
# targets. Global PROVISIONING_PROFILE_SPECIFIER causes Xcode error 65 because
# GoogleMaps_GoogleMapsTarget (a resource bundle) cannot accept app profiles.
XCCONFIG="$SIGNING_DIR/adhoc.xcconfig"
printf 'NARAHEM_SIGNING_TEAM_ID = %s\n' "$TEAM_ID" > "$XCCONFIG"
printf 'NARAHEM_SIGNING_PROFILE_UUID = %s\n' "$PROFILE_UUID" >> "$XCCONFIG"
BUILD_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
BUILD_COMMIT="$(git rev-parse --short=10 HEAD)"
printf 'NARAHEM_BUILD_UTC = %s\n' "$BUILD_UTC" >> "$XCCONFIG"
printf 'NARAHEM_BUILD_COMMIT = %s\n' "$BUILD_COMMIT" >> "$XCCONFIG"
if [[ -n "${IOS_GOOGLE_MAPS_KEY:-}" ]]; then
  if [[ ! "$IOS_GOOGLE_MAPS_KEY" =~ ^AIza[A-Za-z0-9_-]+$ ]]; then
    echo "::error::Invalid iOS Google Maps API key format"
    exit 1
  fi
  printf 'NARAHEM_GOOGLE_MAPS_IOS_API_KEY = %s\n' "$IOS_GOOGLE_MAPS_KEY" >> "$XCCONFIG"
fi
export XCODE_XCCONFIG_FILE="$XCCONFIG"
unset IOS_GOOGLE_MAPS_KEY

ARCHIVE="$SIGNING_DIR/NaraHem.xcarchive"
EXPORT="$SIGNING_DIR/ipa-export"
xcodebuild archive -project NaraHem.xcodeproj -scheme NaraHem \
  -configuration Release -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE" -derivedDataPath "$SIGNING_DIR/derived" \
  "CURRENT_PROJECT_VERSION=$((GITHUB_RUN_NUMBER + 1000))"

xcodebuild -exportArchive -archivePath "$ARCHIVE" \
  -exportPath "$EXPORT" -exportOptionsPlist "$SIGNING_DIR/export-options.plist"

IPA="$(find "$EXPORT" -maxdepth 1 -name '*.ipa' -type f -print -quit)"
if [[ -z "$IPA" ]]; then
  echo "::error::Xcode did not export an iPhone IPA"
  exit 1
fi

mkdir -p "$ROOT/build-output"
cp "$IPA" "$ROOT/build-output/NaraHem.ipa"
# Keep legacy installer filename and include a dated debug IPA as well.
cp "$IPA" "$ROOT/build-output/NaraHem-iOS-$(date -u '+%Y%m%d-%H%M')-build$((GITHUB_RUN_NUMBER + 1000)).ipa"
mkdir -p "$SIGNING_DIR/verify"
unzip -q "$ROOT/build-output/NaraHem.ipa" -d "$SIGNING_DIR/verify"
APP="$SIGNING_DIR/verify/Payload/NaraHem.app"
test -d "$APP"
codesign --verify --deep --strict "$APP"
codesign -d --entitlements :- "$APP" > "$SIGNING_DIR/app-entitlements.plist" 2> /dev/null
security cms -D -i "$APP/embedded.mobileprovision" > "$SIGNING_DIR/embedded.plist"
python3 - "$SIGNING_DIR/embedded.plist" "$PROFILE_UUID" "$SIGNING_DIR/app-entitlements.plist" << 'PY'
import plistlib, pathlib, sys
embedded = plistlib.loads(pathlib.Path(sys.argv[1]).read_bytes())
if embedded["UUID"] != sys.argv[2]:
    raise SystemExit("IPA contains an unexpected provisioning profile")
signed = plistlib.loads(pathlib.Path(sys.argv[3]).read_bytes())
if embedded["Entitlements"].get("aps-environment") != "production" or signed.get("aps-environment") != "production":
    raise SystemExit("Signed IPA is missing Production APNs entitlement")
print("Signed IPA verified: NaraHem.ipa (Ad Hoc, Production APNs enabled)")
PY
