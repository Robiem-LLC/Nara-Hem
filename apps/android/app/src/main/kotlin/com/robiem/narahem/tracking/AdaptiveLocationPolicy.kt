package com.robiem.narahem.tracking
import com.robiem.narahem.data.location.LocalFix
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Chooses the GPS sampling interval: precise GPS while moving, network location only while parked,
 * with an occasional GPS fix to confirm the parked position.
 */
class AdaptiveLocationPolicy {
    private var previous: LocalFix? = null
    private var stationarySamples = 0
    private var lastHighAccuracyAt = 0L

    /**
     * Returns true when the phone has been stationary for several fixes and had a recent precise
     * fix.
     */
    fun preferLowPower(now: Long): Boolean =
        stationarySamples >= 3 && now - lastHighAccuracyAt < PRECISE_CHECK_MS

    /** Records the time of the latest GPS fix. */
    fun recordHighAccuracy(now: Long) {
        lastHighAccuracyAt = now
    }

    /** Returns the next sampling interval in milliseconds, based on the fix's speed. */
    fun observe(fix: LocalFix): Long {
        val old = previous
        previous = fix
        val reliable = fix.accuracy.isFinite() && fix.accuracy in 0f..100f
        val displaced = old != null && old.accuracy <= 100f && reliable &&
            distance(old, fix) > max(60.0, (old.accuracy + fix.accuracy).toDouble())
        return when {
            !reliable -> {
                stationarySamples = 0
                90_000L
            }

            (fix.speedMps ?: 0f) >= 10.73f -> {
                stationarySamples = 0
                4_000L
            }

            (fix.speedMps ?: 0f) >= 2.24f || displaced -> {
                stationarySamples = 0
                9_000L
            }

            (fix.speedMps ?: 0f) >= 0.8f -> {
                stationarySamples = 0
                15_000L
            }

            else -> {
                stationarySamples++
                if (stationarySamples >= 3) STATIONARY_CHECK_IN_MS else 45_000L
            }
        }
    }

    /**
     * Returns true if the fix shows a real departure from the parked position. Requires recent,
     * accurate fixes so a coarse network position jump doesn't count as movement.
     */
    fun movementWake(previous: LocalFix?, current: LocalFix, wallNow: Long): Boolean {
        if (!current.accuracy.isFinite() || current.accuracy !in 0f..50f ||
            !current.latitude.isFinite() || !current.longitude.isFinite() ||
            current.latitude !in -90.0..90.0 || current.longitude !in -180.0..180.0
        ) {
            return false
        }
        val captured = current.capturedAtMillis ?: wallNow
        if (captured > wallNow + 10_000L || wallNow - captured > 60_000L) return false
        val speed = current.speedMps ?: -1f
        if (speed.isFinite() && speed in 2.24f..65f) return true
        return previous != null && previous.accuracy.isFinite() &&
            previous.accuracy in 0f..50f && distance(previous, current) >
            max(65.0, (previous.accuracy + current.accuracy).toDouble() * 2)
    }

    /** Returns the distance between two fixes in metres. */
    private fun distance(a: LocalFix, b: LocalFix): Double {
        val dLat = Math.toRadians(b.latitude - a.latitude)
        val dLon = Math.toRadians(b.longitude - a.longitude)
        val latA = Math.toRadians(a.latitude)
        val latB = Math.toRadians(b.latitude)
        val h = sin(dLat / 2).pow(2) + cos(latA) * cos(latB) * sin(dLon / 2).pow(2)
        return 12_742_000.0 * asin(sqrt(h.coerceIn(0.0, 1.0)))
    }

    /** Interval constants. */
    companion object {
        const val STATIONARY_CHECK_IN_MS = 15 * 60_000L
        const val PRECISE_CHECK_MS = 30 * 60_000L
    }
}
