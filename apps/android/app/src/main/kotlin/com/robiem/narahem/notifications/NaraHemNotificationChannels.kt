package com.robiem.narahem.notifications

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build

/**
 * Notification channels. Channel IDs are never renamed, because that would discard the user's
 * channel settings.
 */
object NaraHemNotificationChannels {
    /** Channel ID for arrival and departure alerts. */
    const val HOUSEHOLD_ALERTS = "narahem-household-alerts-v1"

    private const val DESCRIPTION = "When a household member leaves a place or arrives after " +
        "a drive."

    /**
     * Creates the notification channels, or updates their names and descriptions without touching
     * the user's settings.
     */
    fun ensure(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val notifications = context.getSystemService(NotificationManager::class.java)
        notifications.getNotificationChannel(HOUSEHOLD_ALERTS)?.let { existing ->
            if (existing.description != DESCRIPTION) {
                existing.description = DESCRIPTION
                notifications.createNotificationChannel(existing)
            }
            return
        }
        val sound = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_NOTIFICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        val channel = NotificationChannel(
            HOUSEHOLD_ALERTS,
            "Household alerts",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = DESCRIPTION
            setSound(sound, attributes)
            enableVibration(true)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        notifications.createNotificationChannel(channel)
    }
}
