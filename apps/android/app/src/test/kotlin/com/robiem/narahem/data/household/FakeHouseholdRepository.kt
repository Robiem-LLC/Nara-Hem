package com.robiem.narahem.data.household

import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.location.LocalFix
import com.robiem.narahem.data.trips.TripHistory

/** An in-memory household for view model and UI tests: no server, Keystore or encryption. */
class FakeHouseholdRepository(
    var deviceStatus: String = "ready",
    var people: List<HouseholdPerson> = emptyList(),
    var places: List<HouseholdPlace> = emptyList(),
    var trips: TripHistory = TripHistory(emptyList(), emptyList(), hasEarlier = false)
) : HouseholdRepository {
    var sharing = true

    /** The status [enroll] leaves this phone in. */
    var enrolledStatus = "ready"
    var findPhone = false
    var audience: Set<String> = emptySet()

    /** Whether [tripSummaries] reports the list as complete, so no full history is loaded. */
    var summariesComplete = false
    val published = mutableListOf<LocalFix>()
    val calls = mutableListOf<String>()

    /** Names of calls that throw instead of succeeding, such as "revokeOwnPhone". */
    val failing = mutableSetOf<String>()

    /** Names [includeNewMembers] reports once, as if they had just joined. */
    var newMembers: List<String> = emptyList()

    override suspend fun status(account: Account) = deviceStatus
    override suspend fun ownPairingCode() = "123456"
    override fun deviceFingerprint() = "device-fingerprint"
    override fun ownerFingerprint() = "owner-fingerprint"
    override suspend fun ensureFcmSubscription() {}
    override fun findPhoneEnabled() = findPhone
    override suspend fun household() = HouseholdSnapshot(people, places)
    override fun sharingEnabled() = sharing
    override suspend fun sharingAudience() = audience
    override suspend fun sharingChoices() = people
    override suspend fun ownerViewerId(): String? = null

    override suspend fun includeNewMembers(choices: List<HouseholdPerson>): List<String> =
        newMembers.also { newMembers = emptyList() }

    /** Throws if [name] is in [failing]. */
    private fun maybeFail(name: String) {
        if (name in failing) throw IllegalStateException("$name failed")
    }

    override suspend fun tripSummaries(accountId: String, days: Int): Pair<TripHistory, Boolean> {
        maybeFail("tripSummaries")
        return trips to summariesComplete
    }

    override suspend fun tripHistory(accountId: String, days: Int): TripHistory {
        calls += "tripHistory"
        maybeFail("tripHistory")
        return trips
    }

    override suspend fun enroll(account: Account, server: String) {
        calls += "enroll"
        deviceStatus = enrolledStatus
    }

    override suspend fun sendPhoneCode() {
        calls += "sendPhoneCode"
    }

    override suspend fun verifyPhoneCode(code: String) {
        calls += "verifyPhoneCode"
    }

    override suspend fun discardPendingPhone() {
        calls += "discardPendingPhone"
    }

    override suspend fun revokeOwnPhone() {
        calls += "revokeOwnPhone"
        maybeFail("revokeOwnPhone")
        deviceStatus = "unregistered"
    }

    override suspend fun sendFirstDeviceCode() {
        calls += "sendFirstDeviceCode"
    }

    override suspend fun bootstrapWithEmail(code: String) {
        calls += "bootstrapWithEmail"
        deviceStatus = "ready"
    }

    override suspend fun verifyOwnerFingerprint(fingerprint: String) {
        calls += "verifyOwnerFingerprint"
    }

    override suspend fun reportDevicePermissions() {
        calls += "reportDevicePermissions"
    }

    override suspend fun unsubscribeFcm() {
        calls += "unsubscribeFcm"
    }

    override suspend fun setFindPhoneEnabled(enabled: Boolean) {
        findPhone = enabled
    }

    override suspend fun savePlace(
        name: String,
        lat: Double,
        lon: Double,
        radius: Double,
        existing: HouseholdPlace?,
        alerts: Map<String, PlaceAlert>
    ) {
        val id = existing?.id ?: "place-${places.size + 1}"
        val place = HouseholdPlace(id, name, lat, lon, radius, alerts = alerts)
        places = places.filter { it.id != id } + place
    }

    override suspend fun deletePlace(place: HouseholdPlace) {
        places = places.filter { it.id != place.id }
    }

    override suspend fun saveProfilePhoto(name: String, photo: String) {
        calls += "saveProfilePhoto"
    }

    override suspend fun setSharing(enabled: Boolean) {
        sharing = enabled
    }

    override suspend fun setSharingAudience(ids: Set<String>) {
        audience = ids
    }

    override suspend fun publishLocation(fix: LocalFix, capturedAt: Long) {
        published += fix
    }

    override fun clearPendingTracking() {
        calls += "clearPendingTracking"
    }
}
