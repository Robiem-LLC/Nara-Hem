package com.robiem.narahem.ui.trips

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.robiem.narahem.data.household.HouseholdRepository
import com.robiem.narahem.data.location.AddressLookup
import com.robiem.narahem.ui.HouseholdSession
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * View model for the Trips tab. Loads a member's trips and refreshes them while the tab is open.
 */
class TripsViewModel(
    private val session: HouseholdSession,
    private val household: HouseholdRepository?,
    private val addresses: AddressLookup
) : ViewModel() {
    private var tripLoad: Job? = null

    init {
        session.onSignOut { tripLoad?.cancel() }
    }

    /**
     * Loads a member's trips for the last [days] days, cancelling any earlier load. Summaries
     * appear first, then full routes.
     */
    fun loadMemberTrips(accountId: String, days: Int = session.current.tripDays) {
        tripLoad?.cancel()
        session.update {
            val refresh = it.tripsForMember == accountId && it.tripDays == days
            it.copy(
                tripsForMember = accountId,
                trips = if (refresh) it.trips else emptyList(),
                tripsLoading = true,
                tripsError = "",
                tripPoints = if (refresh) it.tripPoints else emptyList(),
                tripHistoryPartial = refresh && it.tripHistoryPartial,
                tripDays = days
            )
        }
        tripLoad = viewModelScope.launch {
            var shown = false
            try {
                val (quick, complete) = household?.tripSummaries(accountId, days) ?: (null to true)
                shown = quick != null
                session.update {
                    if (it.tripsForMember == accountId) {
                        it.copy(
                            trips = quick?.trips.orEmpty(),
                            tripPoints = quick?.points.orEmpty(),
                            tripHistoryPartial = quick?.hasEarlier ?: false,
                            tripsLoading = !complete
                        )
                    } else {
                        it
                    }
                }
                if (complete) return@launch
                val results = household?.tripHistory(accountId, days)
                session.update {
                    if (it.tripsForMember == accountId) {
                        it.copy(
                            trips = results?.trips.orEmpty(),
                            tripPoints = results?.points.orEmpty(),
                            tripHistoryPartial = results?.hasEarlier ?: false,
                            tripsLoading = false
                        )
                    } else {
                        it
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                session.update {
                    if (it.tripsForMember == accountId) {
                        it.copy(
                            tripsLoading = false,
                            tripsError = if (shown) {
                                "Detailed routes could not load. Retry when online."
                            } else {
                                "Could not load trip history. Retry when online."
                            }
                        )
                    } else {
                        it
                    }
                }
            }
        }
    }

    /** Clears the loaded trips. */
    fun clearMemberTrips() {
        tripLoad?.cancel()
        session.update {
            it.copy(
                tripsForMember = null,
                trips = emptyList(),
                tripPoints = emptyList(),
                tripHistoryPartial = false,
                tripsLoading = false,
                tripsError = ""
            )
        }
    }

    /** Periodically reloads the selected member's trips until cancelled. */
    suspend fun refreshTripsWhileOpen(selectedMember: () -> String?): Nothing {
        while (true) {
            delay(25_000)
            val current = session.current
            val member =
                current.tripsForMember ?: selectedMember() ?: current.people.firstOrNull()?.id
            if (!current.tripsLoading && member != null) loadMemberTrips(member, current.tripDays)
        }
    }

    /** Returns a street address near a trip end, or null. */
    suspend fun addressNear(latitude: Double, longitude: Double): String? =
        runCatching { addresses.near(latitude, longitude) }.getOrNull()
}
