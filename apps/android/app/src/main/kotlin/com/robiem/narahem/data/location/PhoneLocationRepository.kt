package com.robiem.narahem.data.location

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.BatteryManager
import android.os.Bundle
import android.os.Looper
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeout

/** [LocationRepository] using Android's LocationManager (GPS and network providers). */
class PhoneLocationRepository(context: Context) : LocationRepository {
    private val manager = context.getSystemService(LocationManager::class.java)
    private val context = context.applicationContext

    /** Requests a fresh location from the most accurate provider. */
    override suspend fun current(): LocalFix = current(preferLowPower = false)

    /**
     * Requests one location update, using the network provider when [preferLowPower] is set. Uses
     * the deprecated requestSingleUpdate because its replacement needs Android 11 (minSdk is 26)
     * and Play Services is unavailable in the OpenStreetMap build.
     */
    @SuppressLint("MissingPermission")
    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    suspend fun current(preferLowPower: Boolean): LocalFix = withTimeout(20_000) {
        suspendCancellableCoroutine { continuation ->
            val listener = object : LocationListener {
                override fun onLocationChanged(location: Location) {
                    manager.removeUpdates(this)
                    if (continuation.isActive) {
                        continuation.resume(
                            LocalFix(
                                location.latitude,
                                location.longitude,
                                location.accuracy,
                                speedMps = trustedSpeed(location),
                                batteryPct = batteryPercent(),
                                charging = charging()
                            )
                        )
                    }
                }
                override fun onProviderDisabled(provider: String) {
                    manager.removeUpdates(this)
                    if (continuation.isActive) {
                        continuation.resumeWithException(
                            IllegalStateException("Turn on phone location services and try again.")
                        )
                    }
                }
                override fun onProviderEnabled(provider: String) {}
                override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
            }
            continuation.invokeOnCancellation { manager.removeUpdates(listener) }
            try {
                if (!hasAnyLocation()) {
                    throw SecurityException(
                        "Location permission is required. Enable location access in app settings."
                    )
                }
                val fine = hasFineLocation()
                val provider = if (preferLowPower &&
                    manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
                ) {
                    LocationManager.NETWORK_PROVIDER
                } else if (fine && manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                    LocationManager.GPS_PROVIDER
                } else {
                    LocationManager.NETWORK_PROVIDER
                }
                if (!manager.isProviderEnabled(provider)) {
                    throw IllegalStateException("Turn on phone location services and try again.")
                }
                manager.requestSingleUpdate(provider, listener, Looper.getMainLooper())
            } catch (denied: SecurityException) {
                if (continuation.isActive) continuation.resumeWithException(denied)
            } catch (failure: Exception) {
                if (continuation.isActive) continuation.resumeWithException(failure)
            }
        }
    }

    /**
     * Starts continuous location updates at the given interval and returns a handle that stops
     * them. Updates arrive through provider callbacks, which wake the CPU in a way a coroutine
     * delay can't.
     */
    // Callers only start a watch with location allowed; a SecurityException reaches them.
    @SuppressLint("MissingPermission")
    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    fun watch(
        intervalMs: Long,
        lowPower: Boolean,
        onFix: (LocalFix) -> Unit,
        onProblem: (String) -> Unit
    ): AutoCloseable {
        if (!hasAnyLocation()) throw SecurityException("Location permission is required")
        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                if (!location.latitude.isFinite() || !location.longitude.isFinite()) return
                onFix(
                    LocalFix(
                        location.latitude, location.longitude, location.accuracy,
                        speedMps = trustedSpeed(location), batteryPct = batteryPercent(),
                        charging = charging(),
                        capturedAtMillis = location.time, provider = location.provider,
                        bearingDeg = location.bearing.takeIf {
                            location.hasBearing() &&
                                location.hasBearingAccuracy() &&
                                location.bearingAccuracyDegrees <= 20f
                        }
                    )
                )
            }
            override fun onProviderDisabled(provider: String) {
                onProblem("Location provider unavailable; waiting for a fix")
            }
            override fun onProviderEnabled(provider: String) { }
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) { }
        }
        try {
            val fine = hasFineLocation()
            val providers = manager.allProviders
            // Low power: network location only, which is enough to notice a departure. GPS is used
            // only if there is no network provider.
            val network = LocationManager.NETWORK_PROVIDER in providers
            if (fine && LocationManager.GPS_PROVIDER in providers && !(lowPower && network)) {
                manager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER,
                    intervalMs,
                    0f,
                    listener,
                    Looper.getMainLooper()
                )
            }
            if ((lowPower || !fine || LocationManager.GPS_PROVIDER !in providers) && network) {
                manager.requestLocationUpdates(
                    LocationManager.NETWORK_PROVIDER,
                    if (lowPower) minOf(intervalMs, 60_000L) else intervalMs,
                    0f,
                    listener,
                    Looper.getMainLooper()
                )
            }
            if (LocationManager.PASSIVE_PROVIDER in providers) {
                manager.requestLocationUpdates(
                    LocationManager.PASSIVE_PROVIDER,
                    0L,
                    0f,
                    listener,
                    Looper.getMainLooper()
                )
            }
            val usableProvider = providers.any {
                (it == LocationManager.GPS_PROVIDER && fine) ||
                    it == LocationManager.NETWORK_PROVIDER
            }
            if (!usableProvider) throw IllegalStateException("No location provider available")
        } catch (failure: Exception) {
            manager.removeUpdates(listener)
            throw failure
        }
        return AutoCloseable { manager.removeUpdates(listener) }
    }

    /** Returns the newest cached location across all providers. */
    @SuppressLint("MissingPermission")
    override fun lastKnown(): LocalFix? = runCatching {
        val latest = manager.getProviders(true).mapNotNull { manager.getLastKnownLocation(it) }
            .filter { it.latitude.isFinite() && it.longitude.isFinite() }
            .maxByOrNull { it.elapsedRealtimeNanos }
        latest?.let { LocalFix(it.latitude, it.longitude, it.accuracy) }
    }.getOrNull()

    /** Returns true if precise location permission is granted. */
    private fun hasFineLocation() =
        context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    /** Returns true if precise or approximate location permission is granted. */
    private fun hasAnyLocation() = hasFineLocation() ||
        context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) ==
        PackageManager.PERMISSION_GRANTED

    /** Returns the battery level from 0 to 100, or null if unavailable. */
    private fun batteryPercent(): Int? = context.getSystemService(BatteryManager::class.java)
        .getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).takeIf { it in 0..100 }

    /** Returns whether the phone is charging or full, or null if unknown. */
    private fun charging(): Boolean? {
        val status = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            ?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        if (status == -1) return null
        return status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
    }

    /** Returns the speed only when the reported speed accuracy is within 3 m/s. */
    private fun trustedSpeed(location: Location): Float? = location.speed.takeIf {
        location.hasSpeed() && location.hasSpeedAccuracy() &&
            location.speedAccuracyMetersPerSecond <= 3f && it >= 0f
    }
}
