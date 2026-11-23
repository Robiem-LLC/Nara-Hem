package com.robiem.narahem.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.robiem.narahem.data.account.AccountRepository
import com.robiem.narahem.data.account.ContactDetails
import com.robiem.narahem.data.account.USERNAME_RULE
import com.robiem.narahem.data.account.tidyUsername
import com.robiem.narahem.data.account.validateServer
import com.robiem.narahem.data.household.HouseholdRepository
import com.robiem.narahem.tracking.TrackingController
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.HouseholdSession
import kotlinx.coroutines.launch

/** View model for the Settings tab: device setup, sharing, Find My Phone, profile and account. */
class SettingsViewModel(
    private val session: HouseholdSession,
    private val accounts: AccountRepository,
    private val household: HouseholdRepository?,
    private val tracking: TrackingController
) : ViewModel(),
    SettingsEvents {
    /** Runs [task] through [HouseholdSession.work]. */
    private fun work(task: suspend () -> Unit) = session.work(task)

    /** Re-checks the device's setup state. */
    override fun prepareDevice(server: String) = session.prepareDevice(server)

    /** Stops a ringing alarm. */
    override fun stopFindPhoneAlarm() = tracking.stopFindPhoneAlarm()

    /** Enables or disables address lookups. */
    override fun setAddressLookup(enabled: Boolean) = session.setAddressLookup(enabled)

    /** Shows a photo error message. */
    fun photoError(text: String) = session.showError(text)

    /** Returns the account's email address and phone number. */
    override suspend fun contactDetails(): ContactDetails = accounts.contactDetails()

    /** Sends a code to a new email address or phone number. */
    override suspend fun requestContactChange(
        value: String,
        password: String,
        phone: Boolean
    ): String = accounts.requestContactChange(value, password, phone)

    /** Uses the new email address or phone number and says so. */
    override suspend fun confirmContactChange(code: String) {
        accounts.confirmContactChange(code)
        session.update { it.copy(message = "Your sign-in details were updated.", error = false) }
    }

    /** Saves the Find My Phone setting and reports it to the server. */
    override fun setFindPhone(enabled: Boolean) = work {
        if (!enabled) tracking.stopFindPhoneAlarm()
        household?.setFindPhoneEnabled(enabled)
        viewModelScope.launch { runCatching { household?.reportDevicePermissions() } }
        session.update {
            it.copy(
                findPhoneEnabled = enabled,
                message = if (enabled) {
                    "Find my phone enabled while background sharing is running. " +
                        "Test its sound and DND settings."
                } else {
                    "Find my phone disabled."
                }
            )
        }
    }

    /** Requests the phone approval email. */
    override fun requestPhoneCode() = work {
        household?.sendPhoneCode()
        session.update {
            it.copy(message = "Six-digit code sent to your email or phone. Expires in ten minutes.")
        }
    }

    /** Submits the approval code and refreshes the device state. */
    override fun confirmPhoneCode(code: String) = work {
        household?.verifyPhoneCode(code)
        session.refreshTrusted()
    }

    /** Discards the pending registration and registers again. */
    override fun restartPhoneRegistration(server: String) = work {
        val account = session.current.account ?: return@work
        household?.discardPendingPhone()
        household?.enroll(account, server)
        session.refreshTrusted()
    }

    /** Stops sharing, revokes this phone on the server and signs out. */
    override fun revokeThisPhone() {
        tracking.stopSharing()
        if (session.current.busy) return
        session.update { it.copy(busy = true, message = "", error = false) }
        viewModelScope.launch {
            try {
                household?.revokeOwnPhone()
                accounts.signOut()
                session.current = AppState(restoring = false)
            } catch (failure: Exception) {
                session.update {
                    it.copy(
                        message = failure.message ?: "Could not revoke this phone.",
                        error = true,
                        busy = false
                    )
                }
            }
        }
    }

    /** Validates and saves a new display name. */
    override fun changeUsername(username: String) = work {
        val proposed = requireNotNull(tidyUsername(username)) { USERNAME_RULE }
        val reply = accounts.authenticated(
            "/api/account/username",
            org.json.JSONObject().put("username", proposed),
            "PUT"
        )
        val updated = reply.getString("username")
        // Re-save the profile photo under the new name, so phones on older app versions, which
        // show the profile's name, see the change too. Best effort.
        val own = session.current.people.firstOrNull { it.id == session.current.account?.id }
        own?.photo?.let { photo -> runCatching { household?.saveProfilePhoto(updated, photo) } }
        session.update { state ->
            state.copy(
                account = state.account?.copy(name = updated),
                message = "Username updated to $updated."
            )
        }
        session.refreshTrusted()
    }

    /** Requests the first-device email code. */
    override fun sendBootstrapCode() = work {
        household?.sendFirstDeviceCode()
        session.update {
            it.copy(message = "Six-digit verification code sent to the administrator email.")
        }
    }

    /** Registers the first device and refreshes. */
    override fun finishBootstrap(code: String) = work {
        household?.bootstrapWithEmail(code)
        session.refreshTrusted()
    }

    /** Pins the household root key from a confirmed fingerprint. */
    override fun verifyHousehold(fingerprint: String) = work {
        household?.verifyOwnerFingerprint(fingerprint)
        session.refreshTrusted()
    }

    /**
     * Enables or disables sharing on the server and reports the change. The background service
     * follows through [AppViewModel.syncBackgroundSharing].
     */
    override fun setSharing(enabled: Boolean) = work {
        if (!enabled) session.update { it.copy(sharing = false) }
        household?.setSharing(enabled)
        viewModelScope.launch { runCatching { household?.reportDevicePermissions() } }
        session.update {
            it.copy(
                sharing = enabled,
                message = if (enabled) {
                    "Sharing this phone's location is on."
                } else {
                    "Sharing paused. Your current map marker is hidden."
                }
            )
        }
    }

    /** Saves which accounts can see this phone's location. */
    fun setSharingAudience(ids: Set<String>) = work {
        val others = ids - (session.current.account?.id ?: "")
        if (others == session.current.audience - (session.current.account?.id ?: "")) return@work
        check(
            session.current.audienceLoaded &&
                others.all { id ->
                    session.current.audienceChoices.any { it.id == id } ||
                        id == session.current.ownerViewerId
                }
        ) { "Refresh location visibility choices first." }
        check(!session.current.syncProblem) { "Refresh household members before changing sharing." }
        household?.setSharingAudience(others)
        session.update {
            it.copy(
                audience = others,
                message = "Who can see this phone has been updated. New location fixes use " +
                    "your selection."
            )
        }
    }

    /** Adds or removes the admin browser from the audience. */
    override fun setOwnerBrowserAccess(enabled: Boolean) = work {
        val owner =
            session.current.ownerViewerId
                ?: error("No approved household owner viewer is available.")
        check(session.current.audienceLoaded && !session.current.syncProblem) {
            "Refresh location sharing before changing owner access."
        }
        val targets = if (enabled) {
            session.current.audience + owner
        } else {
            session.current.audience -
                owner
        }
        household?.setSharingAudience(targets)
        session.update {
            it.copy(
                audience = targets,
                message = if (enabled) {
                    "Your household owner's approved browser can now see new locations from " +
                        "this phone."
                } else {
                    "Your household owner's browser won't receive new locations from this " +
                        "phone. Earlier received locations remain."
                }
            )
        }
    }

    /** Publishes a new profile photo. */
    fun saveProfilePhoto(photo: String) = work {
        val account = session.current.account ?: error("Sign in first")
        household?.saveProfilePhoto(account.name, photo)
        session.refreshTrusted()
        session.update { it.copy(message = "Your photo has been saved for the household map.") }
    }

    /** Signs out. */
    override fun signOut() {
        tracking.stopSharing()
        session.signOut()
    }

    /** Requests a new email confirmation link for the signed-in account. */
    override fun resendEmailConfirmation(server: String, email: String) = work {
        validateServer(server)
        val message = accounts.requestEnrollment(server, email)
        session.update { it.copy(onboarding = "enroll", message = message) }
    }
}
