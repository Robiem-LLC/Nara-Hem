package com.robiem.narahem.notifications

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.robiem.narahem.data.account.ServerAccountRepository
import com.robiem.narahem.data.household.NativeHouseholdRepository
import com.robiem.narahem.tracking.HouseholdLocationService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Receives FCM pushes and token updates. Pushes carry no content; the app fetches alerts and
 * commands from its own server. Tokens are only uploaded to that server.
 */
class NaraHemFirebaseMessagingService : FirebaseMessagingService() {
    /** Creates the notification channels. */
    override fun onCreate() {
        super.onCreate()
        NaraHemNotificationChannels.ensure(this)
    }

    /**
     * Handles a data-only alert push: shows new household alerts and checks for a Find My Phone
     * command.
     */
    override fun onMessageReceived(message: RemoteMessage) {
        if (message.data["intent"] != "alert") return
        runBlocking(Dispatchers.IO) {
            withTimeoutOrNull(9_000L) {
                try {
                    HouseholdLocationService.checkFinderNow?.invoke()
                    val repo =
                        NativeHouseholdRepository(applicationContext, ServerAccountRepository())
                    if (repo.restoreForService()) {
                        HouseholdAlertNotifier(applicationContext).show(repo)
                    }
                } catch (cancelled: kotlinx.coroutines.CancellationException) {
                    throw cancelled
                } catch (_: Exception) {}
            }
        }
    }

    /**
     * Uploads a new FCM token if this device is approved; otherwise it is uploaded on the next
     * refresh.
     */
    @Suppress("DEPRECATION") // FCM token callback still supported by the selected SDK.
    override fun onNewToken(token: String) {
        super.onNewToken(token)
        if (!applicationContext.getSharedPreferences("server", MODE_PRIVATE)
                .getBoolean("fcm-signed-in", false)
        ) {
            return
        }
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try {
                val repo = NativeHouseholdRepository(
                    applicationContext,
                    ServerAccountRepository(context = applicationContext)
                )
                if (repo.restoreForService()) repo.registerFcmSubscription(token)
            } catch (_: Exception) {}
        }
    }
}
