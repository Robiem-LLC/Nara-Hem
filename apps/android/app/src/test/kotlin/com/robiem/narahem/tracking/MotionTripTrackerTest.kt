package com.robiem.narahem.tracking

import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.location.LocalFix
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MotionTripTrackerTest {
    private fun fix(lat: Double, speed: Float) =
        LocalFix(latitude = lat, longitude = -74.4, accuracy = 8f, speedMps = speed)

    @Test fun recognizedTravelRequiresTwoSamplesAndEndsAfterThreeMinutesStopped() {
        val trips = MotionTripTracker()
        assertFalse(trips.observe(fix(40.0, 12f), 1_000).active)
        val underway = trips.observe(fix(40.001, 15f), 16_000)
        assertTrue(underway.active)
        assertEquals(15f, underway.maxSpeedMps!!)
        assertTrue(underway.distanceMeters!! > 100.0)
        val following = trips.observe(fix(40.002, 20f), 31_000)
        assertTrue(following.distanceMeters!! > 100.0)
        val finished = trips.observe(fix(40.002, 0f), 212_000)
        assertFalse(finished.active)
        assertEquals(underway.tripId, finished.completed!!.tripId)
        assertNotNull(finished.completed!!.tripId)
        assertEquals(20f, finished.completed!!.maxSpeedMps)
        assertEquals(3, finished.completed!!.samples)
        assertEquals(20f, finished.recentMaxSpeedMps!!)
    }

    @Test fun idleTimerClosesTripWithoutWaitingForAnotherGpsCallback() {
        val tracker = MotionTripTracker()
        tracker.observe(fix(40.0, 15f), 1_000)
        tracker.observe(fix(40.001, 16f), 16_000)
        assertNull(tracker.completeIfIdle(195_999))
        val completed = tracker.completeIfIdle(196_000)
        assertNotNull(completed)
        assertTrue(completed!!.distanceMeters > 100.0)
        assertEquals(16_000L, completed.endedAt)
        assertNull(tracker.completeIfIdle(400_000))
    }

    @Test fun movementInsideSavedPlaceNeverBecomesTrip() {
        val home = com.robiem.narahem.data.household.HouseholdPlace(
            "home",
            "Home",
            40.0,
            -74.4,
            200.0
        )
        val tracker = MotionTripTracker()
        tracker.observe(fix(40.0, 12f), 1000, listOf(home))
        tracker.observe(fix(40.001, 12f), 16000, listOf(home))
        assertNull(tracker.completeIfIdle(196000))
        val departed = MotionTripTracker()
        departed.observe(fix(40.0, 12f), 1000, listOf(home))
        departed.observe(fix(40.001, 12f), 16000, listOf(home))
        departed.observe(fix(40.003, 14f), 31000, listOf(home))
        assertNotNull(departed.completeIfIdle(211000))
    }

    @Test fun shortTripPreservesFirstSegmentAndPeak() {
        val trips = MotionTripTracker()
        trips.observe(fix(40.0, 20f), 1_000)
        trips.observe(fix(40.001, 12f), 16_000)
        val trip = trips.observe(fix(40.001, 0f), 196_000).completed!!
        assertEquals(2, trip.samples)
        assertEquals(16_000L, trip.endedAt)
        assertTrue(trip.distanceMeters > 100.0)
        assertEquals(20f, trip.maxSpeedMps)
    }

    @Test fun walkingAtOrdinarySpeedCanBeginARealTrip() {
        val tracker = MotionTripTracker()
        assertFalse(tracker.observe(fix(40.0, 1.4f), 1_000).active)
        val progress = tracker.observe(fix(40.0005, 1.4f), 46_000)
        assertTrue(progress.active)
        assertNotNull(progress.tripId)
    }

    @Test fun temporaryStayRejectsEarlyIndoorGpsDrift() {
        val tracker = MotionTripTracker()
        tracker.observe(fix(40.0, 0f), 1_000)
        tracker.observe(fix(40.0, 0f), 121_000)
        tracker.observe(fix(40.0, 0f), 201_000)
        assertFalse(tracker.observe(fix(40.0001, 8f), 215_000).active)
        assertFalse(tracker.observe(fix(40.0006, 8f), 230_000).active)
        assertTrue(tracker.observe(fix(40.0010, 8f), 245_000).active)
    }

    @Test fun briefAccelerationDoesNotStartTripAndGpsSpikesAreDiscarded() {
        val trips = MotionTripTracker()
        assertFalse(trips.observe(fix(40.0, 3f), 0).active)
        assertFalse(trips.observe(fix(40.0, 0f), 5_000).active)
        assertFalse(trips.observe(fix(40.0, 100f), 20_000).active)
        assertFalse(trips.observe(fix(40.0, 0f), 40_000).active)
    }

    @Test fun speedSpikesWithoutDisplacementDoNotStartTrips() {
        val trips = MotionTripTracker()
        repeat(8) { index ->
            assertFalse(
                trips.observe(fix(40.0 + (index % 2) * 0.00004, 12f), 1000L + index * 15000).active
            )
        }
        assertNull(trips.observe(fix(40.0, 0f), 400000).completed)
    }

    @Test fun unconfirmedMotionDoesNotRetainAnHoursOldDeparture() {
        val trips = MotionTripTracker()
        repeat(50) { trips.observe(fix(40.0, 12f), 1000L + it * 15000) }
        val underway = trips.observe(fix(40.001, 12f), 751000)
        assertTrue(underway.active)
        assertTrue(underway.startedAt!! >= 631000L)
    }

    @Test fun completedTripCarriesBoundedRoundedOutline() {
        val tracker = MotionTripTracker()
        var now = 1_000L
        var lat = 40.0
        var result: com.robiem.narahem.tracking.CompletedTrip? = null
        // 400 moving fixes about 22 m apart: far more than the outline keeps.
        repeat(400) {
            tracker.observe(fix(lat, 15f), now)
            now += 1_500
            lat += 0.0002
        }
        result = tracker.completeIfIdle(now + 200_000)
        val outline = result!!.outline
        assertTrue(outline.size in 2..120)
        assertEquals(40.0, outline.first()[0], 0.0)
        assertEquals(lat - 0.0002, outline.last()[0], 0.00001)
        outline.flatten().forEach { assertEquals(it, Math.round(it * 100_000.0) / 100_000.0, 0.0) }
        // The next trip starts with an empty outline.
        tracker.observe(fix(41.0, 15f), now + 300_000)
        tracker.observe(fix(41.001, 15f), now + 315_000)
        assertEquals(41.0, tracker.completeIfIdle(now + 600_000)!!.outline.first()[0], 0.0)
    }

    @Test fun tripStartsWhereThePhoneWasLastStill() {
        val tracker = MotionTripTracker()
        tracker.observe(fix(40.0, 0f), 1_000)
        tracker.observe(fix(40.0, 0f), 121_000)
        tracker.observe(fix(40.0, 0f), 201_000)
        tracker.observe(fix(40.0010, 15f), 215_000)
        assertTrue(tracker.observe(fix(40.0020, 15f), 230_000).active)
        val trip = tracker.completeIfIdle(230_000 + 180_000)!!
        assertEquals(40.0, trip.outline.first()[0], 0.0)
        assertEquals(40.002, trip.outline.last()[0], 0.0)
        // The ~111 m from the parked spot to the first moving fix counts as driven.
        assertTrue(trip.distanceMeters > 200.0)
    }

    @Test fun stillFixFarFromTheFirstMovingFixIsNotUsedAsTheStart() {
        val tracker = MotionTripTracker()
        tracker.observe(fix(40.0, 0f), 1_000)
        tracker.observe(fix(40.05, 25f), 400_000)
        tracker.observe(fix(40.0515, 25f), 415_000)
        val trip = tracker.completeIfIdle(415_000 + 180_000)!!
        assertEquals(40.05, trip.outline.first()[0], 0.0)
        assertTrue(trip.distanceMeters < 200.0)
    }

    @Test fun leavingASavedPlaceStartsAtThePlaceWhenNoStillFixWasKept() {
        val home = com.robiem.narahem.data.household.HouseholdPlace(
            "home",
            "Home",
            40.0,
            -74.4,
            100.0
        )
        val tracker = MotionTripTracker()
        tracker.observe(fix(40.0008, 12f), 1_000, listOf(home))
        tracker.observe(fix(40.0020, 12f), 16_000, listOf(home))
        val trip = tracker.completeIfIdle(16_000 + 180_000)!!
        assertEquals("Home", trip.originName)
        assertEquals(listOf(40.0, -74.4), trip.outline.first())
    }

    @Test fun nextTripStartsWhereThePreviousTripStopped() {
        val tracker = MotionTripTracker()
        tracker.observe(fix(40.0, 15f), 1_000)
        tracker.observe(fix(40.001, 15f), 16_000)
        assertNotNull(tracker.completeIfIdle(16_000 + 180_000))
        // GPS only notices the next departure ~200 m down the road.
        tracker.observe(fix(40.003, 15f), 600_000)
        tracker.observe(fix(40.004, 15f), 615_000)
        val next = tracker.completeIfIdle(615_000 + 180_000)!!
        assertEquals(40.001, next.outline.first()[0], 0.0)
    }

    @Test fun longWindingDriveKeepsItsShapeFromStartToFinish() {
        val tracker = MotionTripTracker()
        // About 130 km of road curving side to side, one fix every 4 s.
        val route = (0 until 1_200).map { i ->
            40.0 + i * 0.001 to
                -74.4 + 0.01 * kotlin.math.sin(i / 20.0)
        }
        route.forEachIndexed { i, (lat, lon) ->
            tracker.observe(LocalFix(lat, lon, 8f, speedMps = 28f), 1_000L + i * 4_000L)
        }
        val outline = tracker.completeIfIdle(1_000L + 1_200 * 4_000L + 180_000)!!.outline
        assertTrue(outline.size <= 120)
        // Every recorded fix, including the first hour, lies close to the saved outline.
        val worst = route.maxOf { (lat, lon) -> offRoute(lat, lon, outline) }
        assertTrue("worst deviation ${worst.toInt()} m", worst < 150.0)
    }

    private fun offRoute(lat: Double, lon: Double, outline: List<List<Double>>): Double {
        val scale = 111_320.0 * kotlin.math.cos(Math.toRadians(lat))
        fun xy(p: List<Double>) = (p[1] - lon) * scale to (p[0] - lat) * 110_574.0
        return outline.zipWithNext().minOf { (a, b) ->
            val (ax, ay) = xy(a)
            val (bx, by) = xy(b)
            val dx = bx - ax
            val dy = by - ay
            val t = if (dx == 0.0 && dy == 0.0) {
                0.0
            } else {
                ((-ax * dx - ay * dy) / (dx * dx + dy * dy)).coerceIn(0.0, 1.0)
            }
            kotlin.math.hypot(ax + t * dx, ay + t * dy)
        }
    }
}
