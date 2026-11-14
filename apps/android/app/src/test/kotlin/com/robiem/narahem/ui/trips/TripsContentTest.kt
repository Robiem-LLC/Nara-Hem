package com.robiem.narahem.ui.trips

import androidx.compose.foundation.layout.Box
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.theme.NaraHemTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** The trips screen on its own: state in, actions out. */
@RunWith(AndroidJUnit4::class)
class TripsContentTest {
    @get:Rule
    val compose = createComposeRule()

    @Test fun showsMembersAndErrorsAndReportsTheChosenMember() {
        val chosen = mutableListOf<String>()
        val state = AppState(
            restoring = false,
            people = listOf(HouseholdPerson("1", "Sam"), HouseholdPerson("2", "Alex")),
            tripsForMember = "1",
            tripsError = "Could not load trip history. Retry when online."
        )
        compose.setContent {
            NaraHemTheme {
                Box {
                    TripsContent(
                        state = state,
                        mapsEnabled = false,
                        addressNear = null,
                        onSelectMember = { chosen += it },
                        onDays = {},
                        onSavePlace = { _, _, _ -> }
                    )
                }
            }
        }
        compose.onNodeWithText("Sam").assertIsSelected()
        compose.onNodeWithText("Could not load trip history. Retry when online.").assertExists()
        compose.onNodeWithText("Alex").performClick()
        assertEquals(listOf("2"), chosen)
    }
}
