package com.robiem.narahem.tracking

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build

/** Restarts location sharing after a reboot or app update, without opening the UI. */
class TrackingBootReceiver : BroadcastReceiver() {
    /** Starts the sharing service if sharing was enabled and permissions still allow it. */
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED &&
            intent.action != Intent.ACTION_MY_PACKAGE_REPLACED
        ) {
            return
        }
        val prefs = context.getSharedPreferences("server", Context.MODE_PRIVATE)
        val location =
            context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED ||
                context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED
        val background = Build.VERSION.SDK_INT < 29 ||
            context.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        if (!TrackingResumePolicy.permits(
                prefs.getBoolean("resume-sharing", false),
                prefs.getBoolean("map-consent", false),
                location,
                background
            )
        ) {
            return
        }
        try {
            context.startForegroundService(Intent(context, HouseholdLocationService::class.java))
        } catch (_: IllegalStateException) {} catch (_: SecurityException) {
            // A boot receiver must never open UI or request permissions.
        }
    }
}
