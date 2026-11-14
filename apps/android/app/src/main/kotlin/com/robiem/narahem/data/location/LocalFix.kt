package com.robiem.narahem.data.location

/**
 * A location reading from this phone, with battery state and the trip statistics sent along with
 * it.
 */
data class LocalFix(
    val latitude: Double,
    val longitude: Double,
    val accuracy: Float,
    val speedMps: Float? = null,
    val batteryPct: Int? = null,
    val charging: Boolean? = null,
    val tripMaxSpeedMps: Float? = null,
    val tripDistanceMeters: Double? = null,
    val tripStartedAt: Long? = null,
    val recentTripMaxSpeedMps: Float? = null,
    val tripId: String? = null,
    val capturedAtMillis: Long? = null,
    val provider: String? = null,
    val bearingDeg: Float? = null
)
