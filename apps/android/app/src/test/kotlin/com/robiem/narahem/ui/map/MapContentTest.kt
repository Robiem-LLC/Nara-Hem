package com.robiem.narahem.ui.map

import androidx.compose.foundation.layout.Box
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.theme.NaraHemTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/** The map screen's controls on their own, with the map itself turned off. */
@RunWith(AndroidJUnit4::class)
@Config(qualifiers = "w411dp-h891dp") // A typical phone; the drawer covers small screens.
class MapContentTest {
    @get:Rule
    val compose = createComposeRule()
    private val calls = mutableListOf<String>()

    private fun show(state: AppState, selected: String? = null) = compose.setContent {
        NaraHemTheme {
            Box {
                MapContent(
                    state = state,
                    screen = MapScreenState(),
                    loadMap = false,
                    nearbyAddresses = emptyMap(),
                    selectedMemberId = selected,
                    landscape = false,
                    sidePanel = 0.dp,
                    onSelectMember = { calls += "select:$it" },
                    onAskConsent = { calls += "consent" },
                    onOpenTab = { calls += "tab:$it" },
                    onViewTrips = { calls += "trips:$it" },
                    onClearTrips = { calls += "clear" },
                    onCenterOnPhone = { calls += "center" },
                    onCameraMoved = {}
                )
            }
        }
    }

    @Test fun withoutConsentTheMapAsksAndUnfinishedSetupLinksToSettings() {
        show(AppState(restoring = false, deviceStatus = "pending"))
        compose.onNodeWithText("Open household map").performClick()
        compose.onNodeWithText("Complete setup").performClick()
        assertEquals(listOf("consent", "tab:settings"), calls)
    }

    @Test fun aChosenMemberOffersTheirTrips() {
        val alex = HouseholdPerson("2", "Alex", 40.0, -74.0, 10.0, capturedAt = 1)
        show(AppState(restoring = false, deviceStatus = "ready", people = listOf(alex)), "2")
        compose.onNodeWithText("View trips").performScrollTo().performClick()
        assertEquals(listOf("trips:2"), calls)
    }
}
