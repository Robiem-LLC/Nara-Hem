#!/usr/bin/env python3
"""Publish verified mobile artifacts to a strictly configured Mac-local directory or SMB share."""

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/ios/ci/remote"))
from build import decode_profile, validate_profile

DEFAULT_CONFIG = Path("/Library/Application Support/NaraHemRunner/publish.json")
CHANNELS = ("main", "dev")


def digest(path):
    """Returns the SHA-256 digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def package(source, platform):
    """Returns the single APK or IPA in a build directory."""
    suffix = ".apk" if platform == "android" else ".ipa"
    files = sorted(p for p in source.rglob("*" + suffix) if p.is_file())
    if not files:
        raise ValueError("No package found")
    # Hosted iOS export uploads both dated and legacy names of the same IPA.
    checksums = set()
    for path in files:
        if path.is_symlink() or source.resolve() not in path.resolve().parents:
            raise ValueError("Package must be a regular file inside the download directory")
        checksums.add(digest(path))
    if len(checksums) != 1:
        raise ValueError("Expected exactly one unique package, found different binaries")
    chosen = files[0]
    with zipfile.ZipFile(chosen) as archive:
        names = set(archive.namelist())
        if platform == "android":
            if not {"AndroidManifest.xml", "classes.dex"} <= names:
                raise ValueError("Invalid APK structure")
        else:
            app = "Payload/NaraHem.app/"
            if (
                not {
                    app + "Info.plist",
                    app + "embedded.mobileprovision",
                    app + "_CodeSignature/CodeResources",
                }
                <= names
            ):
                raise ValueError("Expected a signed NaraHem IPA")
            if any(n.startswith("/") or ".." in Path(n).parts for n in names):
                raise ValueError("Invalid IPA archive paths")
    if platform == "ios":
        with tempfile.TemporaryDirectory(prefix="narahem-ipa-verify-") as folder:
            subprocess.run(["/usr/bin/ditto", "-x", "-k", str(chosen), folder], check=True)
            app = Path(folder) / "Payload/NaraHem.app"
            subprocess.run(
                ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True
            )
            profile = decode_profile(app / "embedded.mobileprovision")
            team = validate_profile(profile, "ad-hoc")
            ent = plistlib.loads(
                subprocess.check_output(["codesign", "-d", "--entitlements", ":-", str(app)])
            )
            info = plistlib.loads((app / "Info.plist").read_bytes())
            if (
                info.get("CFBundleIdentifier") != "com.robiem.narahem"
                or ent.get("application-identifier") != team + ".com.robiem.narahem"
                or ent.get("aps-environment") != "production"
                or ent.get("get-task-allow", False)
            ):
                raise ValueError("NAS IPA must be an Ad Hoc NaraHem build with Production APNs")
    return chosen


def publish(root, source, platform, run_id, attempt, commit, receipt=None, channel="main"):
    """Copies a build into an immutable versioned folder and atomically updates the latest
    pointer. Dev builds use their own folders, android-dev and ios-dev.
    """
    stage = None
    if channel not in CHANNELS:
        raise ValueError("Unknown build channel")
    folder = platform if channel == "main" else f"{platform}-{channel}"
    artifact = package(source, platform)  # Validate before touching the share.
    if receipt is not None:
        record = json.loads(receipt.read_text())
        if (
            platform != "ios"
            or record.get("type") != "signed-device-ipa"
            or record.get("method") != "ad-hoc"
            or record.get("commit") != commit
            or record.get("sha256") != digest(artifact)
        ):
            raise ValueError("Signed receipt does not match this Ad Hoc IPA and source commit")
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".publish-lock"
    lock.mkdir()  # SMB server arbitrates competing publishers; fail rather than break a lock.
    try:
        builds = root / folder / "builds"
        builds.mkdir(parents=True, exist_ok=True)
        (root / folder).chmod(0o755)
        builds.chmod(0o755)
        version = f"{run_id}-{attempt}-{commit[:12]}"
        destination = builds / version
        filename = "NaraHem.apk" if platform == "android" else "NaraHem.ipa"
        checksum = digest(artifact)
        manifest = {
            "platform": platform,
            "run_id": int(run_id),
            "attempt": int(attempt),
            "commit": commit,
            "sha256": checksum,
            "bytes": artifact.stat().st_size,
            "artifact": f"builds/{version}/{filename}",
            "workflow_run": (
                f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{run_id}"
            ),
        }
        if channel != "main":
            manifest["channel"] = (
                channel  # main manifests stay byte-identical for idempotent retries.
            )
        if destination.exists():
            previous = json.loads((destination / "manifest.json").read_text())
            if previous != manifest or digest(destination / filename) != checksum:
                raise ValueError(
                    "Version already exists with different contents; refusing overwrite"
                )
        else:
            stage = Path(tempfile.mkdtemp(prefix=".upload-", dir=builds))
            shutil.copyfile(artifact, stage / filename)
            if digest(stage / filename) != checksum:
                raise OSError("SMB copy checksum mismatch")
            (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            # Same-share rename: incomplete uploads never become visible as a version.
            (stage / filename).chmod(0o644)
            (stage / "manifest.json").chmod(0o644)
            stage.chmod(0o755)
            stage.rename(destination)
            stage = None
        latest = root / folder / "latest.json"
        current = json.loads(latest.read_text()) if latest.exists() else None
        # Provide one obvious file to copy from Windows Explorer. Never replace
        # the previous working binary until its successor is fully verified.
        if not current or (int(run_id), int(attempt)) >= (current["run_id"], current["attempt"]):
            platform_root = root / folder
            fd, temp_name = tempfile.mkstemp(prefix=".package-", dir=platform_root)
            os.close(fd)
            temp_file = Path(temp_name)
            try:
                shutil.copyfile(destination / filename, temp_file)
                if digest(temp_file) != checksum:
                    raise OSError("Latest package checksum mismatch")
                temp_file.chmod(0o644)
                os.replace(temp_file, platform_root / filename)
            finally:
                temp_file.unlink(missing_ok=True)
        if not current or (int(run_id), int(attempt)) >= (current["run_id"], current["attempt"]):
            # The pointer is authoritative and portable on SMB/Windows (no symlinks).
            # Never replace the old pointer before the immutable package is verified.
            fd, temp_name = tempfile.mkstemp(prefix=".latest-", dir=latest.parent)
            temp = Path(temp_name)
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump(manifest, stream, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                temp.chmod(0o644)
                os.replace(temp, latest)
            finally:
                temp.unlink(missing_ok=True)
        # Keep the current version and at most two historical versions per platform.
        # Only remove old immutable folders *after* the new copy and pointer exist.
        all_versions = []
        for folder in builds.iterdir():
            if folder.is_dir() and not folder.name.startswith("."):
                manifest_path = folder / "manifest.json"
                if manifest_path.exists():
                    try:
                        record = json.loads(manifest_path.read_text())
                        all_versions.append((int(record["run_id"]), int(record["attempt"]), folder))
                    except (ValueError, KeyError, TypeError):
                        continue  # Do not delete unrecognized directories.
        all_versions.sort(reverse=True)
        for _, _, obsolete in all_versions[3:]:
            shutil.rmtree(obsolete)
        print("Published:", destination / filename)
        print("Latest pointer:", latest)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
                summary.write(
                    f"Local Mac share delivery verified: `{destination / filename}`\n\nSHA-256: "
                    f"`{checksum}`\n\nLatest: `{latest}`\n"
                )
        return destination
    finally:
        # Never delete successful versions. Clean only this invocation's unfinished upload.
        if stage is not None:
            shutil.rmtree(stage)
        lock.rmdir()


def configured_root(config_path):
    """Returns the publish directory from the runner config, or None if publishing is disabled."""
    config = json.loads(config_path.read_text())
    if config.get("enabled") is not True:
        raise ValueError("Publishing is disabled in the local configuration")
    if config.get("mode") == "local":
        # Explicitly allow only the dedicated local distribution directory.
        # Never silently fall back to an arbitrary path on mount failure.
        root = Path(config.get("root") or "")
        if str(root) != "/Users/Shared/NaraHem" or root.is_symlink() or not root.is_dir():
            raise ValueError("Expected pre-created /Users/Shared/NaraHem local directory")
        if not os.access(root, os.W_OK | os.X_OK):
            raise ValueError("Local distribution directory is not writable by runner")
        return root
    mount = Path(config.get("mountpoint") or "")
    directory = Path(config.get("directory", "NaraHem"))
    if not mount.is_absolute() or not os.path.ismount(mount):
        raise ValueError("An existing absolute SMB mountpoint is required; refusing local fallback")
    mounts = subprocess.check_output(["/sbin/mount", "-t", "smbfs"], text=True).splitlines()
    smb_paths = [line.rsplit(" on ", 1)[-1].rsplit(" (", 1)[0] for line in mounts]
    if str(mount) not in smb_paths:
        raise ValueError("Configured mountpoint is not SMB; refusing local fallback")
    if directory.is_absolute() or ".." in directory.parts or not directory.parts:
        raise ValueError("directory must be a nonempty relative path within the share")
    target = (mount / directory).resolve()
    if mount.resolve() not in target.parents:
        raise ValueError("Destination escapes the SMB mountpoint")
    return target


def main():
    """Command line entry point: publishes a build with its checksum."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--check", action="store_true", help="Read-only mount/config preflight")
    p.add_argument("--platform", choices=["android", "ios"])
    p.add_argument("--source", type=Path)
    p.add_argument("--run-id", type=int)
    p.add_argument("--attempt", type=int)
    p.add_argument("--commit")
    p.add_argument("--receipt", type=Path)
    p.add_argument("--channel", choices=CHANNELS, default="main")
    args = p.parse_args()
    target = configured_root(args.config)
    if args.check:
        print("SMB configuration and mount available:", target)
        return
    if not all([args.platform, args.source, args.run_id, args.attempt, args.commit]):
        p.error("Require platform, source, run-id, attempt and commit")
    if args.run_id < 1 or args.attempt < 1 or not re.fullmatch(r"[a-f0-9]{40}", args.commit):
        p.error("Expected positive run/attempt and full Git commit SHA")
    publish(
        target,
        args.source,
        args.platform,
        args.run_id,
        args.attempt,
        args.commit,
        args.receipt,
        args.channel,
    )


if __name__ == "__main__":
    main()
