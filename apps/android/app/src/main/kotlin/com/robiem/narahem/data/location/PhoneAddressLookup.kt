package com.robiem.narahem.data.location

import android.content.Context
import android.location.Geocoder
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** [AddressLookup] using Android's Geocoder. */
class PhoneAddressLookup(context: Context) : AddressLookup {
    private val appContext = context.applicationContext

    /** Looks up an address on the IO dispatcher through [NearbyAddress]. */
    override suspend fun near(latitude: Double, longitude: Double): String? =
        withContext(Dispatchers.IO) { NearbyAddress.lookup(appContext, latitude, longitude) }

    /** Geocodes the query on the IO dispatcher and returns the first match. */
    @Suppress("DEPRECATION")
    override suspend fun find(query: String): Pair<Double, Double>? = withContext(Dispatchers.IO) {
        Geocoder(appContext, Locale.getDefault()).getFromLocationName(query, 1)?.firstOrNull()
            ?.let { it.latitude to it.longitude }
    }
}
