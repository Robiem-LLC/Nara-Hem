package com.robiem.narahem.data.household

import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.location.LocalFix
import com.robiem.narahem.data.trips.TripHistory

/**
 * Access to the encrypted household: this device's enrollment state, members and places, sharing
 * settings, location publishing and trips. [NativeHouseholdRepository] is the production
 * implementation; tests use an in-memory fake.
 */
interface HouseholdRepository {
    /**
     * Returns this device's setup state, such as "register", "verify-email", "email-code",
     * "first-device", "pairing", "ready" or "revoked".
     */
    suspend fun status(account: Account): String

    /** Generates this device's keys and registers it with the server. */
    suspend fun enroll(account: Account, server: String)

    /**
     * Returns the six-digit pairing code derived from this device's registration and the household
     * root key.
     */
    suspend fun ownPairingCode(): String

    /** Returns the hash of this device's registration, for manual comparison. */
    fun deviceFingerprint(): String

    /** Returns the hash of the household root key, for manual comparison. */
    fun ownerFingerprint(): String

    /** Asks the server to email the six-digit code that approves this phone. */
    suspend fun sendPhoneCode()

    /** Submits the emailed code and loads the signed roster that now includes this phone. */
    suspend fun verifyPhoneCode(code: String)

    /** Cancels an unfinished phone registration on the server and locally. */
    suspend fun discardPendingPhone()

    /** Permanently revokes this phone on the server and deletes its keys. */
    suspend fun revokeOwnPhone()

    /**
     * For a new household, asks the server to email the admin a code for registering the first
     * device.
     */
    suspend fun sendFirstDeviceCode()

    /** Registers the household's first device using the emailed code and signs the first roster. */
    suspend fun bootstrapWithEmail(code: String)

    /** Legacy recovery: trusts the household root key after the user confirms its fingerprint. */
    suspend fun verifyOwnerFingerprint(fingerprint: String)

    /**
     * Reports this phone's OS permission state to the server when it changes, or every six hours.
     */
    suspend fun reportDevicePermissions()

    /** Uploads the current FCM push token if the server doesn't have it yet. */
    suspend fun ensureFcmSubscription()

    /** Removes this phone's push token from the server. */
    suspend fun unsubscribeFcm()

    /** Returns whether Find My Phone is enabled on this phone. */
    fun findPhoneEnabled(): Boolean

    /** Enables or disables Find My Phone and reports the change to the server. */
    suspend fun setFindPhoneEnabled(enabled: Boolean)

    /** Fetches every member's latest location and the saved places. */
    suspend fun household(): HouseholdSnapshot

    /** Deletes a saved place for the whole household. */
    suspend fun deletePlace(place: HouseholdPlace)

    /** Publishes this member's display name and profile photo. */
    suspend fun saveProfilePhoto(name: String, photo: String)

    /** Returns whether this phone is sharing its location. */
    fun sharingEnabled(): Boolean

    /** Enables or disables location sharing for this phone. */
    suspend fun setSharing(enabled: Boolean)

    /** Returns the account IDs allowed to see this phone's location. */
    suspend fun sharingAudience(): Set<String>

    /** Sets which accounts can see this phone's location. */
    suspend fun setSharingAudience(ids: Set<String>)

    /** Returns the members this phone can share its location with. */
    suspend fun sharingChoices(): List<HouseholdPerson>

    /**
     * Shares this phone's location with members it hasn't seen before and returns their names.
     * The first time, every current member counts as seen, so earlier choices are kept. Members
     * removed in "Who can see this phone?" stay removed.
     */
    suspend fun includeNewMembers(choices: List<HouseholdPerson>): List<String>

    /**
     * Returns the admin browser's device ID, which can be added to the audience separately, or
     * null.
     */
    suspend fun ownerViewerId(): String?

    /** Encrypts and uploads one location immediately. */
    suspend fun publishLocation(fix: LocalFix, capturedAt: Long = System.currentTimeMillis())

    /** Deletes all locations and trips waiting in the offline queue. */
    fun clearPendingTracking()

    /**
     * Fetches a member's trip summaries for the last [days] days. The flag is true when there are
     * no trips, so no routes need loading.
     */
    suspend fun tripSummaries(accountId: String, days: Int = 1): Pair<TripHistory, Boolean>

    /** Fetches a member's trips together with their full GPS routes. */
    suspend fun tripHistory(accountId: String, days: Int = 1): TripHistory

    /** Creates or updates a saved place. */
    suspend fun savePlace(
        name: String,
        lat: Double,
        lon: Double,
        radius: Double,
        existing: HouseholdPlace? = null,
        alerts: Map<String, PlaceAlert> = emptyMap()
    )
}
