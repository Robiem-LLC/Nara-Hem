package com.robiem.narahem.data.trips
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.HouseholdTrip
import com.robiem.narahem.data.household.PlaceMatching
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Builds the trips screen content from trips and GPS points: route segments, stops, and filters for
 * false trips.
 */
object TripTimeline {
    /** Returns the points recorded by the trip's device during the trip, oldest first. */
    fun forTrip(trip: HouseholdTrip, points: List<TripPoint>): List<TripPoint> = points.filter {
        it.accountId == trip.accountId && it.deviceId == trip.deviceId &&
            it.capturedAt in trip.startedAt..trip.endedAt &&
            (trip.tripId == null || it.tripId == null || it.tripId == trip.tripId)
    }.sortedBy { it.capturedAt }

    /** Returns true if the point has valid coordinates and accuracy of 70 m or better. */
    private fun usable(p: TripPoint) = p.latitude.isFinite() && p.latitude in -90.0..90.0 &&
        p.longitude.isFinite() && p.longitude in -180.0..180.0 && p.accuracy.isFinite() &&
        p.accuracy in 0.0..70.0

    /** Returns the distance between two points in metres. */
    private fun meters(a: TripPoint, b: TripPoint): Double {
        val r = Math.PI / 180
        val latitudes = sin((b.latitude - a.latitude) * r / 2).pow(2)
        val longitudes = sin((b.longitude - a.longitude) * r / 2).pow(2)
        val h = latitudes + cos(a.latitude * r) * cos(b.latitude * r) * longitudes
        return 12742000 * asin(sqrt(h.coerceIn(0.0, 1.0)))
    }

    /**
     * Splits points into drawable segments, breaking at gaps over two minutes and dropping
     * implausible jumps.
     */
    fun route(points: List<TripPoint>): List<List<TripPoint>> {
        val result = mutableListOf<MutableList<TripPoint>>()
        var last: TripPoint? = null
        for (p in points.sortedBy { it.capturedAt }) {
            if (!usable(p)) {
                last = null
                continue
            }
            val previous = last
            val seconds = if (previous == null) {
                0.0
            } else {
                (p.capturedAt - previous.capturedAt) / 1000.0
            }
            val continues = previous != null &&
                seconds > 0 &&
                seconds <= 120 &&
                p.deviceId == previous.deviceId && p.accountId == previous.accountId
            val spike = previous != null &&
                continues &&
                !(p.normalized && previous.normalized) &&
                meters(previous, p) > 65 * seconds + previous.accuracy + p.accuracy
            if (spike) {
                last = null
                continue
            }
            if (!continues) result.add(mutableListOf())
            result.last().add(p)
            last = p
        }
        return result
    }

    /**
     * Returns true if the trip's points never moved meaningfully away from the start (GPS drift
     * while parked).
     */
    fun isStationary(trip: HouseholdTrip, points: List<TripPoint>): Boolean {
        val fixes = route(forTrip(trip, points)).flatten()
        if (fixes.size < 3 || fixes.first().capturedAt - trip.startedAt > 120000 ||
            trip.endedAt - fixes.last().capturedAt > 120000
        ) {
            return false
        }
        if (fixes.zipWithNext().any {
                it.second.capturedAt - it.first.capturedAt > 300000
            }
        ) {
            return false
        }
        val lat = fixes.map { it.latitude }.sorted()[fixes.size / 2]
        val lon = fixes.map { it.longitude }.sorted()[fixes.size / 2]
        val tolerance = (
            fixes.map {
                it.accuracy
            }.sorted()[fixes.size / 2] * 2
            ).coerceIn(60.0, 100.0)
        return fixes.all {
            PlaceMatching.distance(lat, lon, it.latitude, it.longitude) <= tolerance
        }
    }

    /**
     * Returns true for short trips that are most likely GPS jitter. Only hides them from the list;
     * records are never deleted.
     */
    fun isInconsequential(
        trip: HouseholdTrip,
        points: List<TripPoint>,
        places: List<HouseholdPlace> = emptyList()
    ): Boolean {
        val duration = trip.endedAt - trip.startedAt
        if (duration !in 0L..120000L || trip.distanceMeters !in 0.0..45.0 ||
            trip.maxSpeedMps !in 0.0..10.0
        ) {
            return false
        }
        val fixes = route(forTrip(trip, points)).flatten()
        if (fixes.size < 2 || fixes.any { it.accuracy > 40 }) return false
        val home = PlaceMatching.match(
            fixes.first().latitude,
            fixes.first().longitude,
            places,
            fixes.first().accuracy
        )
        if (home != null) {
            return fixes.all {
                PlaceMatching.distance(home.latitude, home.longitude, it.latitude, it.longitude) <=
                    home.radius + minOf(10.0, it.accuracy)
            }
        }
        return fixes.size >= 3 && fixes.all { meters(fixes.first(), it) <= 30.0 }
    }

    /**
     * Derives stops between trips from GPS history, merging fragments and treating gaps as unknown
     * time.
     */
    fun stops(
        points: List<TripPoint>,
        trips: List<HouseholdTrip>,
        places: List<HouseholdPlace> = emptyList()
    ): List<TripStop> {
        val result = mutableListOf<TripStop>()
        for (group in points.groupBy { it.accountId to it.deviceId }.values) {
            val cluster = mutableListOf<TripPoint>()
            var place: HouseholdPlace? = null
            fun finish() {
                if (cluster.size >= 2 &&
                    cluster.last().capturedAt - cluster.first().capturedAt >= 180000
                ) {
                    val a = cluster.first()
                    val b = cluster.last()
                    val gaps = cluster.zipWithNext().map {
                        it.second.capturedAt - it.first.capturedAt
                    }.filter {
                        it >
                            300000
                    }.sum()
                    result.add(
                        TripStop(
                            "stop:" + a.id,
                            a.accountId,
                            a.deviceId,
                            a.capturedAt,
                            b.capturedAt,
                            place?.latitude ?: a.latitude,
                            place?.longitude ?: a.longitude,
                            gaps
                        )
                    )
                }
                cluster.clear()
                place = null
            }
            for (p in group.sortedBy { it.capturedAt }) {
                if (!usable(p)) continue
                if (trips.any {
                        it.deviceId == p.deviceId && it.accountId == p.accountId &&
                            p.capturedAt in it.startedAt..it.endedAt
                    }
                ) {
                    finish()
                    continue
                }
                val nextPlace = PlaceMatching.match(p.latitude, p.longitude, places, p.accuracy)
                val same = place != null && place?.id == nextPlace?.id
                if (cluster.isNotEmpty()) {
                    val gapLimit = if (same) 1_800_000 else 300_000
                    val longGap = p.capturedAt - cluster.last().capturedAt > gapLimit
                    val left = !same && meters(cluster.first(), p) > 75 + minOf(50.0, p.accuracy)
                    if (longGap || left) finish()
                }
                if ((p.speedMps ?: 0.0) >= 2.8 && nextPlace == null) continue
                if (cluster.isEmpty()) place = nextPlace
                cluster.add(p)
            }
            finish()
        }
        val merged = mutableListOf<TripStop>()
        for (stop in result.sortedBy { it.startedAt }) {
            val previous = merged.lastOrNull()
            val gap = if (previous != null) stop.startedAt - previous.endedAt else Long.MAX_VALUE
            val home = previous?.let { PlaceMatching.match(it.latitude, it.longitude, places, 0.0) }
            val same =
                home != null &&
                    PlaceMatching.match(stop.latitude, stop.longitude, listOf(home), 0.0) != null
            val tripBetween = previous != null && trips.any {
                it.accountId == stop.accountId &&
                    it.startedAt < stop.startedAt && it.endedAt > previous.endedAt
            }
            val moved =
                previous != null && home != null && points.any { p ->
                    p.accountId == stop.accountId &&
                        p.capturedAt > previous.endedAt && p.capturedAt < stop.startedAt &&
                        usable(p) &&
                        PlaceMatching.match(p.latitude, p.longitude, listOf(home), p.accuracy) ==
                        null
                }
            if (previous != null && previous.accountId == stop.accountId && same &&
                gap in 0..1800000 && !tripBetween && !moved
            ) {
                merged[merged.lastIndex] = previous.copy(
                    endedAt = maxOf(previous.endedAt, stop.endedAt),
                    gapMillis = previous.gapMillis + stop.gapMillis + gap
                )
            } else {
                merged.add(stop)
            }
        }
        return merged.sortedByDescending { it.startedAt }
    }
}
