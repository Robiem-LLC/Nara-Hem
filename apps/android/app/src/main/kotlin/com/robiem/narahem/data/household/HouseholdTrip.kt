package com.robiem.narahem.data.household

/**
 * A completed trip as shown in the trips list: times, distance, top speed, route source and an
 * outline for the preview.
 */
data class HouseholdTrip(
    val id: String,
    val accountId: String,
    val startedAt: Long,
    val endedAt: Long,
    val distanceMeters: Double,
    val maxSpeedMps: Double,
    val samples: Int,
    val deviceId: String = "",
    val tripId: String? = null,
    val normalized: Boolean = false,
    val matched: Boolean = false,
    val processing: Boolean = false,
    val partial: Boolean = false,
    /**
     * Bounded [lat, lon] outline from the signed trip summary, for showing a route before GPS
     * loads.
     */
    val preview: List<List<Double>> = emptyList(),
    /** Where the trip started and ended, as the server named them (a saved place or an address). */
    val startLabel: String? = null,
    val endLabel: String? = null,
    /** The time zone the member's phone reported with the trip, if it sent one. */
    val timeZone: String? = null
)
