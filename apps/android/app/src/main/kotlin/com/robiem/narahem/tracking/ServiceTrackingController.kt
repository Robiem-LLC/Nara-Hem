package com.robiem.narahem.tracking

import android.content.Context
import android.content.Intent
import com.robiem.narahem.data.account.ServerAccountRepository
import com.robiem.narahem.data.household.NativeHouseholdRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** [TrackingController] that starts and stops [HouseholdLocationService]. */
class ServiceTrackingController(context: Context) : TrackingController {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("server", Context.MODE_PRIVATE)
    private val service = Intent(appContext, HouseholdLocationService::class.java)

    /** Sets the resume flag and starts the foreground service if Android allows it. */
    override fun startSharing() {
        prefs.edit().putBoolean("resume-sharing", true).apply()
        try {
            appContext.startForegroundService(service)
        } catch (_: IllegalStateException) {
            // Android may refuse to start a location service from the background; the next app
            // launch retries.
        } catch (_: SecurityException) {}
    }

    /** Clears the resume flag and stops the service. */
    override fun stopSharing() {
        prefs.edit().putBoolean("resume-sharing", false).apply()
        appContext.stopService(service)
    }

    /** Sends the CHECK_IN_NOW action to the service if sharing is on. */
    override fun checkInNow() {
        if (!prefs.getBoolean("resume-sharing", false)) return
        try {
            appContext.startService(Intent(service).setAction("CHECK_IN_NOW"))
        } catch (_: IllegalStateException) {
            // Only possible from the background; the next check-in sends the location anyway.
        }
    }

    /** Sends the STOP_FIND_PHONE action to the service. */
    override fun stopFindPhoneAlarm() {
        appContext.startService(Intent(service).setAction("STOP_FIND_PHONE"))
    }

    /**
     * Reports permissions using the service's stored device, so it works before the UI signs in.
     */
    override suspend fun reportDevicePermissions() = withContext(Dispatchers.IO) {
        val repo = NativeHouseholdRepository(appContext, ServerAccountRepository())
        if (repo.restoreForService()) repo.reportDevicePermissions()
    }
}
