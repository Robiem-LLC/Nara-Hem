package com.robiem.narahem.tracking

/** Trip state after processing a fix, including the completed trip if the fix ended one. */
data class TripProgress(
    val active: Boolean,
    val startedAt: Long? = null,
    val maxSpeedMps: Float? = null,
    val distanceMeters: Double? = null,
    val recentMaxSpeedMps: Float? = null,
    val completed: CompletedTrip? = null,
    val tripId: String? = null
)
