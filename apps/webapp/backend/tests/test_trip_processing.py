import os
import unittest
from unittest.mock import patch

from narahem.trip_processing import match_local_roads, meters, normalize_points


class TripProcessingTests(unittest.TestCase):
    def test_raw_observations_reject_outliers_and_stationary_drift(self):
        points = [
            dict(time=1000, lat=40.0, lon=-74.0, accuracy=5),
            dict(time=2000, lat=41.0, lon=-74.0, accuracy=5),
            dict(time=11000, lat=40.000005, lon=-74.0, accuracy=5),
            dict(time=16000, lat=40.001, lon=-74.0, accuracy=5),
            dict(time=31000, lat=40.002, lon=-74.0, accuracy=5),
        ]
        result = normalize_points(points)
        self.assertEqual([p["time"] for p in result], [1000, 16000, 31000])
        self.assertGreater(meters(result[0], result[-1]), 200)

    def test_road_match_never_uses_public_service_url(self):
        points = [
            dict(time=1000, lat=40.0, lon=-74.0, accuracy=5),
            dict(time=16000, lat=40.001, lon=-74.0, accuracy=5),
            dict(time=31000, lat=40.002, lon=-74.0, accuracy=5),
        ]
        with patch.dict(os.environ, {"NARAHEM_ROAD_MATCH_URL": "https://public.example.invalid"}):
            with self.assertRaises(ValueError):
                match_local_roads(points)
        with patch.dict(os.environ, {"NARAHEM_ROAD_MATCH_URL": ""}):
            self.assertIsNone(match_local_roads(points))

    def test_offline_osrm_failure_preserves_raw_route(self):
        points = [
            dict(time=1000, lat=40.0, lon=-74.0, accuracy=5),
            dict(time=16000, lat=40.001, lon=-74.0, accuracy=5),
            dict(time=31000, lat=40.002, lon=-74.0, accuracy=5),
        ]
        from httpx import ConnectError, Request

        with (
            patch.dict(os.environ, {"NARAHEM_ROAD_MATCH_URL": "http://roadmatcher:5000"}),
            patch("narahem.trip_processing.httpx.Client") as client,
        ):
            client.return_value.__enter__.return_value.get.side_effect = ConnectError(
                "not available", request=Request("GET", "http://roadmatcher:5000")
            )
            self.assertIsNone(match_local_roads(points))
            self.assertEqual(client.call_args.kwargs.get("trust_env"), False)

    def test_region_selection_and_download_url_safety(self):
        from narahem.road_cache import (
            candidate_regions,
            circle_points,
            legal_download,
            polygon_contains,
        )

        def feature(name, bounds):
            left, bottom, right, top = bounds
            ring = [[left, bottom], [right, bottom], [right, top], [left, top], [left, bottom]]
            return {
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "id": name,
                    "urls": {
                        "pbf": "https://download.geofabrik.de/north-america/us/oregon-latest.osm.pbf"
                    },
                },
            }

        large = feature("north-america", (-125, 20, -60, 55))
        oregon = feature("us/oregon", (-125, 42, -116, 47))
        matches = candidate_regions([large, oregon], [{"lat": 44.0, "lon": -120.5}])
        self.assertEqual(matches[0][1], "us__oregon")
        self.assertTrue(polygon_contains(oregon["geometry"], 44.0, -120.5))
        self.assertFalse(polygon_contains(oregon["geometry"], 44.0, -110))
        self.assertEqual(len(circle_points(40.5, -74.5, 25)), 5)
        self.assertFalse(legal_download("http://127.0.0.1/private.osm.pbf"))
        self.assertFalse(legal_download("https://download.geofabrik.de.evil.invalid/a.osm.pbf"))

    def test_thread_setting_has_a_bounded_override(self):
        import tempfile

        from narahem.road_cache import RoadCache

        with (
            tempfile.TemporaryDirectory() as d,
            patch.dict(os.environ, {"NARAHEM_ROAD_THREADS": "99"}),
        ):
            self.assertEqual(RoadCache(d).threads, 4)

    def test_cache_expiry_preserves_pinned_home_region(self):
        import json
        import tempfile
        import time

        from narahem.road_cache import RoadCache

        with tempfile.TemporaryDirectory() as d:
            cache = RoadCache(d)
            old = time.time() - 22 * 86400
            cache.metadata = {"us__oregon": {"used": old}, "us__hawaii": {"used": old}}
            for rid in cache.metadata:
                (cache.root / rid).mkdir()
                (cache.root / rid / "region.osrm").write_text("fixture")
            cache.pinned = {"us__oregon"}
            cache.cleanup()
            self.assertTrue((cache.root / "us__oregon").exists())
            self.assertFalse((cache.root / "us__hawaii").exists())
            self.assertIn("us__oregon", json.loads(cache.meta_file.read_text()))

    def test_download_uses_only_direct_no_proxy_connection(self):
        import tempfile

        from narahem.road_cache import RoadCache

        with tempfile.TemporaryDirectory() as d:
            cache = RoadCache(d)
            with patch("narahem.road_cache.httpx.Client") as client:
                client.return_value.__enter__.return_value.stream.side_effect = RuntimeError(
                    "guard"
                )
                with self.assertRaises(RuntimeError):
                    cache.download(
                        "https://download.geofabrik.de/north-america/us/oregon-latest.osm.pbf",
                        1024,
                    )
                self.assertEqual(client.call_args.kwargs["trust_env"], False)


if __name__ == "__main__":
    unittest.main()
