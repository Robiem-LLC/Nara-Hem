package com.robiem.narahem.data.location

/** Street address lookups using the phone's geocoder. Each call sends coordinates or text to it. */
interface AddressLookup {
    /** Returns a street address near the point, or null if none is close enough. */
    suspend fun near(latitude: Double, longitude: Double): String?

    /** Returns the coordinates of an address or business, or null if nothing matches. */
    suspend fun find(query: String): Pair<Double, Double>?
}
