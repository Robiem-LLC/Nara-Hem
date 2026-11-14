package com.robiem.narahem.tracking

import android.content.Context
import android.util.AtomicFile
import java.io.File
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject

/**
 * [PendingTrackingQueue] stored as a JSON file in no-backup app storage, one file per server,
 * account and device.
 */
class OfflineOutbox(context: Context, namespace: String) : PendingTrackingQueue {
    init {
        require(namespace.matches(Regex("[a-f0-9]{64}")))
    }

    private val stats = context.getSharedPreferences("tracking-queue-stats", Context.MODE_PRIVATE)
    private val droppedKey = "dropped-$namespace"
    private val store = AtomicFile(File(context.noBackupFilesDir, "offline-outbox-$namespace.json"))

    /** Returns how many queued locations were dropped for being too old. */
    fun droppedCount(): Int = stats.getInt(droppedKey, 0)

    /** Deletes the queue file. */
    override fun clear() = synchronized(fileLock) { store.delete() }

    /** Returns the number of queued rows. */
    override fun size(): Int = synchronized(fileLock) { read().length() }

    /** Increments the dropped-location count. */
    fun recordExpired() = locked {
        stats.edit().putInt(droppedKey, (droppedCount() + 1).coerceAtMost(1_000_000)).apply()
    }

    /** Adds a row, removing one chosen by [OutboxThinning] when the queue is full. */
    override fun append(value: JSONObject) = synchronized(fileLock) {
        val rows = read()
        val copy = JSONObject(value.toString()).put("queue_id", UUID.randomUUID().toString())
        var dropped = 0
        rows.put(copy)
        while (rows.length() > 2000 ||
            rows.toString().toByteArray(Charsets.UTF_8).size > 4 * 1024 * 1024
        ) {
            rows.remove(victim(rows))
            dropped++
        }
        if (dropped > 0) {
            stats.edit().putInt(
                droppedKey,
                (droppedCount() + dropped).coerceAtMost(1_000_000)
            ).apply()
        }
        write(rows)
    }

    /**
     * Returns the row to drop when full: a GPS fix chosen by [OutboxThinning], or the oldest row if
     * no fix can be removed.
     */
    private fun victim(rows: JSONArray): Int {
        val items = (0 until rows.length()).map { rows.getJSONObject(it) }
        return OutboxThinning.victim(
            items.map {
                it.optString("kind")
            },
            items.map { it.optLong("captured") }
        )
            ?: 0
    }

    /** Returns a copy of the oldest row. */
    override fun peek(): JSONObject? = synchronized(fileLock) {
        read().optJSONObject(0)?.let { JSONObject(it.toString()) }
    }

    /** Replaces the row with the given queue ID. Returns false if it no longer exists. */
    override fun replace(id: String, value: JSONObject): Boolean = synchronized(fileLock) {
        val rows = read()
        val index =
            (0 until rows.length()).firstOrNull {
                rows.getJSONObject(it).getString("queue_id") == id
            }
                ?: return@synchronized false
        rows.put(index, JSONObject(value.toString()))
        write(rows)
        true
    }

    /** Removes the row with the given queue ID. Returns false if it no longer exists. */
    override fun remove(id: String): Boolean = synchronized(fileLock) {
        val rows = read()
        val index =
            (0 until rows.length()).firstOrNull {
                rows.getJSONObject(it).getString("queue_id") == id
            }
                ?: return@synchronized false
        rows.remove(index)
        write(rows)
        true
    }

    /** Reads the queue file, or returns an empty queue if the file doesn't exist. */
    private fun read(): JSONArray = try {
        JSONArray(String(store.openRead().use { it.readBytes() }, Charsets.UTF_8))
    } catch (_: java.io.FileNotFoundException) {
        JSONArray()
    }

    /** Writes the queue atomically with AtomicFile. */
    private fun write(rows: JSONArray) {
        val output = store.startWrite()
        try {
            output.write(rows.toString().toByteArray(Charsets.UTF_8))
            store.finishWrite(output)
        } catch (failure: Exception) {
            store.failWrite(output)
            throw failure
        }
    }

    /** Lock and helpers shared by every queue. */
    companion object {
        private val fileLock = Any()

        /** Runs [action] while holding the queue file lock. */
        fun <T> locked(action: () -> T): T = synchronized(fileLock) { action() }

        /** Deletes every queue file. */
        fun clearAll(context: Context) = synchronized(fileLock) {
            context.noBackupFilesDir.listFiles()?.filter {
                it.name.startsWith("offline-outbox") &&
                    (
                        it.name.endsWith(".json") || it.name.endsWith(".json.bak") ||
                            it.name.endsWith(".json.new")
                        )
            }?.forEach { it.delete() }
        }
    }
}
