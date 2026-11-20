package com.robiem.narahem.data.household

/**
 * A household member as shown on the map: latest shared location, photo, battery and current trip
 * statistics.
 */
data class HouseholdPerson(
    val id: String,
    val name: String,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val accuracy: Double? = null,
    val capturedAt: Long = 0,
    val photo: String? = null,
    val speedMps: Double? = null,
    val batteryPct: Int? = null,
    val charging: Boolean? = null,
    val tripMaxSpeedMps: Double? = null,
    val tripDistanceMeters: Double? = null,
    val recentTripMaxSpeedMps: Double? = null,
    val tripId: String? = null,
    /**
     * Since when this member has stayed put, and when any of their phones last reached the server.
     */
    val stillSince: Long? = null,
    val lastContact: Long? = null,
    /** The time zone the member's phone reported with this location, if it sent one. */
    val timeZone: String? = null
)
