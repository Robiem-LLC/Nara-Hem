package com.robiem.narahem.ui

import java.text.DateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Times for someone who may be in another time zone. Phones send their zone with each location;
 * when it gives a different clock from this phone's at that moment, both are shown, this phone's
 * first: "8:00 PM EST / 10:00 PM PST". Without a zone, or in the same one, it's the plain local
 * time. Same rule as the iPhone and web apps.
 */
object ZoneTimes {
    /** Formats [at] as a time of day, or with its date when [withDate] is set. */
    fun format(
        at: Long,
        zone: String?,
        withDate: Boolean = false,
        viewer: TimeZone = TimeZone.getDefault(),
        locale: Locale = Locale.getDefault()
    ): String {
        val theirs = known(zone)
        val local = text(at, viewer, withDate, locale)
        if (theirs == null || text(at, theirs, true, locale) == text(at, viewer, true, locale)) {
            return local
        }
        return "$local ${short(at, viewer, locale)} / " +
            "${text(at, theirs, withDate, locale)} ${short(at, theirs, locale)}"
    }

    /** Returns the zone if this phone knows it, otherwise null. */
    fun known(zone: String?): TimeZone? {
        if (zone.isNullOrBlank() || zone.length > 64) return null
        val found = TimeZone.getTimeZone(zone)
        return found.takeIf { it.id == zone }
    }

    /** Formats [at] in [zone]. */
    private fun text(at: Long, zone: TimeZone, withDate: Boolean, locale: Locale): String {
        val format = if (withDate) {
            DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT, locale)
        } else {
            DateFormat.getTimeInstance(DateFormat.SHORT, locale)
        }
        format.timeZone = zone
        return format.format(Date(at))
    }

    /** Returns the zone's short name at [at], such as "EST" or "GMT+01:00". */
    private fun short(at: Long, zone: TimeZone, locale: Locale) =
        zone.getDisplayName(zone.inDaylightTime(Date(at)), TimeZone.SHORT, locale)
}
