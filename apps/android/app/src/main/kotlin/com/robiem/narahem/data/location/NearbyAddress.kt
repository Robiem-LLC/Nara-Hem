package com.robiem.narahem.data.location

import android.content.Context
import android.location.Address
import android.location.Geocoder
import com.robiem.narahem.ui.places.PlaceGeometry
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap

/**
 * Reverse geocoding with an in-memory cache. Failed lookups are cached briefly so they can be
 * retried later.
 */
object NearbyAddress {
    private val cache = ConcurrentHashMap<String, Entry>()

    /** Returns a short street address near the point using Android's Geocoder, or null. */
    @Suppress("DEPRECATION")
    fun lookup(
        context: Context,
        latitude: Double,
        longitude: Double,
        accuracy: Double = 25.0
    ): String? {
        val key = String.format(
            Locale.ROOT,
            "%.4f,%.4f:%d",
            latitude,
            longitude,
            (accuracy / 25).toInt()
        )
        val now = System.currentTimeMillis()
        cache[key]?.takeIf { it.expires > now }?.let { return it.text }
        val text = try {
            val found = Geocoder(context, Locale.getDefault())
                .getFromLocation(latitude, longitude, 1)?.firstOrNull()
            describe(found, latitude, longitude, accuracy)
        } catch (_: Exception) {
            null
        }
        if (cache.size > 2000) cache.clear()
        cache[key] = Entry(now + if (text == null) 30000 else 86400000, text)
        return text
    }

    /**
     * Words a geocoder result as "12 High Street, Oxford, England". Returns null if it is too far
     * from the point, and adds "Near " unless it is close and has a house number.
     */
    internal fun describe(
        found: Address?,
        latitude: Double,
        longitude: Double,
        accuracy: Double
    ): String? {
        if (found == null || !found.hasLatitude() || !found.hasLongitude()) return null
        val distance =
            PlaceGeometry.distanceMeters(latitude, longitude, found.latitude, found.longitude)
        if (distance > maxOf(100.0, minOf(250.0, accuracy.coerceAtLeast(0.0) * 2))) return null
        val street = listOfNotNull(
            found.subThoroughfare?.takeIf { it.isNotBlank() },
            found.thoroughfare?.takeIf { it.isNotBlank() }
        ).joinToString(" ")
        val label = if (street.isNotBlank()) {
            listOfNotNull(street, found.locality, found.adminArea).filter { it.isNotBlank() }
                .joinToString(", ")
        } else {
            found.getAddressLine(0).orEmpty()
        }
        if (label.isBlank()) return null
        val approximate = distance > maxOf(30.0, accuracy) || found.subThoroughfare.isNullOrBlank()
        return (if (approximate) "Near " else "") + label.take(180)
    }

    /** A cached result and its expiry time. */
    private data class Entry(val expires: Long, val text: String?)
}
