package com.robiem.narahem.findphone

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import com.robiem.narahem.tracking.HouseholdLocationService

/**
 * Plays the Find My Phone alarm at full alarm volume for a limited time. Uses Do Not Disturb access
 * when granted but never changes the Do Not Disturb policy.
 */
class FindPhonePlayer(private val context: Context) {
    private val handler = Handler(Looper.getMainLooper())
    private val audio = context.getSystemService(AudioManager::class.java)
    private val notifications = context.getSystemService(NotificationManager::class.java)
    private var player: MediaPlayer? = null
    private var focus: AudioFocusRequest? = null
    private var originalVolume: Int? = null
    private var alarmVolume: Int? = null
    private var onStopped: ((String) -> Unit)? = null

    // Stops on ACTION_USER_PRESENT (keyguard dismissed). Turning the screen on must not stop the
    // alarm.
    private val unlockReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            // "user_stopped" must match a reason the server's FindReportInput accepts.
            if (intent?.action == Intent.ACTION_USER_PRESENT) stop("user_stopped")
        }
    }

    private var listeningForUnlock = false

    /** Returns the system vibrator using the API available on this Android version. */
    @Suppress("DEPRECATION")
    private val vibrator: Vibrator get() = if (Build.VERSION.SDK_INT >= 31) {
        context.getSystemService(VibratorManager::class.java).defaultVibrator
    } else {
        context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
    }

    /** Registers a receiver that stops the alarm when the phone is unlocked. */
    private fun listenForUnlock() {
        if (listeningForUnlock) return
        context.registerReceiver(unlockReceiver, IntentFilter(Intent.ACTION_USER_PRESENT))
        listeningForUnlock = true
    }

    /** Returns the siren WAV file in the cache directory, writing it on first use. */
    private fun sirenFile(): java.io.File {
        val wav = FindPhoneTone.wav()
        val file = java.io.File(context.noBackupFilesDir, "find-phone-siren-v1.wav")
        if (file.length() != wav.size.toLong()) file.writeBytes(wav)
        return file
    }

    /**
     * Starts the alarm and vibration until stopped, unlocked or expired. Returns the status and
     * reason to report to the server; [onStop] is called with the stop reason.
     */
    @Synchronized fun ring(expiresAt: Long, onStop: (String) -> Unit): Pair<String, String> {
        stop("remote_stop")
        val filter = notifications.currentInterruptionFilter
        if (filter == NotificationManager.INTERRUPTION_FILTER_NONE) return "blocked" to "dnd"
        val policy = runCatching { notifications.notificationPolicy }.getOrNull()
        if (filter == NotificationManager.INTERRUPTION_FILTER_PRIORITY && policy != null &&
            (policy.priorityCategories and NotificationManager.Policy.PRIORITY_CATEGORY_ALARMS) == 0
        ) {
            return "blocked" to
                "dnd"
        }
        val attributes = AudioAttributes.Builder().setUsage(
            AudioAttributes.USAGE_ALARM
        ).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build()
        try {
            val request = AudioFocusRequest.Builder(
                AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE
            ).setAudioAttributes(attributes)
                .setOnAudioFocusChangeListener({ change ->
                    if (change < 0) stop("audio_focus")
                }, handler).build()
            if (audio.requestAudioFocus(request) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
                return "blocked" to "audio_focus"
            }
            focus = request
            originalVolume = audio.getStreamVolume(AudioManager.STREAM_ALARM)
            alarmVolume = audio.getStreamMaxVolume(AudioManager.STREAM_ALARM)
            audio.setStreamVolume(AudioManager.STREAM_ALARM, alarmVolume!!, 0)
            val active = MediaPlayer()
            player = active
            active.setAudioAttributes(attributes)
            val siren = runCatching { sirenFile() }.getOrNull()
            if (siren != null) {
                active.setDataSource(siren.path)
            } else {
                active.setDataSource(
                    context,
                    RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                        ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
                )
            }
            active.isLooping = true
            active.setWakeMode(context, PowerManager.PARTIAL_WAKE_LOCK)
            active.setOnErrorListener { _, _, _ ->
                stop("audio_error")
                true
            }
            active.prepare()
            active.start()
            onStopped = onStop
            isRinging = true
            listenForUnlock()
            vibrator.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 500, 300), 0))
            notifications.createNotificationChannel(
                NotificationChannel(
                    "find-phone",
                    "Find my phone",
                    NotificationManager.IMPORTANCE_HIGH
                ).apply {
                    setSound(null, null)
                }
            )
            val stop = PendingIntent.getService(
                context,
                91,
                Intent(context, HouseholdLocationService::class.java).setAction("STOP_FIND_PHONE"),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
            notifications.notify(
                1002,
                Notification.Builder(
                    context,
                    "find-phone"
                ).setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
                    .setContentTitle(
                        "Find my phone"
                    ).setContentText(
                        "Tap or swipe away this alert to stop ringing"
                    ).setCategory(Notification.CATEGORY_ALARM)
                    .setContentIntent(
                        stop
                    ).setDeleteIntent(
                        stop
                    ).setAutoCancel(
                        true
                    ).setOngoing(
                        false
                    ).addAction(Notification.Action.Builder(null, "Stop", stop).build()).build()
            )
            handler.postDelayed({
                stop("timeout")
            }, (expiresAt * 1000 - System.currentTimeMillis()).coerceIn(1, 60000))
            return "ringing" to
                if (filter == NotificationManager.INTERRUPTION_FILTER_PRIORITY && policy == null) {
                    "dnd_unknown"
                } else {
                    ""
                }
        } catch (_: SecurityException) {
            stop("dnd")
            return "blocked" to "dnd"
        } catch (_: Exception) {
            stop("audio_error")
            return "failed" to "audio_error"
        }
    }

    /** Stops the alarm and restores the previous alarm volume. */
    @Synchronized fun stop(reason: String) {
        handler.removeCallbacksAndMessages(null)
        val callback = onStopped
        onStopped = null
        isRinging = false
        if (listeningForUnlock) {
            listeningForUnlock = false
            runCatching { context.unregisterReceiver(unlockReceiver) }
        }
        runCatching { player?.stop() }
        runCatching { player?.release() }
        player = null
        runCatching { vibrator.cancel() }
        runCatching { notifications.cancel(1002) }
        val before = originalVolume
        val changed = alarmVolume
        if (before != null && changed != null) {
            runCatching {
                if (audio.getStreamVolume(AudioManager.STREAM_ALARM) == changed) {
                    audio.setStreamVolume(AudioManager.STREAM_ALARM, before, 0)
                }
            }
        }
        originalVolume = null
        alarmVolume = null
        val oldFocus = focus
        focus = null
        oldFocus?.let { runCatching { audio.abandonAudioFocusRequest(it) } }
        callback?.invoke(reason)
    }

    /** Ringing state shared with the activity. */
    companion object {
        @Volatile var isRinging: Boolean = false
            private set
    }
}
