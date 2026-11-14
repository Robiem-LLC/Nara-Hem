package com.robiem.narahem.ui.places

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.HouseholdRepository
import com.robiem.narahem.data.location.AddressLookup
import com.robiem.narahem.ui.HouseholdSession
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/** View model for creating, editing, deleting and searching for saved places. */
class PlacesViewModel(
    private val session: HouseholdSession,
    private val household: HouseholdRepository?,
    private val addresses: AddressLookup
) : ViewModel() {
    /** Runs [task] through [HouseholdSession.work]. */
    private fun work(task: suspend () -> Unit) = session.work(task)

    /** Saves a new or edited place and refreshes the household. */
    fun savePlace(
        name: String,
        latitude: Double,
        longitude: Double,
        radius: Double,
        existing: HouseholdPlace? = null,
        alerts: Map<String, com.robiem.narahem.data.household.PlaceAlert> = emptyMap(),
        onSaved: () -> Unit = {}
    ) = work {
        household?.savePlace(name, latitude, longitude, radius, existing, alerts)
        session.refreshTrusted()
        session.update { it.copy(message = "Place saved.") }
        onSaved()
    }

    /** Deletes a place for the whole household, then calls [onDeleted]. */
    fun deletePlace(place: HouseholdPlace, onDeleted: () -> Unit = {}) = work {
        household?.deletePlace(place)
        session.refreshTrusted()
        session.update { it.copy(message = "Place deleted.") }
        onDeleted()
    }

    /** Geocodes an address or business name and passes the result to [onFound]. */
    fun findAddress(query: String, onFound: (latitude: Double, longitude: Double) -> Unit) {
        viewModelScope.launch {
            val found = try {
                addresses.find(query.trim())
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                session.showError("Address lookup is unavailable. Choose the location on the map.")
                return@launch
            }
            if (found != null) {
                onFound(found.first, found.second)
            } else {
                session.showError("Address not found. Move the map to pick a location.")
            }
        }
    }
}
