package com.robiem.narahem.ui

import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.HouseholdTrip
import com.robiem.narahem.data.location.LocalFix
import com.robiem.narahem.data.trips.TripPoint

/** Immutable UI state shared by every screen. Held and updated by [HouseholdSession]. */
data class AppState(
    val account: Account? = null,
    val busy: Boolean = false,
    val message: String = "",
    val fix: LocalFix? = null,
    val error: Boolean = false,
    val fields: Map<String, String> = emptyMap(),
    val onboarding: String = "signin",
    val deviceStatus: String = "register",
    val people: List<HouseholdPerson> = emptyList(),
    val places: List<HouseholdPlace> = emptyList(),
    val sharing: Boolean = true,
    val deviceFingerprint: String = "",
    val ownerFingerprint: String = "",
    val pairingCode: String = "",
    val restoring: Boolean = true,
    val syncProblem: Boolean = false,
    val audience: Set<String> = emptySet(),
    val audienceLoaded: Boolean = false,
    val audienceChoices: List<HouseholdPerson> = emptyList(),
    /** Names of members who just joined and are now shared with; shown once, then cleared. */
    val joinedMembers: List<String> = emptyList(),
    val ownerViewerId: String? = null,
    val tripsForMember: String? = null,
    val trips: List<HouseholdTrip> = emptyList(),
    val tripsLoading: Boolean = false,
    val tripsError: String = "",
    val findPhoneEnabled: Boolean = false,
    val tripPoints: List<com.robiem.narahem.data.trips.TripPoint> = emptyList(),
    val tripHistoryPartial: Boolean = false,
    val tripDays: Int = 1
)
