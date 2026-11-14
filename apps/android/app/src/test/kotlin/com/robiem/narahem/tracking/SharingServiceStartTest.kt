package com.robiem.narahem.tracking

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.Intent
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf

/** Starting and stopping the background sharing service. */
@RunWith(AndroidJUnit4::class)
class SharingServiceStartTest {
    private val context: Application get() = ApplicationProvider.getApplicationContext()
    private val prefs get() = context.getSharedPreferences("server", Context.MODE_PRIVATE)
    private val started get() = shadowOf(context).nextStartedService

    private fun boot(action: String = Intent.ACTION_BOOT_COMPLETED) =
        TrackingBootReceiver().onReceive(context, Intent(action))

    @Test fun bootRestartsSharingOnlyWithConsentAndPermission() {
        boot()
        assertNull(started)
        prefs.edit().putBoolean("resume-sharing", true).putBoolean("map-consent", true).commit()
        boot()
        assertNull(started)
        shadowOf(context).grantPermissions(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_BACKGROUND_LOCATION
        )
        boot(Intent.ACTION_SCREEN_ON)
        assertNull(started)
        boot(Intent.ACTION_MY_PACKAGE_REPLACED)
        assertEquals(HouseholdLocationService::class.java.name, started!!.component!!.className)
    }

    @Test fun controllerStartsAndStopsTheService() = runBlocking {
        val controller = ServiceTrackingController(context)
        controller.startSharing()
        assertTrue(prefs.getBoolean("resume-sharing", false))
        assertEquals(HouseholdLocationService::class.java.name, started!!.component!!.className)
        controller.stopFindPhoneAlarm()
        assertEquals("STOP_FIND_PHONE", started!!.action)
        controller.stopSharing()
        assertFalse(prefs.getBoolean("resume-sharing", true))
        assertEquals(
            HouseholdLocationService::class.java.name,
            shadowOf(context).nextStoppedService.component!!.className
        )
        // Without a stored device there is nothing to report.
        controller.reportDevicePermissions()
    }
}
