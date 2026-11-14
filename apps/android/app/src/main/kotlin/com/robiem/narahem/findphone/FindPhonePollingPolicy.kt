package com.robiem.narahem.findphone

/**
 * Polling intervals for Find My Phone commands. Commands normally arrive by a high-priority push;
 * polling only covers a lost push.
 */
internal object FindPhonePollingPolicy {
    /** Polling interval while Find My Phone is enabled. */
    const val ENABLED_INTERVAL_MS = 60_000L

    /** Polling interval while it is disabled, to keep the capability in sync. */
    const val DISABLED_INTERVAL_MS = 15 * 60_000L

    /** Retry interval while there is no network. */
    const val OFFLINE_INTERVAL_MS = 60_000L

    /** Retry interval after a failed poll. */
    const val ERROR_INTERVAL_MS = 60_000L

    /** Returns the delay before the next poll. */
    fun interval(enabled: Boolean, connected: Boolean): Long = when {
        !connected -> OFFLINE_INTERVAL_MS
        enabled -> ENABLED_INTERVAL_MS
        else -> DISABLED_INTERVAL_MS
    }
}
