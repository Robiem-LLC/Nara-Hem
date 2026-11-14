package com.robiem.narahem.ui.settings

import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import com.robiem.narahem.data.account.ContactDetails

/** Actions the Settings screen can trigger. Implemented by [SettingsViewModel]. */
interface SettingsEvents {
    /** Enables or disables Find My Phone. */
    fun setFindPhone(enabled: Boolean)

    /** Stops a ringing alarm. */
    fun stopFindPhoneAlarm()

    /** Emails the code that approves this phone. */
    fun requestPhoneCode()

    /** Submits the emailed approval code. */
    fun confirmPhoneCode(code: String)

    /** Discards an unfinished phone registration and starts again. */
    fun restartPhoneRegistration(server: String)

    /** Re-checks this phone's setup state. */
    fun prepareDevice(server: String)

    /** Permanently revokes this phone. */
    fun revokeThisPhone()

    /** Changes the account's display name. */
    fun changeUsername(username: String)

    /** Emails the code for registering a new household's first device. */
    fun sendBootstrapCode()

    /** Registers the first device with the emailed code. */
    fun finishBootstrap(code: String)

    /** Legacy recovery: trusts the household root key after confirming its fingerprint. */
    fun verifyHousehold(fingerprint: String)

    /** Enables or disables location sharing. */
    fun setSharing(enabled: Boolean)

    /** Adds or removes the admin's browser from this phone's audience. */
    fun setOwnerBrowserAccess(enabled: Boolean)

    /** Enables or disables street address lookups. */
    fun setAddressLookup(enabled: Boolean)

    /** Sends the email confirmation link again. */
    fun resendEmailConfirmation(server: String, email: String)

    /** Signs out. */
    fun signOut()

    /** Returns the account's email address and phone number, and whether the server can text. */
    suspend fun contactDetails(): ContactDetails = ContactDetails(null, null, false)

    /** Sends a code to a new email address or phone number. Returns where it went. */
    suspend fun requestContactChange(value: String, password: String, phone: Boolean): String =
        error("Changing your email or phone isn't available.")

    /** Uses the new email address or phone number once its code is entered. */
    suspend fun confirmContactChange(code: String) {
        error("Changing your email or phone isn't available.")
    }
}
