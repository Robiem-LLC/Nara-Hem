package com.robiem.narahem.notifications

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import com.robiem.narahem.MainActivity
import com.robiem.narahem.data.household.NativeHouseholdRepository
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray

/**
 * Shows arrival and departure alerts about other members. Triggered by a data-only FCM push, with a
 * periodic check from the sharing service as a fallback. Alert text comes from the household
 * server, never from Google or the relay.
 */
class HouseholdAlertNotifier(private val context: Context) {
    private val prefs = context.getSharedPreferences("household-alerts", Context.MODE_PRIVATE)

    /** Fetches new alerts and posts a notification for each one not shown before. */
    suspend fun show(repo: NativeHouseholdRepository) = lock.withLock {
        val self = repo.accountId() ?: return@withLock
        val now = System.currentTimeMillis()
        val seen = prefs.getString("seen", null)?.let { runCatching { JSONArray(it) }.getOrNull() }
            ?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()
        val fresh = repo.recentAlerts(now - STALE_MS)
            .filter {
                it.accountId != self && it.eventId !in seen && now - it.capturedAt <= STALE_MS
            }
            .sortedBy { it.capturedAt }
        if (fresh.isEmpty()) return@withLock
        prefs.edit().putString(
            "seen",
            JSONArray(
                (
                    seen + fresh.map {
                        it.eventId
                    }
                    ).takeLast(200)
            ).toString()
        ).apply()
        NaraHemNotificationChannels.ensure(context)
        val manager = context.getSystemService(NotificationManager::class.java)
        if (!manager.areNotificationsEnabled()) return@withLock
        val open = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val hidden = Notification.Builder(context, NaraHemNotificationChannels.HOUSEHOLD_ALERTS)
            .setSmallIcon(
                android.R.drawable.ic_menu_mylocation
            ).setContentTitle("Household alert").build()
        for (alert in fresh) {
            val text = alert.text
            val note = Notification.Builder(context, NaraHemNotificationChannels.HOUSEHOLD_ALERTS)
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .setContentTitle(text)
                .setStyle(Notification.BigTextStyle().bigText(text))
                .setWhen(alert.capturedAt).setShowWhen(true)
                .setContentIntent(open).setAutoCancel(true)
                .setVisibility(Notification.VISIBILITY_PRIVATE).setPublicVersion(hidden)
                .build()
            try {
                manager.notify(alert.eventId, 2001, note)
            } catch (_: SecurityException) {
                return@withLock
            }
        }
    }

    /** Lock shared by the FCM service and the sharing service, which run in the same process. */
    companion object {
        private val lock = Mutex()
        private const val STALE_MS = 15 * 60_000L // an alert this old is old news
    }
}
