package com.robiem.narahem.tracking

/**
 * Summary of a finished trip: times, GPS-measured distance and top speed, endpoints and a route
 * outline.
 */
data class CompletedTrip(
    val startedAt: Long,
    val endedAt: Long,
    val maxSpeedMps: Float,
    val distanceMeters: Double,
    val samples: Int,
    val tripId: String? = null,
    /**
     * Bounded [lat, lon] outline of moving fixes for list thumbnails; first/last are the endpoints.
     */
    val outline: List<List<Double>> = emptyList(),
    val originName: String? = null
)
