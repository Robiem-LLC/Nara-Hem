package com.robiem.narahem.tracking

import com.robiem.narahem.data.location.LocalFix
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class OfflineTrackingCodecTest {
    @Test fun queuedSamplesRetainCaptureTimeAndTripTelemetry() {
        val fix = LocalFix(
            1.0, 2.0, 10f, speedMps = 5f, batteryPct = 80,
            tripMaxSpeedMps = 9f, tripDistanceMeters = 500.0, tripStartedAt = 100L,
            tripId = "a".repeat(32)
        )
        val row = OfflineTrackingCodec.location(fix, 777L)
        val payload = OfflineTrackingCodec.payload(row, "member")
        assertEquals(777L, row.getLong("captured"))
        assertEquals("member", payload.entityId)
        assertEquals(500.0, payload.data.getDouble("trip_distance_m"), 0.0)
        assertEquals(80, payload.data.getInt("battery_pct"))
        assertEquals("a".repeat(32), payload.data.getString("trip_id"))
    }

    @Test fun completedTripsKeepStableIdentityAndEndedAtForDeferredPublication() {
        val row = OfflineTrackingCodec.trip(CompletedTrip(100, 900, 12f, 700.0, 4, "b".repeat(32)))
        val first = OfflineTrackingCodec.payload(row, "member")
        val second = OfflineTrackingCodec.payload(row, "member")
        assertEquals(first.entityId, second.entityId)
        assertEquals("event", first.kind)
        assertEquals(900L, row.getLong("captured"))
        assertEquals("member", first.data.getString("account_id"))
        assertEquals(100L, first.data.getLong("started_at"))
        assertEquals("b".repeat(32), first.data.getString("trip_id"))
    }

    @Test fun tripSummaryCarriesEndpointsOutlineAndOrigin() {
        val outline = listOf(listOf(40.1, -74.1), listOf(40.2, -74.2), listOf(40.3, -74.3))
        val row = OfflineTrackingCodec.trip(
            CompletedTrip(100, 900, 12f, 700.0, 4, "b".repeat(32), outline, "Home")
        )
        val data = OfflineTrackingCodec.payload(row, "member").data
        assertEquals(40.1, data.getJSONArray("start").getDouble(0), 0.0)
        assertEquals(-74.3, data.getJSONArray("end").getDouble(1), 0.0)
        assertEquals(3, data.getJSONArray("preview").length())
        assertEquals("Home", data.getString("origin_name"))
        // Trips without an outline (e.g. queued by older builds) omit the optional fields.
        val bare = OfflineTrackingCodec.payload(
            OfflineTrackingCodec.trip(CompletedTrip(100, 900, 12f, 700.0, 4)),
            "member"
        ).data
        assertFalse(bare.has("preview") || bare.has("start") || bare.has("origin_name"))
    }
}
