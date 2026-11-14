package com.robiem.narahem.data.trips

/** A period between trips when a member stayed in one place. */
data class TripStop(
    val id: String,
    val accountId: String,
    val deviceId: String,
    val startedAt: Long,
    val endedAt: Long,
    val latitude: Double,
    val longitude: Double,
    val gapMillis: Long = 0
)
