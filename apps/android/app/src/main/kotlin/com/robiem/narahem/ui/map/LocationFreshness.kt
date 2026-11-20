package com.robiem.narahem.ui.map

import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.ui.ZoneTimes
import java.text.DateFormat
import java.util.Date

/**
 * Describes how current a member's location is. Parked phones report about every 15 minutes, so a
 * location that stayed the same reads "since 10:34" rather than stale. Same rules as the iPhone and
 * web apps.
 */
object LocationFreshness {
    /** Age after which a location is flagged as possibly out of date. */
    const val STALE_MS = 20 * 60_000L

    /** Time without contact after which the phone may be off. */
    private const val OFF_MS = 30 * 60_000L

    /** Returns the freshness text and warning state for a member's location. */
    fun of(person: HouseholdPerson, now: Long = System.currentTimeMillis()): Status {
        if (now - person.capturedAt <= STALE_MS) return Status("", false, null)
        val heard = maxOf(person.capturedAt, person.lastContact ?: 0L)
        val battery = person.batteryPct
        if (battery != null && battery <= 10 && person.charging != true && now - heard > OFF_MS) {
            return Status(
                " · may be off",
                true,
                "May be off: its battery was $battery% at " +
                    "${time(person.capturedAt, now, person.timeZone)}."
            )
        }
        val since = person.stillSince ?: return Status(
            " · stale",
            true,
            "Last reported location is over 20 minutes old. Verify before traveling."
        )
        val contact = person.lastContact?.takeIf { it > person.capturedAt + 60_000L }
        val zone = person.timeZone
        return Status(
            " · since ${time(since, now, zone)}",
            false,
            "Stayed here since ${time(since, now, zone)}." +
                (contact?.let { " Phone last heard from at ${time(it, now, zone)}." } ?: "")
        )
    }

    /** Formats a time, adding the date if it isn't today and the member's own time if it differs. */
    private fun time(at: Long, now: Long, zone: String?): String {
        val sameDay =
            DateFormat.getDateInstance().format(Date(at)) ==
                DateFormat.getDateInstance().format(Date(now))
        return ZoneTimes.format(at, zone, withDate = !sameDay)
    }

    /**
     * [suffix] is shown after the place name; [alarming] marks a location that may be wrong; [note]
     * is extra detail.
     */
    data class Status(val suffix: String, val alarming: Boolean, val note: String?)
}
