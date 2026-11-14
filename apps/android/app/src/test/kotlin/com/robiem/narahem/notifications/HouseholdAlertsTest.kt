package com.robiem.narahem.notifications

import android.app.Application
import android.app.NotificationManager
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.FakeAndroidKeyStore
import com.robiem.narahem.data.household.DesktopSodium
import com.robiem.narahem.data.household.FakeHouseholdServer
import com.robiem.narahem.data.household.NativeHouseholdRepository
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf

/** Arrival and departure notifications, fetched from the fake household server. */
@RunWith(AndroidJUnit4::class)
class HouseholdAlertsTest {
    private val context: Application get() = ApplicationProvider.getApplicationContext()
    private val manager get() = context.getSystemService(NotificationManager::class.java)
    private lateinit var fake: FakeHouseholdServer
    private lateinit var repo: NativeHouseholdRepository

    @After fun tearDown() = fake.stop()

    @Before fun setUp() {
        DesktopSodium.install()
        FakeAndroidKeyStore.install()
        fake = FakeHouseholdServer()
        fake.start()
        repo = NativeHouseholdRepository(context, fake.accounts, fake.client)
        runBlocking { fake.join(repo) }
    }

    private fun alert(id: String, account: String, ageMs: Long, text: String) = JSONObject()
        .put("id", id).put("account_id", account)
        .put("captured_at", System.currentTimeMillis() - ageMs).put("text", text)

    @Test fun channelIsCreatedOnceAndItsDescriptionKeptCurrent() {
        NaraHemNotificationChannels.ensure(context)
        val channel = manager.getNotificationChannel(NaraHemNotificationChannels.HOUSEHOLD_ALERTS)
        assertEquals(NotificationManager.IMPORTANCE_HIGH, channel.importance)
        channel.description = "Old text"
        manager.createNotificationChannel(channel)
        NaraHemNotificationChannels.ensure(context)
        assertTrue(
            manager.getNotificationChannel(NaraHemNotificationChannels.HOUSEHOLD_ALERTS)
                .description.startsWith("When a household member")
        )
    }

    @Test fun eachFreshAlertAboutSomeoneElseIsShownOnce() = runBlocking {
        fake.alerts = JSONArray()
            .put(alert("1", fake.ownerAccount, 60_000, "Alex arrived at Home"))
            .put(alert("2", fake.phoneAccount, 60_000, "You left School"))
            .put(alert("3", fake.ownerAccount, 20 * 60_000, "Alex left Work"))
        val notifier = HouseholdAlertNotifier(context)
        notifier.show(repo)
        val shown = shadowOf(manager).allNotifications
        assertEquals(1, shown.size)
        assertEquals("Alex arrived at Home", shown.single().extras.getString("android.title"))
        notifier.show(repo)
        assertEquals(1, shadowOf(manager).allNotifications.size)
    }

    @Test fun nothingIsShownWhenNotificationsAreOff() = runBlocking {
        shadowOf(manager).setNotificationsEnabled(false)
        fake.alerts = JSONArray().put(alert("9", fake.ownerAccount, 1_000, "Alex arrived"))
        HouseholdAlertNotifier(context).show(repo)
        assertTrue(shadowOf(manager).allNotifications.isEmpty())
    }
}
