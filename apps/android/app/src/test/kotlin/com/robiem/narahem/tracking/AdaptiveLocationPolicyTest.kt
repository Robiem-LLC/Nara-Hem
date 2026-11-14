package com.robiem.narahem.tracking

import com.robiem.narahem.data.location.LocalFix
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AdaptiveLocationPolicyTest {
    @Test fun stationaryFixesReducePowerButPeriodicGpsAndMovementRestoreAccuracy() {
        val p = AdaptiveLocationPolicy()
        val now = 1_000_000L
        p.recordHighAccuracy(now)
        repeat(3) { p.observe(LocalFix(1.0, 2.0, 10f, speedMps = 0f)) }
        assertTrue(p.preferLowPower(now + 20 * 60_000L))
        assertFalse("a precise GPS fix about every half hour", p.preferLowPower(now + 30 * 60_000L))
        assertEquals(15 * 60_000L, p.observe(LocalFix(1.0, 2.0, 10f, speedMps = 0f)))
        assertEquals(9_000L, p.observe(LocalFix(1.002, 2.0, 10f)))
        assertFalse(p.preferLowPower(now + 120_000))
    }

    @Test fun credibleMovementWakesFromStationaryButJitterOrStaleFixDoesNot() {
        val p = AdaptiveLocationPolicy()
        val now = 1_000_000L
        val home = LocalFix(40.0, -74.0, 10f, speedMps = 0f, capturedAtMillis = now - 15000L)
        val drive = LocalFix(40.00005, -74.0, 10f, speedMps = 18f, capturedAtMillis = now)
        assertTrue(p.movementWake(home, drive, now))
        assertTrue(p.movementWake(home, LocalFix(40.001, -74.0, 10f, capturedAtMillis = now), now))
        assertFalse(
            p.movementWake(home, LocalFix(40.001, -74.0, 150f, capturedAtMillis = now), now)
        )
        assertFalse(
            p.movementWake(home, LocalFix(40.001, -74.0, 10f, capturedAtMillis = now - 90000), now)
        )
        assertFalse(
            p.movementWake(
                home,
                LocalFix(40.00001, -74.0, 10f, speedMps = 0f, capturedAtMillis = now),
                now
            )
        )
    }

    @Test fun poorAccuracyCannotBeMistakenForStationaryAndTravelStaysFrequent() {
        val p = AdaptiveLocationPolicy()
        p.recordHighAccuracy(1_000_000)
        repeat(4) { p.observe(LocalFix(1.0, 2.0, 500f)) }
        assertFalse(p.preferLowPower(1_010_000))
        assertEquals(4_000L, p.observe(LocalFix(1.0, 2.0, 10f, speedMps = 20f)))
        assertEquals(15_000L, p.observe(LocalFix(1.0, 2.0, 10f, speedMps = 1f)))
    }
}
