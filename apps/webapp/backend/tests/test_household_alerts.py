import unittest
from unittest.mock import patch

import httpx

from narahem import household_alerts as alerts

HOME = {"id": "h" * 32, "name": "Home", "lat": 40.0, "lon": -74.0, "radius": 100, "alerts": {}}


class HouseholdAlertRuleTests(unittest.TestCase):
    def test_trip_ends_at_the_place_the_phone_reached_just_after(self):
        def fix(lat, time, accuracy=10):
            return {
                "lat": lat,
                "lon": -74.0,
                "accuracy": accuracy,
                "time": time,
            }

        end, short = 1_000_000, [40.0015, -74.0]  # ~170 m short of Home
        self.assertEqual(alerts.boundary_place([40.0, -74.0], end, [], [HOME], after=True), HOME)
        self.assertIsNone(alerts.boundary_place(short, end, [], [HOME], after=True))
        self.assertEqual(
            alerts.boundary_place(short, end, [fix(40.0, end + 60_000)], [HOME], after=True), HOME
        )
        self.assertIsNone(
            alerts.boundary_place(short, end, [fix(40.0, end + 180_000)], [HOME], after=True),
            "too late",
        )
        self.assertIsNone(
            alerts.boundary_place(short, end, [fix(40.0, end - 60_000)], [HOME], after=True),
            "wrong side",
        )
        self.assertIsNone(
            alerts.boundary_place(short, end, [fix(40.0, end + 60_000, 90)], [HOME], after=True),
            "too vague",
        )
        self.assertIsNone(
            alerts.boundary_place([40.5, -74.0], end, [fix(40.0, end + 2_000)], [HOME], after=True),
            "could not have got there",
        )
        self.assertEqual(
            alerts.boundary_place(short, end, [fix(40.0, end - 60_000)], [HOME], after=False), HOME
        )
        # A parked phone checks in rarely: Home 9 minutes before GPS started is still the start.
        away = [40.006, -74.0]
        self.assertEqual(
            alerts.boundary_place(away, end, [fix(40.0, end - 540_000)], [HOME], after=False), HOME
        )
        self.assertIsNone(
            alerts.boundary_place(
                away,
                end,
                [fix(40.0, end - 540_000), fix(40.02, end - 300_000)],
                [HOME],
                after=False,
            ),
            "somewhere else in between",
        )
        self.assertIsNone(
            alerts.boundary_place(away, end, [fix(40.0, end - 2_400_000)], [HOME], after=False),
            "too long before",
        )

    def test_place_rules_choose_who_is_alerted(self):
        ruled = dict(HOME, alerts={"a" * 32: {"departure": True, "arrival": False}})
        self.assertTrue(alerts.allowed(HOME, "b" * 32, departure=True), "no rules: everyone")
        self.assertTrue(alerts.allowed(ruled, "a" * 32, departure=True))
        self.assertFalse(alerts.allowed(ruled, "a" * 32, departure=False))
        self.assertFalse(alerts.allowed(ruled, "b" * 32, departure=True))

    def test_drive_from_an_unsaved_spot_reports_where_it_was_parked(self):
        memory, found = alerts.on_fix(
            alerts.fresh_memory(), "m", 41.0, -75.0, 10, None, 1_000_000, [HOME]
        )
        self.assertEqual((memory["parked"], found), ([41.0, -75.0], []))
        memory, found = alerts.on_fix(memory, "m", 41.01, -75.0, 10, "t" * 32, 1_060_000, [HOME])
        self.assertEqual(found, [{"kind": "left", "at": [41.0, -75.0]}])
        # The same drive does not alert again.
        self.assertEqual(
            alerts.on_fix(memory, "m", 41.02, -75.0, 10, "t" * 32, 1_120_000, [HOME])[1], []
        )

    def test_short_drives_and_text(self):
        self.assertIsNone(
            alerts.on_trip_end(alerts.fresh_memory(), "m", [40.0, -74.0], 300, 10, [HOME])[1]
        )
        memory, alert = alerts.on_trip_end(
            alerts.fresh_memory(), "m", [40.0, -74.0], 16093.44, 29.06, [HOME]
        )
        self.assertEqual(memory["inside"], HOME["id"])
        self.assertEqual(
            alerts.render("Sam", alert),
            "Sam arrived at Home after a 10 mile drive, top speed 65 mph",
        )
        self.assertEqual(alerts.place_from(None), "an unsaved place")
        self.assertEqual(
            alerts._label(40.0, -74.0, (40.0, -74.0), "12", "Main St", "Town"), "12 Main St, Town"
        )
        self.assertEqual(
            alerts._label(40.0, -74.0, (40.0005, -74.0), None, "Main St", "Town"),
            "Near Main St, Town",
        )
        self.assertIsNone(
            alerts._label(40.0, -74.0, (40.01, -74.0), "12", "Main St", "Town"), "too far away"
        )

    def fix(self, memory, lat, trip=None, now=1_000_000, places=None):
        # About 0.0045 degrees of latitude is 500 m.
        return alerts.on_fix(memory, "m", lat, -74.0, 10, trip, now, places or [HOME])

    def test_leaving_a_saved_place_alerts_once_clearly_outside(self):
        home, quiet = self.fix(alerts.fresh_memory(), 40.0)
        self.assertEqual((home["inside"], quiet), (HOME["id"], []))
        edge, none = self.fix(home, 40.0011)
        self.assertEqual(
            (edge["inside"], none), (HOME["id"], []), "drift just past the edge stays quiet"
        )
        gone, left = self.fix(edge, 40.0045)
        self.assertEqual((gone["inside"], left), (None, [{"kind": "left", "place": "Home"}]))
        self.assertEqual(self.fix(gone, 40.0046)[1], [])

    def test_drive_already_running_and_leaving_home_by_car(self):
        self.assertEqual(
            self.fix(alerts.fresh_memory(), 40.05, trip="t" * 32)[1],
            [],
            "a drive already running when the server first hears of it says nothing",
        )
        home, _ = self.fix(alerts.fresh_memory(), 40.0)
        left_home, by_car = self.fix(home, 40.0045, trip="t" * 32)
        self.assertEqual(by_car, [{"kind": "left", "place": "Home"}])
        self.assertEqual(
            self.fix(left_home, 40.01, trip="d" * 32, now=1_060_000)[1],
            [],
            "no second alert right after",
        )

    def test_arrival_text_matches_the_apps(self):
        _, home = alerts.on_trip_end(
            alerts.fresh_memory(), "m", [40.0, -74.0], 11_426, 28.16, [HOME]
        )
        self.assertEqual(
            alerts.render("Android", home),
            "Android arrived at Home after a 7.1 mile drive, top speed 63 mph",
        )
        _, away = alerts.on_trip_end(
            alerts.fresh_memory(), "m", [40.5, -74.0], 64_373.8, 31.3, [HOME]
        )
        self.assertEqual(away["at"], [40.5, -74.0])
        away = dict(away, place="12 Main St, Springfield")
        self.assertEqual(
            alerts.render("Android", away),
            "Android arrived at 12 Main St, Springfield after a 40 mile drive, top speed 70 mph",
        )


class AddressLookupTests(unittest.TestCase):
    """Street addresses for alerts, from Google when a key is set and OpenStreetMap otherwise."""

    def lookup(self, handler, key=""):
        """Runs a lookup with [handler] answering every HTTP request. Returns the address and the
        hosts that were asked.
        """
        asked = []

        def answer(request):
            asked.append(request.url.host)
            return handler(request)

        real = httpx.Client
        with patch.object(
            alerts.httpx,
            "Client",
            lambda **options: real(transport=httpx.MockTransport(answer), **options),
        ):
            return alerts.lookup_address(40.0, -74.0, key), asked

    @staticmethod
    def nominatim(lat=40.0, number="12"):
        return httpx.Response(
            200,
            json={
                "lat": str(lat),
                "lon": "-74.0",
                "address": {"house_number": number, "road": "Main St", "town": "Springfield"},
            },
        )

    def test_openstreetmap_is_used_without_a_google_key(self):
        address, asked = self.lookup(lambda _: self.nominatim())
        self.assertEqual(address, "12 Main St, Springfield")
        self.assertEqual(asked, ["nominatim.openstreetmap.org"])

    def test_google_answers_when_a_key_is_set(self):
        def google(_):
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "results": [
                        {
                            "address_components": [
                                {"short_name": "7", "types": ["street_number"]},
                                {"short_name": "Elm Rd", "types": ["route"]},
                                {"short_name": "Riverton", "types": ["locality"]},
                            ],
                            "geometry": {"location": {"lat": 40.0002, "lng": -74.0}},
                        }
                    ],
                },
            )

        address, asked = self.lookup(google, key="synthetic-key")
        self.assertEqual(address, "7 Elm Rd, Riverton")
        self.assertEqual(asked, ["maps.googleapis.com"])

    def test_google_failure_falls_back_to_openstreetmap(self):
        def handler(request):
            if request.url.host == "maps.googleapis.com":
                return httpx.Response(200, json={"status": "OVER_QUERY_LIMIT"})
            return self.nominatim()

        address, asked = self.lookup(handler, key="synthetic-key")
        self.assertEqual(address, "12 Main St, Springfield")
        self.assertEqual(asked, ["maps.googleapis.com", "nominatim.openstreetmap.org"])

    def test_far_vague_or_broken_answers_give_near_or_nothing(self):
        self.assertEqual(
            self.lookup(lambda _: self.nominatim(lat=40.0005))[0], "Near 12 Main St, Springfield"
        )
        self.assertEqual(
            self.lookup(lambda _: self.nominatim(number=None))[0], "Near Main St, Springfield"
        )
        self.assertIsNone(self.lookup(lambda _: self.nominatim(lat=40.01))[0])
        self.assertIsNone(self.lookup(lambda _: httpx.Response(200, text="<html>"))[0])
        self.assertIsNone(self.lookup(lambda _: httpx.Response(200, json={"address": {}}))[0])

        def offline(request):
            raise httpx.ConnectError("offline", request=request)

        self.assertIsNone(self.lookup(offline)[0])

    def test_alert_text_reads_naturally(self):
        self.assertEqual(alerts.render("Kim", {"kind": "left", "place": "Home"}), "Kim left Home")
        self.assertEqual(
            alerts.render("Kim", {"kind": "arrived", "place": "School"}), "Kim arrived at School"
        )
        self.assertEqual(alerts.place_from("Near Main St"), "near Main St")
        self.assertEqual(alerts.place_from(None), "an unsaved place")


if __name__ == "__main__":
    unittest.main()
