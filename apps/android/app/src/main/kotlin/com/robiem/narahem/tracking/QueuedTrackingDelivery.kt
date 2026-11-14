package com.robiem.narahem.tracking

import org.json.JSONObject

/**
 * Uploads queued rows in order. Each row's prepared record is saved before sending, so a lost
 * response is retried with identical bytes.
 */
class QueuedTrackingDelivery(
    private val queue: PendingTrackingQueue,
    private val allowed: () -> Boolean,
    private val prepare: suspend (JSONObject) -> JSONObject,
    private val onExpired: () -> Unit = {},
    private val send: suspend (JSONObject) -> Unit
) {
    /** Uploads up to [limit] rows, oldest first. Returns the number sent. */
    suspend fun drain(limit: Int = 8): Int {
        var sent = 0
        repeat(limit) {
            if (!allowed()) return sent
            val item = queue.peek() ?: return sent
            val id = item.getString("queue_id")
            try {
                val envelope = item.optJSONObject("envelope") ?: prepare(item).also {
                    item.put("envelope", it)
                    if (!queue.replace(id, item)) return sent
                }
                if (!allowed() || queue.peek()?.optString("queue_id") != id) return sent
                send(envelope)
                // Remove by ID, so a concurrent clear can't remove a newer row.
                queue.remove(id)
                sent++
            } catch (_: ExpiredTrackingSample) {
                if (queue.remove(id)) onExpired()
            } catch (_: ReprepareTrackingSample) {
                item.remove("envelope")
                queue.replace(id, item)
                return sent
            } catch (_: TrackingDisabled) {
                queue.clear()
                throw TrackingDisabled()
            }
        }
        return sent
    }
}
