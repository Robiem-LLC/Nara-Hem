package com.robiem.narahem.ui.map

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.HouseholdRepository
import com.robiem.narahem.data.location.AddressLookup
import com.robiem.narahem.data.location.LocationRepository
import com.robiem.narahem.data.settings.MapCamera
import com.robiem.narahem.ui.HouseholdSession
import com.robiem.narahem.ui.places.PlaceGeometry
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.mapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/**
 * View model for the map tab: this phone's location, the stored camera position and nearby
 * addresses.
 */
class MapViewModel(
    private val session: HouseholdSession,
    private val locations: LocationRepository,
    private val household: HouseholdRepository?,
    private val addresses: AddressLookup
) : ViewModel() {
    /**
     * Street addresses for members who are not at a saved place, when address lookup is enabled.
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    val nearbyAddresses: StateFlow<Map<String, String>> = combine(
        session.state.map { it.people to it.places }.distinctUntilChanged(),
        session.phoneSettings.map { it.addressLookup }.distinctUntilChanged()
    ) { (people, places), enabled -> Triple(people, places, enabled) }
        .mapLatest { (people, places, enabled) ->
            if (enabled) addressesAwayFromPlaces(people, places) else emptyMap()
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyMap())

    private var cameraLocation: Job? = null

    init {
        session.onSignOut { cameraLocation?.cancel() }
    }

    /** Runs [task] through [HouseholdSession.work]. */
    private fun work(task: suspend () -> Unit) = session.work(task)

    /** Stores the map position. */
    fun rememberMapCamera(camera: MapCamera) = session.rememberMapCamera(camera)

    /**
     * Looks up addresses for members outside every saved place. Returns an empty map when lookups
     * are disabled.
     */
    private suspend fun addressesAwayFromPlaces(
        people: List<HouseholdPerson>,
        places: List<HouseholdPlace>
    ): Map<String, String> = people.mapNotNull { person ->
        val lat = person.latitude ?: return@mapNotNull null
        val lon = person.longitude ?: return@mapNotNull null
        if (PlaceGeometry.matchingPlace(lat, lon, places) != null) return@mapNotNull null
        runCatching { addresses.near(lat, lon) }.getOrNull()?.let { person.id to it }
    }.toMap()

    /** Gets a fresh location for this phone and centres the map on it. */
    fun locate() = work {
        check(session.current.account != null) { "Sign in first." }
        val fix = locations.current()
        val sharingReady = session.current.deviceStatus == "ready" && session.current.sharing
        if (sharingReady) household?.publishLocation(fix)
        session.update {
            it.copy(
                fix = fix,
                message = if (sharingReady) {
                    "Location shared with household."
                } else {
                    "Location shown locally; device approval is still needed for sharing."
                }
            )
        }
    }

    /**
     * Centres the map on this phone once per launch (or again when [force] is set) without
     * publishing the location.
     */
    fun centerMapOnPhone(force: Boolean = false) {
        val accountId = session.current.account?.id ?: return
        if (!force && (session.current.fix != null || cameraLocation?.isActive == true)) return
        cameraLocation?.cancel()
        if (session.current.fix == null) {
            locations.lastKnown()?.let { cached ->
                session.update { if (it.account?.id == accountId) it.copy(fix = cached) else it }
            }
        }
        cameraLocation = viewModelScope.launch {
            try {
                val fix = locations.current()
                session.update { if (it.account?.id == accountId) it.copy(fix = fix) else it }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (
                _: Exception
            ) { /* Retain a last-known local fix or the member's encrypted fix. */ }
        }
    }
}
