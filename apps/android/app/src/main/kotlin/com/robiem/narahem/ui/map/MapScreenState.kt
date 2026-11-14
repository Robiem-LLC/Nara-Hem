package com.robiem.narahem.ui.map

import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.setValue

/** Map screen UI state that survives rotation: drawer height, selected trip and camera focus. */
@Stable
class MapScreenState {
    var sheetExpanded by mutableStateOf(true)
    var drawerHeightDp by mutableFloatStateOf(255f)
    var selectedTripId by mutableStateOf<String?>(null)

    /** Member to centre on. Incrementing [focusKey] re-centres on the same member. */
    var focusMember by mutableStateOf<String?>(null)
    var focusKey by mutableIntStateOf(0)

    /** Error message if the map failed to load. */
    var mapError by mutableStateOf("")

    /** State saver. */
    companion object {
        val Saver = listSaver<MapScreenState, Any?>(
            save = { listOf(it.sheetExpanded, it.drawerHeightDp, it.selectedTripId) },
            restore = { saved ->
                MapScreenState().apply {
                    sheetExpanded = saved[0] as Boolean
                    drawerHeightDp = saved[1] as Float
                    selectedTripId = saved[2] as String?
                }
            }
        )
    }
}
