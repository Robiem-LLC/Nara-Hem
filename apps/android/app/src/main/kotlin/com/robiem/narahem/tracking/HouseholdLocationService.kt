package com.robiem.narahem.tracking

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import com.robiem.narahem.MainActivity
import com.robiem.narahem.data.account.ServerAccountRepository
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.NativeHouseholdRepository
import com.robiem.narahem.data.household.PlaceMatching
import com.robiem.narahem.data.location.LocalFix
import com.robiem.narahem.data.location.PhoneLocationRepository
import com.robiem.narahem.findphone.FindPhonePlayer
import com.robiem.narahem.findphone.FindPhonePollingPolicy
import com.robiem.narahem.notifications.HouseholdAlertNotifier
import kotlin.math.abs
import kotlin.math.min
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout

/** Notification channel for the low-importance "sharing location" notification. */
private const val SHARING_CHANNEL = "location-sharing-quiet"

/**
 * Foreground service that collects GPS fixes, records trips, uploads encrypted locations and polls
 * for Find My Phone commands. Stops if the device isn't approved instead of sending anything
 * unencrypted.
 */
class HouseholdLocationService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null
    private var deliveryJob: Job? = null
    private var alertsJob: Job? = null
    private var finderJob: Job? = null
    private var permissionsJob: Job? = null
    private var tripIdleJob: Job? = null
    private var tripPlacesJob: Job? = null
    private var watcher: AutoCloseable? = null
    private var sharingRun: SharingRun? = null

    private val wakeLocks = java.util.Collections.synchronizedSet(
        mutableSetOf<PowerManager.WakeLock>()
    )

    private val finderPoll = Mutex()
    private var finder: FindPhonePlayer? = null
    private var destroyingFinder = false
    private var shownProblem: String? = null

    /** Not bindable. */
    override fun onBind(intent: Intent?): IBinder? = null

    /** Returns true if a network is available. */
    private fun online() = getSystemService(ConnectivityManager::class.java).activeNetwork != null

    /**
     * Fetches a pending Find My Phone command, rings or stops accordingly, and reports the result.
     * Errors are ignored so they never interrupt location sharing.
     */
    private suspend fun pollFinder(repo: NativeHouseholdRepository) = finderPoll.withLock {
        if (!online()) return@withLock
        try {
            if (!repo.findPhoneEnabled()) finder?.stop("disabled")
            val command = repo.nextFindPhoneCommand() ?: return@withLock
            if (command.action == "stop") {
                finder?.stop("remote_stop")
                repo.queueFindReport(command.id, "stopped", "remote_stop")
            } else {
                val player = finder ?: FindPhonePlayer(this).also { finder = it }
                val result = player.ring(command.expiresAt) { reason ->
                    val status = if (reason == "audio_error") "failed" else "stopped"
                    if (destroyingFinder || !scope.isActive) {
                        repo.queueFindReport(command.id, status, reason)
                    } else {
                        scope.launch {
                            finderPoll.withLock {
                                repo.queueFindReport(command.id, status, reason)
                                runCatching { repo.flushFindReport() }
                            }
                        }
                    }
                }
                repo.queueFindReport(command.id, result.first, result.second)
            }
            repo.flushFindReport()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {}
    }

    /**
     * Builds the silent foreground notification Android requires while sharing, showing [problem]
     * if there is one.
     */
    private fun sharingNotification(problem: String?): Notification {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return Notification.Builder(this, SHARING_CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentTitle("Sharing location with your household")
            .apply { if (problem != null) setContentText(problem) }
            .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_SERVICE).build()
    }

    /** Updates the foreground notification's text when the problem changes. */
    private fun showSharingProblem(problem: String?) {
        if (problem == shownProblem) return
        shownProblem = problem
        getSystemService(NotificationManager::class.java).notify(1001, sharingNotification(problem))
    }

    /** Replaces the old notification channel with a low-importance one. */
    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        // A channel's importance can't be lowered after creation, so the old channel is replaced.
        manager.deleteNotificationChannel("household-location")
        manager.createNotificationChannel(
            NotificationChannel(
                SHARING_CHANNEL,
                "Location sharing",
                NotificationManager.IMPORTANCE_MIN
            ).apply {
                setShowBadge(false)
            }
        )
    }

    /** Returns true if coarse or fine location permission is granted. */
    private fun allowed(): Boolean =
        checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED ||
            checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    /** Returns true while sharing is enabled in preferences. */
    private fun sharingWanted() =
        getSharedPreferences("server", MODE_PRIVATE).getBoolean("resume-sharing", false)

    /**
     * Starts sharing, or stops a ringing alarm for the STOP_FIND_PHONE action. Stops the service if
     * sharing is off, permission is missing or the device can't be restored.
     */
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "STOP_FIND_PHONE") {
            finder?.stop("user_stopped")
            if (watcher == null) {
                stopSelf()
                return START_NOT_STICKY
            }
            return START_STICKY
        }
        if (intent?.action == "CHECK_IN_NOW") {
            val run = sharingRun
            if (run != null) {
                // A fresh GPS watch reports a fix straight away; send it without waiting.
                scope.launch {
                    runCatching {
                        watch(run)
                        run.repo.flushPendingTracking()
                    }
                }
                return START_STICKY
            }
        }
        if (!allowed() || !sharingWanted() || !showForegroundNotice()) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (watcher != null || job?.isActive == true) return START_STICKY
        val repo = NativeHouseholdRepository(applicationContext, ServerAccountRepository())
        if (!runCatching { repo.restoreForService() }.getOrDefault(false)) {
            stopSelf()
            return START_NOT_STICKY
        }
        startSharing(SharingRun(repo, PhoneLocationRepository(applicationContext)))
        return START_STICKY
    }

    /** Starts the service in the foreground. Returns false if Android refuses. */
    private fun showForegroundNotice(): Boolean {
        val notification = sharingNotification(shownProblem)
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                startForeground(1001, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            } else {
                startForeground(1001, notification)
            }
        } catch (_: SecurityException) {
            return false
        }
        return true
    }

    /** Starts the background loops and GPS updates for a sharing session. */
    private fun startSharing(run: SharingRun) {
        sharingRun = run
        val repo = run.repo
        permissionsJob = scope.launch {
            while (isActive) {
                runCatching { repo.reportDevicePermissions() }
                delay(5 * 60_000L)
            }
        }
        checkFinderNow = { scope.launch { runCatching { pollFinder(repo) } } }
        finderJob = launchFinderLoop(repo)
        alertsJob = launchAlertLoop(repo)
        deliveryJob = launchDeliveryLoop(repo)
        tripPlacesJob = launchPlacesRefresh(run)
        tripIdleJob = launchTripIdleCheck(run)
        job = scope.launch {
            while (isActive) {
                try {
                    watch(run)
                    showSharingProblem(null)
                    break
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Exception) {
                    showSharingProblem("Cannot start GPS; check location permissions/services")
                    delay(15_000L)
                }
            }
        }
    }

    /** Polls for Find My Phone commands on their own schedule, independent of GPS and uploads. */
    private fun launchFinderLoop(repo: NativeHouseholdRepository) = scope.launch {
        while (isActive) {
            try {
                if (!sharingWanted()) break
                val enabled = repo.findPhoneEnabled()
                val connected = online()
                if (connected) pollFinder(repo)
                delay(FindPhonePollingPolicy.interval(enabled, connected))
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                delay(FindPhonePollingPolicy.ERROR_INTERVAL_MS)
            }
        }
    }

    /**
     * Checks for household alerts every 15 minutes in case a push was missed. Errors are ignored.
     */
    private fun launchAlertLoop(repo: NativeHouseholdRepository): Job {
        val alerts = HouseholdAlertNotifier(applicationContext)
        return scope.launch {
            while (isActive) {
                try {
                    if (online()) alerts.show(repo)
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Exception) {}
                delay(15 * 60_000L)
            }
        }
    }

    /**
     * Uploads the offline queue, more often while a backlog remains. Stops the service if sharing
     * is turned off.
     */
    private fun launchDeliveryLoop(repo: NativeHouseholdRepository) = scope.launch {
        while (isActive) {
            var waitMs = 15_000L
            try {
                if (!sharingWanted()) {
                    repo.clearPendingTracking()
                    stopSelf()
                    break
                }
                if (repo.pendingTrackingCount() > 0 && online()) {
                    repo.flushPendingTracking()
                    waitMs = if (repo.pendingTrackingCount() > 0) 5_000L else 15_000L
                }
            } catch (_: TrackingDisabled) {
                stopSelf()
                break
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                waitMs = 30_000L
            }
            delay(waitMs)
        }
    }

    /**
     * Refreshes the saved places used for trip detection every 10 minutes. Errors are ignored;
     * trips are still recorded without places.
     */
    private fun launchPlacesRefresh(run: SharingRun) = scope.launch {
        while (isActive) {
            try {
                val snapshot = run.repo.household()
                run.lock.withLock { run.places = snapshot.places }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {}
            delay(600_000L)
        }
    }

    /**
     * Completes the current trip once the phone has been stationary long enough. Errors are ignored
     * so sharing continues.
     */
    private fun launchTripIdleCheck(run: SharingRun) = scope.launch {
        while (isActive) {
            delay(30_000L)
            try {
                run.lock.withLock {
                    run.trips.completeIfIdle(System.currentTimeMillis())?.let { trip ->
                        run.repo.queueTrip(trip)
                        run.activeTrip = false
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {}
        }
    }

    /** Restarts GPS updates with the session's current interval and power mode. */
    private suspend fun watch(run: SharingRun) = withContext(Dispatchers.Main) {
        val previousWatcher = watcher
        watcher = run.location.watch(
            run.interval,
            run.lowPower,
            onFix = { onFix(run, it) },
            onProblem = { showSharingProblem(it) }
        )
        previousWatcher?.close()
    }

    /**
     * Handles a GPS fix: holds a wake lock, records the fix on the IO dispatcher and uploads
     * immediately unless it can wait for the next batch.
     */
    private fun onFix(run: SharingRun, raw: LocalFix) {
        if (!scope.isActive) return
        // Acquire the wake lock inside Android's callback, before switching to the IO dispatcher.
        val wake = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "NaraHem:location-delivery")
        wake.acquire(120_000L)
        wakeLocks.add(wake)
        scope.launch {
            try {
                withTimeout(90_000L) {
                    val sendNow = run.lock.withLock { record(run, raw) }
                    if (sendNow && online()) {
                        run.repo.flushPendingTracking()
                        showSharingProblem(null)
                    }
                }
            } catch (_: TrackingDisabled) {
                stopSelf()
            } catch (_: TimeoutCancellationException) {
                // It's saved on the phone; the delivery loop retries.
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                // It's saved on the phone; the delivery loop retries.
            } finally {
                wakeLocks.remove(wake)
                runCatching { if (wake.isHeld) wake.release() }
            }
        }
    }

    /**
     * Applies the sampling cadence, updates trip tracking, queues the fix and adjusts the GPS
     * interval. Returns false if the fix can wait for the next batch upload. Must be called while
     * holding [SharingRun.lock].
     */
    private suspend fun record(run: SharingRun, raw: LocalFix): Boolean {
        if (!allowed() || !sharingWanted()) return true
        val now = SystemClock.elapsedRealtime()
        val turn = isTurn(run.previous, raw)
        val motion = run.policy.movementWake(run.previous, raw, System.currentTimeMillis())
        if (!run.cadence.accept(now, turn || motion)) return true
        run.previous = raw
        val capturedAt = raw.capturedAtMillis ?: System.currentTimeMillis()
        if (raw.provider == "gps") run.policy.recordHighAccuracy(now)
        val wasActive = run.activeTrip
        val progress = run.trips.observe(raw, capturedAt, run.places)
        run.activeTrip = progress.active
        val enriched = raw.copy(
            tripMaxSpeedMps = progress.maxSpeedMps,
            tripDistanceMeters = progress.distanceMeters,
            tripStartedAt = progress.startedAt,
            recentTripMaxSpeedMps = progress.recentMaxSpeedMps,
            tripId = progress.tripId
        )
        run.repo.queueLocation(enriched, capturedAt)
        progress.completed?.let { run.repo.queueTrip(it) }
        val observedInterval = run.policy.observe(raw)
        val next = if (run.activeTrip) minOf(15_000L, observedInterval) else observedInterval
        val low = !run.activeTrip && run.policy.preferLowPower(now)
        run.cadence.schedule(now, next)
        if (next != run.interval || low != run.lowPower) {
            run.interval = next
            run.lowPower = low
            watch(run)
        }
        return !run.activeTrip || !wasActive || progress.completed != null
    }

    /** Stops the alarm, GPS, wake locks and every background loop. */
    override fun onDestroy() {
        checkFinderNow = null
        destroyingFinder = true
        finder?.stop("service_stopped")
        finder = null
        watcher?.close()
        watcher = null
        synchronized(wakeLocks) {
            wakeLocks.forEach { runCatching { if (it.isHeld) it.release() } }
            wakeLocks.clear()
        }
        job?.cancel()
        deliveryJob?.cancel()
        alertsJob?.cancel()
        finderJob?.cancel()
        permissionsJob?.cancel()
        tripIdleJob?.cancel()
        tripPlacesJob?.cancel()
        scope.cancel()
        super.onDestroy()
    }

    /** Hook for the FCM service. */
    companion object {
        /** Set while sharing runs: a push asks it to check for a Find My Phone command now. */
        @Volatile var checkFinderNow: (() -> Unit)? = null
    }
}

/** State for one sharing session. Access only while holding [lock]. */
private class SharingRun(
    val repo: NativeHouseholdRepository,
    val location: PhoneLocationRepository
) {
    val lock = Mutex()
    val trips = MotionTripTracker()
    val policy = AdaptiveLocationPolicy()
    val cadence = TrackingCadence()
    var places: List<HouseholdPlace> = emptyList()
    var activeTrip = false
    var previous: LocalFix? = null
    var interval = 15_000L
    var lowPower = false
}

/**
 * Returns true for a heading change of 35 degrees or more after at least 18 m at 2.24 m/s or
 * faster.
 */
private fun isTurn(previous: LocalFix?, raw: LocalFix): Boolean {
    if (previous == null || (raw.speedMps ?: 0f) < 2.24f) return false
    val before = previous.bearingDeg ?: return false
    val after = raw.bearingDeg ?: return false
    val moved = PlaceMatching.distance(
        previous.latitude,
        previous.longitude,
        raw.latitude,
        raw.longitude
    )
    if (moved < 18) return false
    val delta = abs(after - before) % 360f
    return min(delta, 360f - delta) >= 35f
}
