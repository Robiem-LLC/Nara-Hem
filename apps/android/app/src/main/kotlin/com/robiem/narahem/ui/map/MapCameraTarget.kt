package com.robiem.narahem.ui.map

import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.location.LocalFix

/** Returns the map camera target: the selected member if one is chosen, otherwise this phone. */
internal fun mapCameraTarget(
    fix: LocalFix?,
    members: List<HouseholdPerson>,
    ownId: String?,
    focusId: String?
): Pair<Double, Double>? {
    /** Returns the member with this ID if they have a location. */
    fun member(id: String?) = members.firstOrNull {
        it.id == id && it.latitude != null && it.longitude != null
    }
        ?.let { it.latitude!! to it.longitude!! }
    val local = fix?.let { it.latitude to it.longitude }
    return if (focusId == null || focusId == ownId) local ?: member(ownId) else member(focusId)
}
