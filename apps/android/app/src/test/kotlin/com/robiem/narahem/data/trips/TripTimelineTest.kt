package com.robiem.narahem.data.trips

import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.HouseholdTrip
import com.robiem.narahem.data.household.PlaceMatching
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TripTimelineTest {
    private fun point(
        time: Long,
        lat: Double = 40.0,
        device: String = "phone",
        accuracy: Double = 5.0
    ) = TripPoint("$time:$device", "member", device, time, lat, -74.0, accuracy, 0.0)

    @Test fun delayedOrderIsSortedAndGapsAndJumpsAreBroken() {
        assertEquals(1, TripTimeline.route(listOf(point(60000, 40.001), point(0))).size)
        assertEquals(2, TripTimeline.route(listOf(point(0), point(180000, 40.001))).size)
        assertEquals(
            2,
            TripTimeline.route(listOf(point(0), point(15000, 41.0), point(30000, 40.001))).size
        )
        assertEquals(
            2,
            TripTimeline.route(listOf(point(0), point(1000, accuracy = 100.0), point(2000))).size
        )
        assertEquals(2, TripTimeline.route(listOf(point(0), point(1000, device = "other"))).size)
    }

    @Test fun rejectedSpikeDoesNotDistortMapBounds() {
        val route = TripTimeline.route(listOf(point(0), point(15000, 41.0), point(30000, 40.001)))
        assertEquals(2, route.flatten().size)
    }

    @Test fun stopsRequireObservedStationaryTimeFromOneDevice() {
        val points = listOf(point(0), point(120000), point(240000))
        assertEquals(1, TripTimeline.stops(points, emptyList()).size)
        assertEquals(240000L, TripTimeline.stops(points, emptyList()).first().endedAt)
        assertTrue(TripTimeline.stops(listOf(point(0), point(600000)), emptyList()).isEmpty())
        assertTrue(
            TripTimeline.stops(
                listOf(point(0), point(240000, device = "other")),
                emptyList()
            ).isEmpty()
        )
        val trip = HouseholdTrip("trip", "member", 0, 240000, 100.0, 10.0, 3, "phone")
        assertTrue(TripTimeline.stops(points, listOf(trip)).isEmpty())
    }

    @Test fun tripIdsMatchDeferredSamplesWithoutLosingOlderData() {
        val trip =
            HouseholdTrip("event", "member", 0, 30000, 100.0, 10.0, 3, "phone", "b".repeat(32))
        val legacy = point(0)
        val linked = point(15000).copy(tripId = "b".repeat(32))
        val foreign = point(20000).copy(tripId = "a".repeat(32))
        assertEquals(
            listOf(legacy, linked),
            TripTimeline.forTrip(trip, listOf(linked, foreign, legacy))
        )
    }

    @Test fun savedHomeStayConsolidatesDriftAndMarksObservationGaps() {
        val home = HouseholdPlace("home", "Home", 40.0, -74.0, 100.0)
        val points = listOf(point(0), point(240000, 40.001), point(720000, 40.0001), point(960000))
        val stays = TripTimeline.stops(points, emptyList(), listOf(home))
        assertEquals(1, stays.size)
        assertEquals(480000L, stays.first().gapMillis)
        assertEquals("home", PlaceMatching.match(40.001, -74.0, listOf(home), 30.0)!!.id)
        val trip = HouseholdTrip("noise", "member", 0, 240000, 500.0, 20.0, 3, "phone")
        assertTrue(
            TripTimeline.isStationary(trip, listOf(point(0), point(120000, 40.0001), point(240000)))
        )
        assertFalse(
            TripTimeline.isStationary(trip, listOf(point(0), point(120000, 40.01), point(240000)))
        )
    }

    @Test fun tinyHomeMotionIsNotACompletedTripInTheTimeline() {
        val home = HouseholdPlace("home", "Home", 40.0, -74.0, 100.0)
        val tiny = HouseholdTrip("trash", "member", 0, 32000, 16.0, 4.47, 184, "phone")
        assertTrue(
            TripTimeline.isInconsequential(
                tiny,
                listOf(point(0), point(32000, 40.00009)),
                listOf(home)
            )
        )
        assertFalse(TripTimeline.isInconsequential(tiny, listOf(point(0), point(32000, 40.00009))))
        assertFalse(
            TripTimeline.isInconsequential(
                tiny,
                listOf(point(0), point(16000, 40.002), point(32000)),
                listOf(home)
            )
        )
        assertFalse(
            TripTimeline.isInconsequential(
                tiny.copy(endedAt = 7 * 86400000L),
                listOf(point(0), point(32000)),
                listOf(home)
            )
        )
    }

    @Test fun historicalHomeFragmentsMergeAcrossDevicesWithoutHidingTripsOrDepartures() {
        val home = HouseholdPlace("home", "Home", 40.0, -74.0, 100.0)
        val samples = listOf(
            point(0),
            point(240000),
            point(540000, device = "other"),
            point(780000, device = "other"),
            point(1320000, device = "third"),
            point(1560000, device = "third")
        )
        val result = TripTimeline.stops(samples, emptyList(), listOf(home))
        assertEquals(1, result.size)
        assertEquals(840000L, result.single().gapMillis)
        val genuine = HouseholdTrip("outing", "member", 270000, 480000, 500.0, 5.0, 8, "phone")
        assertEquals(2, TripTimeline.stops(samples, listOf(genuine), listOf(home)).size)
        val left = point(380000, 40.02)
        assertEquals(2, TripTimeline.stops(samples + left, emptyList(), listOf(home)).size)
        val distant = listOf(point(0), point(240000), point(3840000), point(4080000))
        assertEquals(2, TripTimeline.stops(distant, emptyList(), listOf(home)).size)
    }
}
