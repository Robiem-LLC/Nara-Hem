package com.robiem.narahem.ui.places

import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.PlaceMatching
import kotlin.math.PI
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Geometry helpers for saved places. Coordinates are decrypted on the device; the server never sees
 * them.
 */
object PlaceGeometry {
    /** Returns the great-circle distance between two points in metres. */
    fun distanceMeters(aLat: Double, aLon: Double, bLat: Double, bLon: Double): Double {
        val r = 6_371_000.0
        val lat = Math.toRadians(bLat - aLat)
        val lon = Math.toRadians(bLon - aLon)
        val h =
            sin(lat / 2).pow(2) +
                cos(Math.toRadians(aLat)) * cos(Math.toRadians(bLat)) * sin(lon / 2).pow(2)
        return 2 * r * asin(sqrt(h.coerceIn(0.0, 1.0)))
    }

    /** Returns the saved place containing the point, or null. */
    fun matchingPlace(
        lat: Double,
        lon: Double,
        places: List<HouseholdPlace>,
        accuracy: Double = 25.0
    ): HouseholdPlace? =
        com.robiem.narahem.data.household.PlaceMatching.match(lat, lon, places, accuracy)

    /** Returns points around a place's boundary for drawing it as a polygon. */
    fun circle(
        lat: Double,
        lon: Double,
        meters: Double,
        samples: Int = 64
    ): List<Pair<Double, Double>> {
        val latRadius = meters / 111_320.0
        val lonRadius = meters / (111_320.0 * cos(Math.toRadians(lat)).coerceAtLeast(0.01))
        return (0..samples).map { step ->
            val direction = 2 * PI * step / samples
            Pair(
                (lat + latRadius * cos(direction)).coerceIn(-85.0, 85.0),
                (lon + lonRadius * sin(direction)).coerceIn(-180.0, 180.0)
            )
        }
    }

    /** Returns the name of the saved place containing the point, or the coordinates. */
    fun label(lat: Double, lon: Double, places: List<HouseholdPlace>): String =
        matchingPlace(lat, lon, places)?.name ?: "%.5f, %.5f".format(lat, lon)
}
