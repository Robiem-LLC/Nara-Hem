package com.robiem.narahem.tracking

/**
 * Limits how often fixes are recorded, using elapsed realtime. Movement can bypass the interval; a
 * 5 second minimum drops duplicate callbacks.
 */
class TrackingCadence {
    private var dueAt = 0L
    private var lastAccepted = Long.MIN_VALUE

    /** Returns true if a fix should be recorded now. */
    fun accept(now: Long, movement: Boolean = false): Boolean {
        val wake = movement && (lastAccepted == Long.MIN_VALUE || now - lastAccepted >= 5_000L)
        if (!wake && now < dueAt) return false
        lastAccepted = now
        return true
    }

    /** Sets when the next fix is due. */
    fun schedule(now: Long, interval: Long) {
        dueAt = now + interval
    }
}
