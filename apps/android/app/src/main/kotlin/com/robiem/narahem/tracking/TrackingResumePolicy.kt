package com.robiem.narahem.tracking

/** Decides whether sharing may restart automatically. */
internal object TrackingResumePolicy {
    /**
     * Returns true only if sharing was enabled, map consent was given, and foreground and
     * background location are granted.
     */
    fun permits(enabled: Boolean, consent: Boolean, location: Boolean, background: Boolean) =
        enabled && consent && location && background
}
