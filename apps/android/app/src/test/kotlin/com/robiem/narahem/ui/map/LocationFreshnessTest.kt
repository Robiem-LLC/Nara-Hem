package com.robiem.narahem.ui.map

import com.robiem.narahem.data.household.HouseholdPerson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LocationFreshnessTest {
    private val now = 100_000_000L

    private fun person(
        minutesAgo: Long,
        still: Long? = null,
        battery: Int? = 80,
        contact: Long? = null
    ) = HouseholdPerson(
        "a", "Sam", 40.0, -74.0, 10.0, now - minutesAgo * 60_000, batteryPct = battery,
        charging = false, stillSince = still, lastContact = contact
    )

    @Test fun recentParkedStaleAndPossiblyOff() {
        assertEquals("", LocationFreshness.of(person(5), now).suffix)
        val parked = LocationFreshness.of(person(40, still = now - 90 * 60_000), now)
        assertTrue(parked.suffix.startsWith(" · since "))
        assertFalse(parked.alarming)
        assertTrue(LocationFreshness.of(person(40), now).alarming)
        assertEquals(" · stale", LocationFreshness.of(person(40), now).suffix)
        val off = LocationFreshness.of(person(40, still = now - 90 * 60_000, battery = 4), now)
        assertTrue(off.alarming)
        assertEquals(" · may be off", off.suffix)
        // Low battery but the phone was heard from recently: just parked.
        assertFalse(
            LocationFreshness.of(
                person(40, still = now - 90 * 60_000, battery = 4, contact = now - 60_000),
                now
            ).alarming
        )
    }
}
