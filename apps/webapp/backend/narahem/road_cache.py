"""On-demand, bounded and local-only OpenStreetMap road graph cache.

Only public regional extracts are downloaded. Actual GPS points are passed
exclusively to the loopback OSRM process in Nära Hem's own container.

PARKED: road matching is switched off (see TripProcessor in trip_processing.py) and is kept
for a possible future version. Only the tests use this module today.
"""

import json
import math
import os
import re
import resource
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

INDEX_URL = "https://download.geofabrik.de/index-v1.json"
LOCAL_OSRM = "http://127.0.0.1:5000"


def setting(name, default, lower, upper):
    """Reads a number from the environment, clamped to lower..upper."""
    try:
        value = int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default
    return min(upper, max(lower, value))


def polygon_contains(geometry, latitude, longitude):
    """Returns True if a GeoJSON Polygon or MultiPolygon (with holes) contains the point."""
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return False
    polygons = (
        [geometry.get("coordinates", [])]
        if geometry["type"] == "Polygon"
        else geometry.get("coordinates", [])
    )

    def inside(ring):
        """Returns True if the point is inside the ring."""
        result = False
        for a, b in zip(ring, ring[1:] + ring[:1]):
            x1, y1 = a[:2]
            x2, y2 = b[:2]
            if (y1 > latitude) != (y2 > latitude):
                crossing = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
                if longitude < crossing:
                    result = not result
        return result

    return any(
        poly and inside(poly[0]) and not any(inside(hole) for hole in poly[1:]) for poly in polygons
    )


def feature_area(feature):
    """Returns the approximate area of a catalog region, used to prefer the smallest match."""
    coords = []

    def walk(node):
        """Collects every coordinate in nested GeoJSON coordinates."""
        if node and isinstance(node[0], (int, float)):
            coords.append(node)
        else:
            for child in node:
                walk(child)

    walk(feature["geometry"]["coordinates"])
    return (
        (
            (max(p[0] for p in coords) - min(p[0] for p in coords))
            * (max(p[1] for p in coords) - min(p[1] for p in coords))
        )
        if coords
        else float("inf")
    )


def candidate_regions(features, points):
    """Returns the smallest available regions covering all the points."""
    matches = []
    for feature in features:
        props = feature.get("properties") or {}
        url = (props.get("urls") or {}).get("pbf")
        rid = props.get("id", "")
        if not (
            isinstance(rid, str)
            and re.fullmatch(r"[a-z0-9_/-]{2,80}", rid)
            and isinstance(url, str)
            and legal_download(url)
        ):
            continue
        if all(polygon_contains(feature.get("geometry"), p["lat"], p["lon"]) for p in points):
            matches.append((feature_area(feature), rid.replace("/", "__"), url))
    return sorted(matches)


def legal_download(url):
    """Returns True only for Geofabrik regional extract URLs."""
    p = urlsplit(url)
    return (
        p.scheme == "https"
        and p.hostname == "download.geofabrik.de"
        and not p.username
        and not p.password
        and not p.port
        and not p.query
        and not p.fragment
        and p.path.endswith(".osm.pbf")
    )


def circle_points(lat, lon, miles):
    """Returns points around a circle, for finding the regions it overlaps."""
    radius = miles / 69.0
    lon_delta = radius / max(0.15, math.cos(math.radians(lat)))
    return [
        {"lat": lat, "lon": lon},
        {"lat": lat + radius, "lon": lon},
        {"lat": lat - radius, "lon": lon},
        {"lat": lat, "lon": lon + lon_delta},
        {"lat": lat, "lon": lon - lon_delta},
    ]


class RoadCache:
    """Parked with road matching. Downloads road data around saved places and runs a local OSRM
    server.
    """

    def __init__(self, directory):
        """Creates the cache directory and reads the limits."""
        self.root = Path(directory) / "roads"
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.meta_file = self.root / "manifest.json"
        self.index_file = self.root / "geofabrik-index.json"
        self.ttl_days = setting("NARAHEM_ROAD_CACHE_TTL_DAYS", 21, 1, 3650)
        self.pin_miles = setting("NARAHEM_ROAD_PIN_RADIUS_MILES", 25, 1, 250)
        self.max_bytes = setting("NARAHEM_ROAD_CACHE_MAX_GB", 8, 1, 256) * 1024**3
        self.download_max = setting("NARAHEM_ROAD_DOWNLOAD_MAX_MB", 512, 32, 4096) * 1024**2
        self.prep_mem = setting("NARAHEM_ROAD_PREP_MEMORY_MB", 2048, 512, 32768) * 1024**2
        self.threads = setting("NARAHEM_ROAD_THREADS", 1, 1, 4)
        self.last_error = ""
        self.process = None
        self.active_id = None
        self.pinned = set()
        self.pin_urls = {}
        self.pin_retry = {}
        self.last_clean = 0
        self._index = None
        try:
            self.metadata = json.loads(self.meta_file.read_text())
            if not isinstance(self.metadata, dict):
                self.metadata = {}
        except (FileNotFoundError, ValueError):
            self.metadata = {}

    def save(self):
        """Writes the cache metadata file."""
        tmp = self.meta_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.metadata, separators=(",", ":")))
        os.replace(tmp, self.meta_file)

    def features(self):
        """Returns the region catalog, downloading it once."""
        if self._index is not None:
            return self._index
        refresh = (
            not self.index_file.exists()
            or time.time() - self.index_file.stat().st_mtime > 7 * 86400
        )
        if refresh:
            try:
                data = self.download(INDEX_URL, 48 * 1024**2)
                parsed = json.loads(data)
                if parsed.get("type") != "FeatureCollection" or not isinstance(
                    parsed.get("features"), list
                ):
                    raise ValueError("Invalid road extract catalog")
                tmp = self.index_file.with_suffix(".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, self.index_file)
            except (OSError, ValueError, httpx.HTTPError):
                if not self.index_file.exists():
                    return []
        try:
            self._index = json.loads(self.index_file.read_text())["features"]
        except (OSError, ValueError, KeyError):
            self._index = []
        return self._index

    def download(self, url, max_bytes):
        """Downloads an allowed URL with a size limit."""
        if url != INDEX_URL and not legal_download(url):
            raise ValueError("Only approved public road extracts may be downloaded")
        with httpx.Client(
            trust_env=False, follow_redirects=False, timeout=httpx.Timeout(30, read=90)
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("Road download redirected")
                if int(response.headers.get("content-length", "0")) > max_bytes:
                    raise ValueError("Road extract exceeds download limit")
                chunks, total = [], 0
                for part in response.iter_bytes(1024 * 1024):
                    total += len(part)
                    if total > max_bytes:
                        raise ValueError("Road extract exceeds download limit")
                    chunks.append(part)
                return b"".join(chunks)

    def storage_used(self):
        """Returns the bytes used by the cache."""
        return sum(p.stat().st_size for p in self.root.glob("*/**/*") if p.is_file())

    def pin_saved_places(self, places):
        """Pins the regions covering 25 miles around every saved place."""
        pins = set()
        urls = {}
        features = self.features() if places else (self._index or [])
        if places and not features:
            return
        for place in places:
            lat, lon = place.get("lat"), place.get("lon")
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                continue
            if not all(map(math.isfinite, (lat, lon))) or abs(lat) > 90 or abs(lon) > 180:
                continue
            for pt in circle_points(lat, lon, self.pin_miles):
                matches = candidate_regions(features, [pt])
                if matches:
                    pins.add(matches[0][1])
                    urls[matches[0][1]] = matches[0][2]
        for rid in self.pinned - pins:
            if rid in self.metadata:
                self.metadata[rid]["used"] = time.time()
        if self.pinned != pins:
            self.save()
        self.pinned = pins
        self.pin_urls = urls

    def prepare_one_pinned(self):
        """Builds one missing pinned region per worker pass."""
        for rid in sorted(self.pinned):
            if (self.root / rid / "region.osrm").exists():
                continue
            if time.time() < self.pin_retry.get(rid, 0):
                continue
            url = self.pin_urls.get(rid)
            if not url:
                continue
            result = self._prepare(rid, url)
            if not result:
                self.pin_retry[rid] = time.time() + 3600
            return result
        return None

    def cleanup(self):
        """Deletes regions no longer pinned, at most once an hour."""
        now = time.time()
        if now - self.last_clean < 3600:
            return
        self.last_clean = now
        changed = False
        for rid, meta in list(self.metadata.items()):
            if rid in self.pinned or rid == self.active_id:
                continue
            if now - float(meta.get("used", now)) <= self.ttl_days * 86400:
                continue
            shutil.rmtree(self.root / rid, ignore_errors=True)
            del self.metadata[rid]
            changed = True
        if changed:
            self.save()

    def stop(self):
        """Stops the OSRM process."""
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            self.process = None
        self.active_id = None

    def _limits(self):
        """Applies memory and CPU limits to the OSRM build process."""
        resource.setrlimit(resource.RLIMIT_AS, (self.prep_mem, self.prep_mem))
        resource.setrlimit(resource.RLIMIT_CPU, (1800, 1800))

    def _prepare(self, rid, url):
        """Downloads a region and builds its OSRM graph, stopping if disk space runs low."""
        self.stop()
        target = self.root / rid
        temp = self.root / (rid + ".building")
        shutil.rmtree(temp, ignore_errors=True)
        temp.mkdir(mode=0o700)
        try:
            self.last_error = ""
            if self.storage_used() >= self.max_bytes:
                raise ValueError("Road cache disk quota reached")
            pbf = self.download(url, min(self.download_max, self.max_bytes - self.storage_used()))
            (temp / "region.osm.pbf").write_bytes(pbf)
            del pbf
            for command in (
                ["osrm-extract", "-p", "/opt/car.lua", str(temp / "region.osm.pbf")],
                ["osrm-partition", str(temp / "region.osrm")],
                ["osrm-customize", str(temp / "region.osrm")],
            ):
                process = subprocess.Popen(
                    command,
                    cwd=str(temp),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=self._limits,
                    env={**os.environ, "TMPDIR": str(temp), "OMP_NUM_THREADS": str(self.threads)},
                )
                deadline = time.monotonic() + 1800
                while process.poll() is None:
                    if (
                        time.monotonic() > deadline
                        or self.storage_used() > self.max_bytes
                        or shutil.disk_usage(self.root).free < 128 * 1024**2
                    ):
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        raise ValueError("Road preparation exceeded resource budget")
                    time.sleep(1)
                if process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, command)
            (temp / "region.osm.pbf").unlink(missing_ok=True)
            if not (temp / "region.osrm").exists():
                raise ValueError("OSRM preprocessing did not create an index")
            if target.exists():
                shutil.rmtree(target)
            temp.rename(target)
            self.metadata[rid] = {"used": time.time()}
            self.save()
            return True
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.last_error = (type(exc).__name__ + ": " + str(exc))[:150]
            return False
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def ready_for(self, fixes):
        """Returns a URL of an OSRM server covering the fixes, starting one if needed, or None."""
        self.last_error = ""
        if len(fixes) < 3:
            self.last_error = "fewer_than_three_usable_points"
            return None
        choices = candidate_regions(self.features(), fixes)
        if not choices:
            self.last_error = "no_available_road_map_region_for_full_trip"
            return None
        _, rid, url = choices[0]
        folder = self.root / rid
        if not (folder / "region.osrm").exists() and not self._prepare(rid, url):
            self.last_error = self.last_error or "failed_to_download_or_prepare_road_graph"
            return None
        if rid != self.active_id or self.process is None or self.process.poll() is not None:
            self.stop()
            self.process = subprocess.Popen(
                [
                    "osrm-routed",
                    "--algorithm",
                    "mld",
                    "--ip",
                    "127.0.0.1",
                    "--port",
                    "5000",
                    "--threads",
                    str(self.threads),
                    str(folder / "region.osrm"),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
            self.active_id = rid
            with httpx.Client(trust_env=False, timeout=1) as client:
                for _ in range(40):
                    if self.process.poll() is not None:
                        self.stop()
                        self.last_error = "road_matcher_process_exited"
                        return None
                    try:
                        result = client.get(
                            LOCAL_OSRM
                            + "/nearest/v1/driving/"
                            + str(fixes[0]["lon"])
                            + ","
                            + str(fixes[0]["lat"])
                        )
                        if result.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.5)
                else:
                    self.stop()
                    self.last_error = "road_matcher_healthcheck_timeout"
                    return None
        self.metadata[rid] = {"used": time.time()}
        self.save()
        return LOCAL_OSRM
