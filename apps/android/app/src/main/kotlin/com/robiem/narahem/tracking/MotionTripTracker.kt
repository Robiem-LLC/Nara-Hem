package com.robiem.narahem.tracking

import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.PlaceMatching
import com.robiem.narahem.data.location.LocalFix
import kotlin.math.abs
import kotlin.math.cos

/** Maximum number of points in a trip's route outline. */
internal const val MAX_OUTLINE_POINTS = 120

/**
 * Maximum distance between the parked position and the first moving fix for the trip to start at
 * the parked position.
 */
internal const val MAX_DEPARTURE_GAP_METERS = 3_000.0

/** Rounds a coordinate to five decimal places (about 1 m) to keep trip summaries small. */
internal fun roundCoordinate(value: Double) = Math.round(value * 100_000.0) / 100_000.0

/**
 * Removes the interior point whose removal changes the line least (the smallest triangle with its
 * neighbours). Endpoints are never removed.
 */
internal fun dropFlattestPoint(outline: MutableList<List<Double>>) {
    if (outline.size < 3) return
    val scale = cos(Math.toRadians(outline[0][0]))
    var best = 1
    var bestArea = Double.MAX_VALUE
    for (i in 1 until outline.lastIndex) {
        val a = outline[i - 1]
        val b = outline[i]
        val c = outline[i + 1]
        val area =
            abs((b[1] - a[1]) * scale * (c[0] - a[0]) - (c[1] - a[1]) * scale * (b[0] - a[0]))
        if (area < bestArea) {
            bestArea = area
            best = i
        }
    }
    outline.removeAt(best)
}

/** Detects trips from GPS fixes: start and end, distance, top speed and a route outline. */
class MotionTripTracker {
    private val candidate = mutableListOf<Pair<LocalFix, Long>>()
    private var start: Long? = null
    private var last: Pair<LocalFix, Long>? = null
    private var lastMovingAt = 0L
    private var peak = 0f
    private var traveled = 0.0
    private var samples = 0
    private var recentPeak: Float? = null
    private var candidateTripId: String? = null
    private var activeTripId: String? = null
    private var startingPlace: HouseholdPlace? = null
    private var observedPlaceExit = false
    private var stayAnchor: Pair<LocalFix, Long>? = null
    private var stayConfirmed = false
    private val outline = mutableListOf<List<Double>>()

    /** Returns the distance between two fixes in metres. */
    private fun distance(a: LocalFix, b: LocalFix) =
        PlaceMatching.distance(a.latitude, a.longitude, b.latitude, b.longitude)

    /** Returns true if the fix has valid coordinates and accuracy of 50 m or better. */
    private fun reliable(f: LocalFix) = f.accuracy.isFinite() && f.accuracy in 0f..50f &&
        f.latitude.isFinite() && f.latitude in -90.0..90.0 && f.longitude.isFinite() &&
        f.longitude in -180.0..180.0

    /** Returns false if travelling between the two fixes would need an impossible speed. */
    private fun plausible(a: Pair<LocalFix, Long>, b: Pair<LocalFix, Long>): Boolean {
        val dt = (b.second - a.second) / 1000.0
        return dt > 0 && dt <= 120 && distance(
            a.first,
            b.first
        ) <= 65 * dt + a.first.accuracy + b.first.accuracy
    }

    /** Adds a fix to the current trip and updates distance and top speed. */
    private fun append(f: LocalFix, now: Long, moving: Boolean) {
        startingPlace?.let { place ->
            if (reliable(f) &&
                PlaceMatching.distance(place.latitude, place.longitude, f.latitude, f.longitude) >
                place.radius + minOf(10.0, f.accuracy.toDouble())
            ) {
                observedPlaceExit = true
            }
        }
        val old = last
        if (old != null && plausible(old, f to now)) {
            val step = distance(old.first, f)
            if (step > old.first.accuracy + f.accuracy) traveled += step
        }
        last = f to now
        if (moving) {
            lastMovingAt = now
            peak = maxOf(peak, f.speedMps ?: 0f)
            samples++
            addOutline(f)
        }
    }

    /** Adds a fix to the route outline, thinning it once it reaches [MAX_OUTLINE_POINTS]. */
    private fun addOutline(f: LocalFix) {
        val point = listOf(roundCoordinate(f.latitude), roundCoordinate(f.longitude))
        val previous = outline.lastOrNull()
        if (previous != null &&
            PlaceMatching.distance(previous[0], previous[1], point[0], point[1]) < 8.0
        ) {
            outline[outline.lastIndex] = point
            return
        }
        if (outline.size >= MAX_OUTLINE_POINTS) dropFlattestPoint(outline)
        outline.add(point)
    }

    /**
     * Returns where the trip should start. A trip is confirmed only after some travel, so this uses
     * the last parked fix (or the saved place being left) unless it is too far from the first
     * moving fix.
     */
    private fun departureOrigin(parkedAt: LocalFix?, first: LocalFix): LocalFix? {
        val origin =
            parkedAt ?: startingPlace?.let {
                LocalFix(it.latitude, it.longitude, 0f)
            } ?: return null
        return origin.takeIf { distance(it, first) <= MAX_DEPARTURE_GAP_METERS }
    }

    /**
     * Completes the current trip if no moving fix arrived for three minutes. Needed because GPS
     * callbacks can stop after a trip.
     */
    fun completeIfIdle(now: Long): CompletedTrip? {
        if (start == null || now - lastMovingAt < 180000L) return null
        val result = if (traveled >= 50 && samples >= 2 &&
            (startingPlace == null || observedPlaceExit)
        ) {
            CompletedTrip(
                start!!,
                lastMovingAt,
                peak,
                traveled,
                samples,
                activeTripId,
                outline.toList().takeIf { it.size >= 2 } ?: emptyList(),
                startingPlace?.name
            )
        } else {
            null
        }
        if (result != null) recentPeak = peak
        stayAnchor = last?.takeIf { reliable(it.first) }
        stayConfirmed = false
        start = null
        last = null
        candidate.clear()
        candidateTripId = null
        activeTripId = null
        peak = 0f
        traveled = 0.0
        samples = 0
        startingPlace = null
        observedPlaceExit = false
        outline.clear()
        return result
    }

    /**
     * Processes a fix and returns the trip state, including the completed trip if this fix ended
     * one.
     */
    fun observe(
        fix: LocalFix,
        now: Long,
        places: List<HouseholdPlace> = emptyList()
    ): TripProgress {
        val moving = reliable(fix) && (fix.speedMps ?: -1f) in 0.8f..65f
        if (start == null) {
            if (!moving) {
                candidate.clear()
                candidateTripId = null
                if (reliable(fix)) {
                    val anchor = stayAnchor
                    if (anchor == null ||
                        distance(anchor.first, fix) >
                        maxOf(30.0, (anchor.first.accuracy + fix.accuracy).toDouble())
                    ) {
                        stayAnchor = fix to now
                        stayConfirmed = false
                    } else if (now - anchor.second >= 180000L) {
                        stayConfirmed = true
                    }
                }
            } else {
                if (candidate.isNotEmpty() &&
                    (
                        !plausible(
                            candidate.last(),
                            fix to now
                        ) || now - candidate.first().second > 120000
                        )
                ) {
                    candidate.clear()
                    candidateTripId = null
                }
                if (candidateTripId == null) {
                    candidateTripId = java.util.UUID.randomUUID().toString().replace("-", "")
                }
                candidate.add(fix to now)
                if (candidate.size >= 2 && now - candidate.first().second >= 10000 &&
                    distance(candidate.first().first, fix) >
                    maxOf(50.0, (candidate.first().first.accuracy + fix.accuracy).toDouble()) &&
                    (
                        !stayConfirmed || stayAnchor == null || candidate.takeLast(2).all {
                            distance(stayAnchor!!.first, it.first) >
                                (
                                    maxOf(40.0, stayAnchor!!.first.accuracy * 2.0) +
                                        it.first.accuracy.toDouble()
                                    )
                        }
                        )
                ) {
                    start = candidate.first().second
                    activeTripId = candidateTripId
                    last = null
                    peak = 0f
                    traveled = 0.0
                    samples = 0
                    outline.clear()
                    val parkedAt = stayAnchor?.first
                    stayAnchor = null
                    stayConfirmed = false
                    val first = candidate.first().first
                    startingPlace =
                        PlaceMatching.match(
                            first.latitude,
                            first.longitude,
                            places,
                            first.accuracy.toDouble()
                        )
                    observedPlaceExit = false
                    departureOrigin(parkedAt, first)?.let { origin ->
                        addOutline(origin)
                        val gap = distance(origin, first)
                        if (gap > origin.accuracy + first.accuracy) traveled += gap
                    }
                    candidate.forEach { append(it.first, it.second, true) }
                    candidate.clear()
                }
            }
        } else if (reliable(fix) && (last == null || plausible(last!!, fix to now))) {
            append(fix, now, moving)
        }
        val completed = completeIfIdle(now)
        return TripProgress(
            start != null,
            start,
            peak.takeIf { start != null },
            traveled.takeIf {
                start !=
                    null
            },
            recentPeak,
            completed,
            activeTripId ?: candidateTripId
        )
    }
}
