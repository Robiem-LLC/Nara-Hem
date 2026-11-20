package com.robiem.narahem.ui

import java.util.Locale
import java.util.TimeZone
import org.junit.Assert.assertEquals
import org.junit.Test

class ZoneTimesTest {
    private val newYork = TimeZone.getTimeZone("America/New_York")

    // 2026-11-20 01:00 UTC: 8:00 PM in New York, 5:00 PM in Los Angeles.
    private val evening = 1_795_136_400_000L

    private fun format(zone: String?, withDate: Boolean = false) =
        ZoneTimes.format(evening, zone, withDate, newYork, Locale.US)

    @Test fun anotherZoneShowsBothTimesTheViewersFirst() {
        assertEquals("8:00 PM EST / 5:00 PM PST", format("America/Los_Angeles").replace(' ', ' '))
    }

    @Test fun theSameClockOrNoZoneShowsOneTime() {
        assertEquals("8:00 PM", format("America/New_York").replace(' ', ' '))
        assertEquals("8:00 PM", format("America/Toronto").replace(' ', ' '))
        assertEquals("8:00 PM", format(null).replace(' ', ' '))
        assertEquals("8:00 PM", format("Not/AZone").replace(' ', ' '))
    }

    @Test fun datesAreIncludedWhenAsked() {
        val both = format("Asia/Tokyo", withDate = true).replace(' ', ' ')
        assertEquals("11/19/26, 8:00 PM EST / 11/20/26, 10:00 AM JST", both)
    }
}
