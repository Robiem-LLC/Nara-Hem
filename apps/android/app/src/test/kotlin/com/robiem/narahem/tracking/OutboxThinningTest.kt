package com.robiem.narahem.tracking

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OutboxThinningTest {
    @Test fun dropsTheMostCrowdedFixAndNeverATripSummaryOrTheEnds() {
        val kinds = listOf("location", "location", "trip", "location", "location", "location")
        val captured = listOf(0L, 4_000L, 5_000L, 8_000L, 60_000L, 64_000L)
        // Row 1 (gap 0..5s) is densest; the trip row and both ends are protected.
        assertEquals(1, OutboxThinning.victim(kinds, captured))
        assertNull(OutboxThinning.victim(listOf("location", "location"), listOf(0L, 1L)))
        assertNull(
            OutboxThinning.victim(listOf("location", "trip", "location"), listOf(0L, 1L, 2L))
        )
    }

    @Test fun eightHourOfflineDriveKeepsTheWholeJourneyAndEveryTrip() {
        val kinds = mutableListOf<String>()
        val captured = mutableListOf<Long>()
        var dropped = 0
        // One fix every 4 s for 8 hours, with a trip summary every 2 hours.
        for (step in 0 until 7_200) {
            val at = step * 4_000L
            kinds += "location"
            captured += at
            if (step % 1_800 == 1_799) {
                kinds += "trip"
                captured += at
            }
            while (kinds.size > 2_000) {
                val index = OutboxThinning.victim(kinds, captured)!!
                kinds.removeAt(index)
                captured.removeAt(index)
                dropped++
            }
        }
        assertEquals(4, kinds.count { it == "trip" })
        assertEquals(0L, captured.first())
        assertEquals(7_199 * 4_000L, captured.last())
        // No hole longer than a minute anywhere in the drive.
        val longestGap = captured.zipWithNext { a, b -> b - a }.maxOrNull()!!
        assertTrue("longest gap $longestGap ms", longestGap <= 60_000L)
        assertTrue(dropped > 0)
    }
}
