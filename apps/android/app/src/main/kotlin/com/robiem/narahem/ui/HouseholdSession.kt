package com.robiem.narahem.ui

import com.robiem.narahem.data.account.AccountRepository
import com.robiem.narahem.data.account.AccountRequestException
import com.robiem.narahem.data.account.serverOrigin
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.household.HouseholdRepository
import com.robiem.narahem.data.settings.AppSettings
import com.robiem.narahem.data.settings.MapCamera
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * State shared by every screen: the account, the device's setup state, the household data, the
 * running action and its message, and stored phone settings. Created by [AppViewModel]; screen view
 * models read and update it.
 */
class HouseholdSession(
    private val accounts: AccountRepository,
    private val household: HouseholdRepository?,
    private val settings: AppSettings,
    private val scope: CoroutineScope
) {
    private val mutable = MutableStateFlow(AppState())
    val state: StateFlow<AppState> = mutable.asStateFlow()

    /** The current state. Assigning replaces it entirely. */
    var current: AppState
        get() = mutable.value
        set(value) {
            mutable.value = value
        }

    private val phoneSettingsFlow = MutableStateFlow(
        PhoneSettings(settings.mapConsent, settings.addressLookup, settings.mapCamera)
    )

    /** Settings stored on the phone. Kept separate from [state], which resets at sign-out. */
    val phoneSettings = phoneSettingsFlow.asStateFlow()
    private var operation: Job? = null
    private var backgroundRefresh: Job? = null

    /** Server used for the last sign-in. */
    val savedServer: String get() = settings.serverUrl
    private val signOutActions = mutableListOf<() -> Unit>()

    /** Applies [change] to the current state. */
    fun update(change: (AppState) -> AppState) = mutable.update(change)

    /**
     * Runs a user action if none is running. Sets the busy flag and turns failures into a message
     * or field errors.
     */
    fun work(task: suspend () -> Unit) {
        if (mutable.value.busy) return
        mutable.update { it.copy(busy = true, message = "", error = false, fields = emptyMap()) }
        operation = scope.launch {
            try {
                task()
            } catch (timeout: TimeoutCancellationException) {
                mutable.update {
                    it.copy(
                        error = true,
                        message = "Could not get a phone location yet. Check location " +
                            "services, move near a window, and tap Refresh my location."
                    )
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (failure: Exception) {
                mutable.update {
                    it.copy(
                        message = failure.message ?: "Unable to complete this action.",
                        error = true,
                        fields = (failure as? AccountRequestException)?.fields.orEmpty()
                    )
                }
            } finally {
                mutable.update { it.copy(busy = false) }
            }
        }
    }

    /** Re-checks the device's setup state and loads the household once the device is ready. */
    suspend fun refreshTrusted() {
        val account = mutable.value.account ?: return
        val repo = household ?: return
        val status = repo.status(account)
        if (mutable.value.account?.id != account.id) return
        val code = if (status == "pending" || status == "pairing") repo.ownPairingCode() else ""
        mutable.update {
            it.copy(
                deviceStatus = status,
                deviceFingerprint = repo.deviceFingerprint(),
                ownerFingerprint = repo.ownerFingerprint(),
                pairingCode = code,
                sharing = repo.sharingEnabled()
            )
        }
        if (status == "ready") {
            val snapshot = repo.household()
            val choices = repo.sharingChoices()
            val joined = repo.includeNewMembers(choices)
            val audience = repo.sharingAudience()
            val ownerViewerId = repo.ownerViewerId()
            if (mutable.value.account?.id != account.id) return
            mutable.update {
                it.copy(
                    people = snapshot.people,
                    findPhoneEnabled = repo.findPhoneEnabled(),
                    places = snapshot.places,
                    audience = audience,
                    audienceLoaded = true,
                    audienceChoices = choices,
                    ownerViewerId = ownerViewerId,
                    joinedMembers = it.joinedMembers + joined
                )
            }
            // Push registration failures are ignored so they never block household access or
            // location sync.
            try {
                repo.ensureFcmSubscription()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) { /* Retry during next household refresh. */ }
        } else {
            val members = accounts.authenticated("/api/household/members").getJSONArray("members")
            val people = (0 until members.length()).map {
                val member = members.getJSONObject(it)
                HouseholdPerson(member.getString("id"), member.optString("username", "Member"))
            }
            mutable.update { it.copy(people = people, places = emptyList()) }
        }
    }

    /** Registers this phone if needed and determines its setup state. */
    fun prepareDevice(server: String) = work {
        val account = mutable.value.account ?: return@work
        val repo = household ?: return@work
        // An account registered in the app isn't confirmed yet; the code that approves this
        // phone confirms it, so it may register.
        repo.enroll(account, server)
        refreshTrusted()
    }

    /**
     * Reloads the household in the background without setting the busy flag or clearing the current
     * message.
     */
    fun refreshHousehold() {
        if (mutable.value.busy || mutable.value.account == null ||
            backgroundRefresh?.isActive == true
        ) {
            return
        }
        backgroundRefresh = scope.launch {
            try {
                refreshTrusted()
                mutable.update { it.copy(syncProblem = false) }
            } catch (_: CancellationException) {
                throw CancellationException()
            } catch (_: Exception) {
                mutable.update { it.copy(syncProblem = true) }
            }
        }
    }

    /** Clears the "has joined" names once they have been shown. */
    fun clearJoinedMembers() {
        mutable.update { it.copy(joinedMembers = emptyList()) }
    }

    /** Shows an error message. */
    fun showError(text: String) {
        mutable.update { it.copy(message = text, error = true) }
    }

    /** Stores the server for the next sign-in. */
    fun rememberServer(server: String) {
        runCatching { serverOrigin(server).toString().removeSuffix("/") }
            .onSuccess { settings.serverUrl = it }
    }

    /** Stores that the user agreed to location sharing and map tiles. */
    fun acceptMapConsent() {
        settings.mapConsent = true
        phoneSettingsFlow.update { it.copy(mapConsent = true) }
    }

    /** Enables or disables street address lookups. */
    fun setAddressLookup(enabled: Boolean) {
        settings.addressLookup = enabled
        phoneSettingsFlow.update { it.copy(addressLookup = enabled) }
    }

    /** Stores the map position. */
    fun rememberMapCamera(camera: MapCamera) {
        settings.mapCamera = camera
        phoneSettingsFlow.update { it.copy(mapCamera = camera) }
    }

    /** Returns true the first time it is called and records that the prompt was shown. */
    fun takeFirstLaunchLocationPrompt(): Boolean {
        if (settings.locationPrompted) return false
        settings.locationPrompted = true
        return true
    }

    /**
     * Signs out: stops sharing, removes the push token, runs [onSignOut] actions and resets the
     * state.
     */
    fun signOut() {
        household?.clearPendingTracking()
        signOutActions.forEach { it() }
        operation?.cancel()
        backgroundRefresh?.cancel()
        mutable.value = AppState(busy = true, restoring = false)
        operation = scope.launch {
            // Remove the push token before signing out, since that needs the credentials. Sign out
            // locally even if the server is unreachable.
            try {
                household?.unsubscribeFcm()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) { }
            try {
                accounts.signOut()
            } catch (failure: Exception) {
                mutable.update {
                    it.copy(
                        message = "Signed out locally. Server session could not be revoked; " +
                            "it will expire."
                    )
                }
            } finally {
                mutable.update { it.copy(busy = false) }
            }
        }
    }

    /** Registers [action] to run at sign-out, to stop work tied to the account. */
    fun onSignOut(action: () -> Unit) {
        signOutActions += action
    }
}
