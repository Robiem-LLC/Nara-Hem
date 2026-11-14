package com.robiem.narahem.tracking

import com.robiem.narahem.data.location.LocalFix
import org.json.JSONArray
import org.json.JSONObject

/**
 * Converts locations and trips to offline queue rows, and queue rows back to records for
 * publishing.
 */
object OfflineTrackingCodec {
    /** Returns a queue row for a location. */
    fun location(fix: LocalFix, at: Long): JSONObject {
        val data = JSONObject().put("lat", fix.latitude).put("lon", fix.longitude)
            .put("accuracy", fix.accuracy.toDouble())
        fix.speedMps?.let { data.put("speed_mps", it.toDouble()) }
        fix.batteryPct?.let { data.put("battery_pct", it) }
        fix.charging?.let { data.put("charging", it) }
        fix.tripMaxSpeedMps?.let { data.put("trip_max_speed_mps", it.toDouble()) }
        fix.tripDistanceMeters?.let { data.put("trip_distance_m", it) }
        fix.tripStartedAt?.let { data.put("trip_started_at", it) }
        fix.tripId?.let { data.put("trip_id", it) }
        fix.recentTripMaxSpeedMps?.let { data.put("recent_trip_max_speed_mps", it.toDouble()) }
        return JSONObject().put("kind", "location").put("captured", at).put("data", data)
    }

    /** Returns a queue row for a completed trip. */
    fun trip(summary: CompletedTrip): JSONObject = JSONObject()
        .put("kind", "trip").put("captured", summary.endedAt)
        .put("entity_id", java.util.UUID.randomUUID().toString().replace("-", ""))
        .put(
            "data",
            JSONObject().put("type", "trip_summary")
                .put("started_at", summary.startedAt).put("ended_at", summary.endedAt)
                .put("max_speed_mps", summary.maxSpeedMps.toDouble())
                .put("distance_m", summary.distanceMeters).put("samples", summary.samples)
                .apply {
                    summary.tripId?.let { put("trip_id", it) }
                    summary.originName?.takeIf {
                        it.isNotBlank()
                    }?.let { put("origin_name", it.take(80)) }
                    if (summary.outline.size >= 2) {
                        put(
                            "start",
                            JSONArray(summary.outline.first())
                        ).put("end", JSONArray(summary.outline.last()))
                        put("preview", JSONArray(summary.outline.map { JSONArray(it) }))
                    }
                }
        )

    /** Converts a queue row into the record kind, entity ID and data to publish. */
    fun payload(record: JSONObject, accountId: String): PendingTrackingPayload {
        val data = JSONObject(record.getJSONObject("data").toString())
        return when (record.getString("kind")) {
            "location" -> PendingTrackingPayload("location", accountId, data)

            "trip" -> PendingTrackingPayload(
                "event",
                record.getString("entity_id"),
                data.put("account_id", accountId)
            )

            else -> error("Unsupported queued item")
        }
    }
}
