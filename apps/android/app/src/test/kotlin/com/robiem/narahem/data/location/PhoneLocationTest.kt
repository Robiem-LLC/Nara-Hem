package com.robiem.narahem.data.location

import android.Manifest
import android.app.Application
import android.location.Address
import android.location.Location
import android.location.LocationManager
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.util.Locale
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf

/** Phone location and address lookups through Robolectric's LocationManager and Geocoder. */
@RunWith(AndroidJUnit4::class)
class PhoneLocationTest {
    private val context: Application get() = ApplicationProvider.getApplicationContext()
    private val manager get() = context.getSystemService(LocationManager::class.java)

    private fun grant(vararg permissions: String) = shadowOf(context).grantPermissions(*permissions)

    private fun location(provider: String, lat: Double, lon: Double) = Location(provider).apply {
        latitude = lat
        longitude = lon
        accuracy = 5f
        time = 1_000
        speed = 4f
        speedAccuracyMetersPerSecond = 1f
        elapsedRealtimeNanos = System.nanoTime()
    }

    @Test fun locationNeedsPermissionAndEnabledProviders() = runBlocking<Unit> {
        val repo = PhoneLocationRepository(context)
        val denied = assertThrows(SecurityException::class.java) { runBlocking { repo.current() } }
        assertTrue(denied.message!!.startsWith("Location permission is required"))
        assertThrows(SecurityException::class.java) { repo.watch(1000, false, {}, {}) }
        grant(Manifest.permission.ACCESS_FINE_LOCATION)
        shadowOf(manager).setProviderEnabled(LocationManager.GPS_PROVIDER, false)
        shadowOf(manager).setProviderEnabled(LocationManager.NETWORK_PROVIDER, false)
        val off = assertThrows(IllegalStateException::class.java) { runBlocking { repo.current() } }
        assertEquals("Turn on phone location services and try again.", off.message)
    }

    @Test fun oneFreshFixComesFromGps() = runBlocking<Unit> {
        grant(Manifest.permission.ACCESS_FINE_LOCATION)
        shadowOf(manager).setProviderEnabled(LocationManager.GPS_PROVIDER, true)
        val repo = PhoneLocationRepository(context)
        val pending = async { repo.current() }
        yield()
        shadowOf(Looper.getMainLooper()).idle()
        shadowOf(manager).simulateLocation(location(LocationManager.GPS_PROVIDER, 51.5, -0.12))
        shadowOf(Looper.getMainLooper()).idle()
        val fix = pending.await()
        assertEquals(51.5, fix.latitude, 0.0)
        assertEquals(4f, fix.speedMps)
    }

    @Test fun watchingDeliversFixesUntilClosed() {
        grant(Manifest.permission.ACCESS_FINE_LOCATION)
        val repo = PhoneLocationRepository(context)
        val fixes = mutableListOf<LocalFix>()
        val watch = repo.watch(5_000, lowPower = false, onFix = { fixes += it }, onProblem = {})
        assertTrue(
            shadowOf(manager).getLocationUpdateListeners(LocationManager.GPS_PROVIDER).isNotEmpty()
        )
        shadowOf(manager).simulateLocation(location(LocationManager.GPS_PROVIDER, 1.0, 2.0))
        shadowOf(Looper.getMainLooper()).idle()
        assertTrue(fixes.isNotEmpty())
        assertTrue(fixes.all { it.provider == LocationManager.GPS_PROVIDER })
        watch.close()
        assertTrue(
            shadowOf(manager).getLocationUpdateListeners(LocationManager.GPS_PROVIDER).isEmpty()
        )
        val lowPower = repo.watch(5_000, lowPower = true, onFix = { fixes += it }, onProblem = {})
        assertTrue(
            shadowOf(manager).getLocationUpdateListeners(LocationManager.GPS_PROVIDER).isEmpty()
        )
        assertTrue(
            shadowOf(
                manager
            ).getLocationUpdateListeners(LocationManager.NETWORK_PROVIDER).isNotEmpty()
        )
        lowPower.close()
    }

    @Test fun lastKnownPicksTheNewestCachedFix() {
        val repo = PhoneLocationRepository(context)
        shadowOf(manager).setProviderEnabled(LocationManager.GPS_PROVIDER, true)
        shadowOf(
            manager
        ).setLastKnownLocation(
            LocationManager.GPS_PROVIDER,
            location(LocationManager.GPS_PROVIDER, 3.0, 4.0)
        )
        assertEquals(3.0, repo.lastKnown()!!.latitude, 0.0)
    }

    private fun address(lat: Double, lon: Double, number: String?) = Address(Locale.UK).apply {
        latitude = lat
        longitude = lon
        subThoroughfare = number
        thoroughfare = "High Street"
        locality = "Oxford"
        adminArea = "England"
    }

    @Test fun nearbyAddressIsExactOnlyWhenClose() {
        val here = address(51.75, -1.25, "12")
        assertEquals(
            "12 High Street, Oxford, England",
            NearbyAddress.describe(here, 51.75, -1.25, 25.0)
        )
        assertEquals(
            "Near High Street, Oxford, England",
            NearbyAddress.describe(address(51.75, -1.25, null), 51.75, -1.25, 25.0)
        )
        assertEquals(
            "Near 12 High Street, Oxford, England",
            NearbyAddress.describe(here, 51.7505, -1.25, 25.0)
        )
        assertNull(NearbyAddress.describe(here, 51.76, -1.25, 25.0))
        assertNull(NearbyAddress.describe(null, 51.75, -1.25, 25.0))
        val lineOnly = Address(Locale.UK).apply {
            latitude = 51.75
            longitude = -1.25
            setAddressLine(0, "Radcliffe Square")
        }
        assertEquals("Near Radcliffe Square", NearbyAddress.describe(lineOnly, 51.75, -1.25, 25.0))
    }

    @Test fun addressLookupsWithoutAGeocoderResultReturnNothing() = runBlocking<Unit> {
        val lookup = PhoneAddressLookup(context)
        assertNull(lookup.near(40.0, -3.0))
        assertNull(lookup.near(40.0, -3.0))
    }
}
