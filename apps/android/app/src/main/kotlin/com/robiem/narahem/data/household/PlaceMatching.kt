package com.robiem.narahem.data.household
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/** Matches coordinates to saved places. */
object PlaceMatching {
    /** Returns the great-circle distance between two points in metres. */
    fun distance(aLat: Double, aLon: Double, bLat: Double, bLon: Double): Double {
        val r = Math.PI / 180
        val h = sin(
            (bLat - aLat) * r / 2
        ).pow(2) + cos(aLat * r) * cos(bLat * r) * sin((bLon - aLon) * r / 2).pow(2)
        return 12742000 * asin(sqrt(h.coerceIn(0.0, 1.0)))
    }

    /** Returns the saved place containing the point, allowing for its accuracy, or null. */
    fun match(
        lat: Double,
        lon: Double,
        places: List<HouseholdPlace>,
        accuracy: Double = 25.0
    ): HouseholdPlace? {
        val tolerance = accuracy.takeIf { it.isFinite() }?.coerceIn(15.0, 50.0) ?: 25.0
        return places.map { it to distance(lat, lon, it.latitude, it.longitude) }
            .filter { it.second <= it.first.radius + tolerance }
            .sortedWith(
                compareBy<Pair<HouseholdPlace, Double>> {
                    it.second > it.first.radius
                }.thenBy { it.second }
            )
            .firstOrNull()?.first
    }
}
