package com.robiem.narahem.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.robiem.narahem.data.account.AccountRepository
import com.robiem.narahem.data.household.HouseholdRepository
import com.robiem.narahem.data.settings.AppSettings
import com.robiem.narahem.tracking.TrackingController
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * App-level view model. Owns the [HouseholdSession] shared by the screen view models and handles
 * work that isn't tied to one screen: device setup, background sharing, polling, permissions and
 * messages.
 */
class AppViewModel(
    accounts: AccountRepository,
    household: HouseholdRepository?,
    settings: AppSettings,
    private val tracking: TrackingController
) : ViewModel() {
    val session = HouseholdSession(accounts, household, settings, viewModelScope)
    val state = session.state
    val phoneSettings = session.phoneSettings

    /** Server used for the last sign-in, used to prefill the sign-in form. */
    val savedServer: String get() = session.savedServer

    /** Registers this phone if needed and determines its setup state. */
    fun prepareDevice(server: String) = session.prepareDevice(server)

    /** Records that the user agreed to location sharing and map tiles. */
    fun acceptMapConsent() = session.acceptMapConsent()

    /** Returns true the first time it is called, so location is requested once on first launch. */
    fun takeFirstLaunchLocationPrompt() = session.takeFirstLaunchLocationPrompt()

    /** Stops a ringing Find My Phone alarm. */
    fun stopFindPhoneAlarm() = tracking.stopFindPhoneAlarm()

    /** Clears the message if it is still [expected] and is not an error. */
    fun dismissMessage(expected: String) {
        session.update { if (!it.error && it.message == expected) it.copy(message = "") else it }
    }

    /** Shows a message after location permission is denied. */
    fun permissionDenied() {
        session.update {
            it.copy(
                message = "Location permission was denied. You can still view the map.",
                error = true
            )
        }
    }

    /**
     * Starts or stops the background location service to match consent, location permission and the
     * device's setup state.
     */
    fun syncBackgroundSharing(hasLocation: Boolean) {
        val current = session.current
        val account = current.account ?: return
        // Device status is "register" while trust is being restored after the activity is
        // recreated, so don't stop a running tracker then.
        if (current.deviceStatus != "ready") return
        if (session.phoneSettings.value.mapConsent && current.sharing && hasLocation &&
            account.role != "admin"
        ) {
            tracking.startSharing()
        } else {
            tracking.stopSharing()
        }
    }

    /** Reports this phone's permission state to the server. No location data is sent. */
    fun reportDevicePermissions() {
        viewModelScope.launch { runCatching { tracking.reportDevicePermissions() } }
    }

    /**
     * Called once the "has joined" message is shown: clears it and sends this phone's location
     * now, so the new members see it without waiting for the next check-in.
     */
    fun joinedMembersShown() {
        session.clearJoinedMembers()
        tracking.checkInNow()
    }

    /**
     * Refreshes the household until cancelled: every 15 seconds while the map is showing, as on
     * the iPhone, so people move in small steps; otherwise every 30.
     */
    suspend fun refreshHouseholdWhileOpen(mapShowing: () -> Boolean = { false }): Nothing {
        while (true) {
            delay(if (mapShowing()) 15_000 else 30_000)
            session.refreshHousehold()
        }
    }
}
