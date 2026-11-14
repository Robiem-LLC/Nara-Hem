package com.robiem.narahem.findphone

import android.app.Application
import android.app.NotificationManager
import android.content.Intent
import android.media.AudioManager
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf
import org.robolectric.shadows.ShadowMediaPlayer
import org.robolectric.shadows.util.DataSource

/** The Find My Phone alarm: Do Not Disturb, audio focus, volume and the ways it stops. */
@RunWith(AndroidJUnit4::class)
class FindPhonePlayerTest {
    private val context: Application get() = ApplicationProvider.getApplicationContext()
    private val audio get() = context.getSystemService(AudioManager::class.java)
    private val notifications get() = context.getSystemService(NotificationManager::class.java)
    private val stops = mutableListOf<String>()
    private val expires get() = System.currentTimeMillis() / 1000 + 60

    @After fun tearDown() = ShadowMediaPlayer.resetStaticState()

    /** Lets Robolectric's MediaPlayer play the siren file the player writes. */
    private fun sirenPlays() = ShadowMediaPlayer.addMediaInfo(
        DataSource.toDataSource(File(context.noBackupFilesDir, "find-phone-siren-v1.wav").path),
        ShadowMediaPlayer.MediaInfo(5_000, 0)
    )

    @Test fun ringsAtFullVolumeAndRestoresItWhenStopped() {
        sirenPlays()
        shadowOf(audio).setStreamMaxVolume(7)
        audio.setStreamVolume(AudioManager.STREAM_ALARM, 2, 0)
        val player = FindPhonePlayer(context)
        assertEquals("ringing" to "", player.ring(expires) { stops += it })
        assertTrue(FindPhonePlayer.isRinging)
        assertEquals(7, audio.getStreamVolume(AudioManager.STREAM_ALARM))
        assertEquals(1, shadowOf(notifications).allNotifications.size)
        context.sendBroadcast(Intent(Intent.ACTION_USER_PRESENT))
        shadowOf(Looper.getMainLooper()).idle()
        assertEquals(listOf("user_stopped"), stops)
        assertFalse(FindPhonePlayer.isRinging)
        assertEquals(2, audio.getStreamVolume(AudioManager.STREAM_ALARM))
        assertTrue(shadowOf(notifications).allNotifications.isEmpty())
    }

    @Test fun stopsByItselfWhenTheCommandExpires() {
        sirenPlays()
        val player = FindPhonePlayer(context)
        player.ring(System.currentTimeMillis() / 1000 + 1) { stops += it }
        shadowOf(Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(2))
        assertEquals(listOf("timeout"), stops)
    }

    @Test fun totalSilenceAndRefusedAudioFocusBlockTheAlarm() {
        sirenPlays()
        val player = FindPhonePlayer(context)
        shadowOf(notifications).setNotificationPolicyAccessGranted(true)
        notifications.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_NONE)
        assertEquals("blocked" to "dnd", player.ring(expires) {})
        notifications.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_PRIORITY)
        notifications.notificationPolicy = NotificationManager.Policy(0, 0, 0)
        assertEquals("blocked" to "dnd", player.ring(expires) {})
        notifications.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_ALL)
        shadowOf(audio).setNextFocusRequestResponse(AudioManager.AUDIOFOCUS_REQUEST_FAILED)
        assertEquals("blocked" to "audio_focus", player.ring(expires) {})
        assertFalse(FindPhonePlayer.isRinging)
    }

    @Test fun unplayableAudioIsReportedAsFailed() {
        val player = FindPhonePlayer(context)
        assertEquals("failed" to "audio_error", player.ring(expires) { stops += it })
        assertFalse(FindPhonePlayer.isRinging)
        assertNull(stops.firstOrNull())
    }
}
