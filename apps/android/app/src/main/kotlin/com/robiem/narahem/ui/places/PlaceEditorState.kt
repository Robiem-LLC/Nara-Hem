package com.robiem.narahem.ui.places

import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.PlaceAlert
import com.robiem.narahem.data.settings.MapCamera
import com.robiem.narahem.ui.AppState

/** State of the place editor while it is open: the place being edited and the entered values. */
@Stable
class PlaceEditorState {
    var open by mutableStateOf(false)

    /** The place being edited, or null when adding a new one. */
    var editing by mutableStateOf<HouseholdPlace?>(null)
    var alerts by mutableStateOf<Map<String, PlaceAlert>>(emptyMap())
    var confirmingDelete by mutableStateOf(false)
    var name by mutableStateOf("")
    var latitude by mutableStateOf("")
    var longitude by mutableStateOf("")
    var radius by mutableStateOf("100")

    /** Current editor step: "map" for the boundary, then the details step. */
    var step by mutableStateOf("map")
    var search by mutableStateOf("")

    /** Incremented to move the picker map to [latitude] and [longitude]. */
    var recenter by mutableIntStateOf(0)
    var showCoordinates by mutableStateOf(false)

    /**
     * Opens the editor for a new place, centred on this phone's location, the account's last known
     * location, the last map position, or any member, in that order.
     */
    fun beginNew(state: AppState, lastCamera: MapCamera?) {
        val own = state.people.firstOrNull { it.id == state.account?.id }
        val anyone = state.people.firstOrNull { it.latitude != null && it.longitude != null }
        editing = null
        alerts = emptyMap()
        latitude = (
            state.fix?.latitude ?: own?.latitude ?: lastCamera?.latitude ?: anyone?.latitude ?: 0.0
            ).toString()
        longitude = (
            state.fix?.longitude ?: own?.longitude ?: lastCamera?.longitude
                ?: anyone?.longitude ?: 0.0
            ).toString()
        radius = "100"
        name = ""
        search = ""
        step = "map"
        recenter = 0
        showCoordinates = false
        open = true
    }

    /** Closes the editor and resets its fields. */
    fun close() {
        open = false
        confirmingDelete = false
    }
}
