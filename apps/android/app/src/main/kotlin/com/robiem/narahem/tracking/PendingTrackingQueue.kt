package com.robiem.narahem.tracking

import org.json.JSONObject

/** Persistent queue of locations and trips waiting to upload. */
interface PendingTrackingQueue {
    /** Adds a row, dropping another if the queue is full. */
    fun append(value: JSONObject)

    /** Returns the oldest row without removing it. */
    fun peek(): JSONObject?

    /** Replaces a row. Returns false if it no longer exists. */
    fun replace(id: String, value: JSONObject): Boolean

    /** Removes a row. Returns false if it no longer exists. */
    fun remove(id: String): Boolean

    /** Removes every row. */
    fun clear()

    /** Returns the number of rows. */
    fun size(): Int
}
