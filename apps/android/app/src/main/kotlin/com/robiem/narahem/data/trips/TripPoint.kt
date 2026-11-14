package com.robiem.narahem.data.trips

/** A single GPS point from a member's location history. */
data class TripPoint(
    val id: String,
    val accountId: String,
    val deviceId: String,
    val capturedAt: Long,
    val latitude: Double,
    val longitude: Double,
    val accuracy: Double,
    val speedMps: Double? = null,
    val tripId: String? = null,
    val normalized: Boolean = false
)
