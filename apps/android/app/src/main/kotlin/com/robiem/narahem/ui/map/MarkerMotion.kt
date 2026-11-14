package com.robiem.narahem.ui.map

import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Glides member markers between location fixes, as the iPhone app does: from where a marker is
 * shown to its new fix, over most of the time between the two fixes. It never moves past the
 * latest fix, and jumps when a change is too large to be real movement.
 */
class MarkerMotion {
    private val fixTimes = mutableMapOf<String, Long>()
    private val glides = mutableMapOf<String, Glide>()

    /** Whether any marker is still gliding. */
    val moving: Boolean get() = glides.isNotEmpty()

    /** The markers that are gliding. */
    val gliding: Set<String> get() = glides.keys.toSet()

    /**
     * Takes a member's latest fix, captured at [capturedAt], for a marker shown at [shown] (null if
     * it isn't on the map yet), and returns where to show it at [now]. Starts a glide for a newer,
     * plausible fix; otherwise jumps to it.
     */
    fun update(
        id: String,
        shown: Pair<Double, Double>?,
        fix: Pair<Double, Double>,
        capturedAt: Long,
        now: Long
    ): Pair<Double, Double> {
        val previous = fixTimes[id]
        if (shown == null || previous == null) {
            fixTimes[id] = capturedAt
            glides.remove(id)
            return fix
        }
        if (capturedAt <= previous) return positionAt(id, now) ?: shown
        fixTimes[id] = capturedAt
        val seconds = (capturedAt - previous) / 1000.0
        val meters = distanceMeters(shown, fix)
        if (meters < MIN_METERS || meters > MAX_METERS || seconds > MAX_SECONDS) {
            glides.remove(id)
            return fix
        }
        glides[id] = Glide(shown, fix, now, durationMillis(seconds))
        return shown
    }

    /** Returns where a gliding marker is at [now], or null if it isn't gliding. */
    fun positionAt(id: String, now: Long): Pair<Double, Double>? {
        val glide = glides[id] ?: return null
        val progress = ((now - glide.startedAt).toDouble() / glide.millis).coerceIn(0.0, 1.0)
        if (progress >= 1.0) glides.remove(id)
        return interpolate(glide.from, glide.to, progress)
    }

    /** Forgets a marker that has left the map. */
    fun forget(id: String) {
        fixTimes.remove(id)
        glides.remove(id)
    }

    private class Glide(
        val from: Pair<Double, Double>,
        val to: Pair<Double, Double>,
        val startedAt: Long,
        val millis: Long
    )

    companion object {
        private const val MIN_METERS = 3.0
        private const val MAX_METERS = 2_000.0
        private const val MAX_SECONDS = 120.0

        /** Returns how long a glide takes for fixes [seconds] apart: 80%, from 0.5 to 12 s. */
        fun durationMillis(seconds: Double): Long {
            if (!seconds.isFinite() || seconds <= 0) return 0
            return (min(12.0, max(0.5, seconds * 0.8)) * 1000).toLong()
        }

        /** Returns the point a fraction [progress] of the way from [from] to [to]. */
        fun interpolate(
            from: Pair<Double, Double>,
            to: Pair<Double, Double>,
            progress: Double
        ): Pair<Double, Double> {
            val fraction = progress.coerceIn(0.0, 1.0)
            return from.first + (to.first - from.first) * fraction to
                from.second + (to.second - from.second) * fraction
        }

        /** Returns the distance between two points in meters. */
        fun distanceMeters(a: Pair<Double, Double>, b: Pair<Double, Double>): Double {
            val lat1 = Math.toRadians(a.first)
            val lat2 = Math.toRadians(b.first)
            val dLat = lat2 - lat1
            val dLon = Math.toRadians(b.second - a.second)
            val h = sin(dLat / 2) * sin(dLat / 2) +
                cos(lat1) * cos(lat2) * sin(dLon / 2) * sin(dLon / 2)
            return 2 * 6_371_000.0 * asin(sqrt(min(1.0, h)))
        }
    }
}
