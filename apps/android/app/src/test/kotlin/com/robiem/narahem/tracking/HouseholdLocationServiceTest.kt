package com.robiem.narahem.tracking

import android.Manifest
import android.app.Application
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.location.Location
import android.location.LocationManager
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.FakeAndroidKeyStore
import com.robiem.narahem.data.household.DesktopSodium
import com.robiem.narahem.data.household.FakeHouseholdServer
import com.robiem.narahem.data.household.NativeHouseholdRepository
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.Shadows.shadowOf

/**
 * The background sharing service: when it refuses to start, and how it turns GPS fixes into queued
 * uploads. The service's own HTTP client doesn't trust the fake server's test certificate, so
 * uploads stay queued, which is what these tests look at.
 */
@RunWith(AndroidJUnit4::class)
class HouseholdLocationServiceTest {
    private val context: Application get() = ApplicationProvider.getApplicationContext()
    private val manager get() = context.getSystemService(LocationManager::class.java)
    private val prefs get() = context.getSharedPreferences("server", Context.MODE_PRIVATE)
    private lateinit var fake: FakeHouseholdServer

    @After fun tearDown() = fake.stop()

    @Before fun setUp() {
        DesktopSodium.install()
        FakeAndroidKeyStore.install()
        fake = FakeHouseholdServer()
        fake.start()
    }

    private fun joinedPhone(): NativeHouseholdRepository {
        val repo = NativeHouseholdRepository(context, fake.accounts, fake.client)
        runBlocking { fake.join(repo) }
        return repo
    }

    private fun allowSharing() {
        shadowOf(context).grantPermissions(Manifest.permission.ACCESS_FINE_LOCATION)
        prefs.edit().putBoolean("resume-sharing", true).commit()
    }

    private fun fix(lat: Double, speed: Float = 0f) = Location(LocationManager.GPS_PROVIDER).apply {
        latitude = lat
        longitude = -0.12
        accuracy = 5f
        this.speed = speed
        speedAccuracyMetersPerSecond = 1f
        time = System.currentTimeMillis()
        elapsedRealtimeNanos = System.nanoTime()
    }

    /** Waits up to five seconds for [check] while letting the main looper run. */
    private fun eventually(check: () -> Boolean) {
        val until = System.currentTimeMillis() + 5_000
        while (!check() && System.currentTimeMillis() < until) {
            shadowOf(Looper.getMainLooper()).idle()
            Thread.sleep(20)
        }
        assertTrue(check())
    }

    @Test fun refusesToRunWithoutPermissionConsentOrADevice() {
        val service = Robolectric.buildService(HouseholdLocationService::class.java).create().get()
        service.onStartCommand(Intent(), 0, 1)
        assertTrue(shadowOf(service).isStoppedBySelf)
        allowSharing()
        val noDevice = Robolectric.buildService(HouseholdLocationService::class.java).create().get()
        noDevice.onStartCommand(Intent(), 0, 1)
        assertTrue(shadowOf(noDevice).isStoppedBySelf)
        val stopAlarm = Robolectric.buildService(
            HouseholdLocationService::class.java
        ).create().get()
        stopAlarm.onStartCommand(Intent("STOP_FIND_PHONE"), 0, 1)
        assertTrue(shadowOf(stopAlarm).isStoppedBySelf)
    }

    @Test fun sharingRunsInTheForegroundAndQueuesFixes() {
        val repo = joinedPhone()
        allowSharing()
        val controller = Robolectric.buildService(HouseholdLocationService::class.java).create()
        val service = controller.get()
        service.onStartCommand(Intent(), 0, 1)
        assertNotNull(shadowOf(service).lastForegroundNotification)
        val channels = context.getSystemService(
            NotificationManager::class.java
        ).notificationChannels
        assertTrue(channels.any { it.importance == NotificationManager.IMPORTANCE_MIN })
        eventually {
            manager.let {
                shadowOf(it).getLocationUpdateListeners(LocationManager.GPS_PROVIDER).isNotEmpty()
            }
        }
        assertNotNull(HouseholdLocationService.checkFinderNow)
        shadowOf(manager).simulateLocation(fix(51.5))
        eventually { repo.pendingTrackingCount() >= 1 }
        // A second identical fix right away is skipped by the sampling cadence.
        shadowOf(manager).simulateLocation(fix(51.5))
        shadowOf(Looper.getMainLooper()).idle()
        Thread.sleep(200)
        assertEquals(1, repo.pendingTrackingCount())
        service.onStartCommand(Intent("STOP_FIND_PHONE"), 0, 2)
        controller.destroy()
        assertNull(HouseholdLocationService.checkFinderNow)
        assertTrue(
            shadowOf(manager).getLocationUpdateListeners(LocationManager.GPS_PROVIDER).isEmpty()
        )
    }

    @Test fun turningSharingOffStopsRecording() {
        val repo = joinedPhone()
        allowSharing()
        val controller = Robolectric.buildService(HouseholdLocationService::class.java).create()
        controller.get().onStartCommand(Intent(), 0, 1)
        eventually {
            shadowOf(manager).getLocationUpdateListeners(LocationManager.GPS_PROVIDER).isNotEmpty()
        }
        prefs.edit().putBoolean("resume-sharing", false).commit()
        shadowOf(manager).simulateLocation(fix(51.6))
        shadowOf(Looper.getMainLooper()).idle()
        Thread.sleep(200)
        assertEquals(0, repo.pendingTrackingCount())
        controller.destroy()
    }
}
