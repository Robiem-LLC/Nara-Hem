package com.robiem.narahem.ui.trips

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.HouseholdTrip
import com.robiem.narahem.data.trips.TripPoint
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.theme.NaraHemTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/** Trip and stop cards, their dialogs, and the day range chips (with maps turned off). */
@RunWith(AndroidJUnit4::class)
@Config(qualifiers = "w411dp-h891dp")
class TripTimelineCardsTest {
    @get:Rule
    val compose = createComposeRule()
    private val start = 1_700_000_000_000L
    private val calls = mutableListOf<String>()

    /** A 15-minute stop, then a 15-minute drive north with a point every minute. */
    private val stopPoints = listOf(point(0, 40.0), point(120_000, 40.0), point(240_000, 40.0))
    private val drivePoints = (0..15).map { point(600_000 + it * 60_000L, 40.0 + it * 0.003) }

    private val drive = HouseholdTrip(
        "drive", "m", start + 600_000, start + 1_500_000, 5_000.0, 15.0, 40, "phone",
        startLabel = "Home"
    )

    private fun point(offset: Long, lat: Double) =
        TripPoint("$offset", "m", "phone", start + offset, lat, -74.0, 5.0)

    private fun show(state: AppState, addressNear: AddressNear? = null) = compose.setContent {
        NaraHemTheme {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                TripTimelineCards(
                    state,
                    mapsEnabled = false,
                    addressNear = addressNear,
                    onDays = { calls += "days:$it" },
                    onSavePlace = { name, lat, lon -> calls += "save:$name:$lat:$lon" }
                )
            }
        }
    }

    private fun day(vararg trips: HouseholdTrip, places: List<HouseholdPlace> = emptyList()) =
        AppState(
            restoring = false,
            trips = trips.toList(),
            tripPoints = stopPoints + drivePoints,
            places = places,
            tripsForMember = "m"
        )

    @Test fun noTripsSaysSoAndOffersOtherRanges() {
        show(AppState(restoring = false))
        compose.onNodeWithText("No trips").assertExists()
        compose.onNodeWithText("7 days").performClick()
        compose.onNodeWithText("14 days").performClick()
        assertEquals(listOf("days:7", "days:14"), calls)
    }

    @Test fun tripCardSummarisesTheDrive() {
        show(day(drive).copy(tripHistoryPartial = true))
        compose.onNodeWithText("Earlier route history", substring = true).assertExists()
        compose.onNodeWithText("Home").assertExists()
        compose.onNodeWithText("Recorded GPS").assertExists()
        compose.onNodeWithText("3.11 mi", substring = true).assertExists()
        compose.onNodeWithText("Top speed 34 mph", substring = true).assertExists()
        compose.onNodeWithText("Enable maps to see the route").assertExists()
        compose.onNodeWithText("16 GPS points matched", substring = true).assertExists()
    }

    @Test fun tappingATripOpensItsDetails() {
        show(day(drive))
        compose.onNodeWithText("Enable maps to see the route").performClick()
        compose.onNodeWithText("Only available recorded sections", substring = true).assertExists()
        compose.onNodeWithText("Close").performClick()
        compose.onNodeWithText("Only available recorded sections", substring = true)
            .assertDoesNotExist()
    }

    @Test fun routeSourceAndGapsAreLabelled() {
        val matched = drive.copy(id = "m1", matched = true, partial = true)
        val pending = drive.copy(
            id = "m2",
            startedAt = start + 3_600_000,
            endedAt = start + 4_200_000,
            normalized = true,
            processing = true
        )
        show(day(matched, pending))
        compose.onNodeWithText("Road matched").assertExists()
        compose.onNodeWithText("Partial GPS observations").assertExists()
        compose.onNodeWithText("GPS normalized · Road matching pending").performScrollTo()
        compose.onNodeWithText("Route unavailable").performScrollTo()
        compose.onNodeWithText("Route points unavailable", substring = true).performScrollTo()
    }

    @Test fun anUnsavedStopShowsItsAddressAndOffersToSaveIt() {
        show(day(drive), addressNear = { _, _ -> "1 High St" })
        compose.onNodeWithText("At").assertExists()
        compose.onAllNodesWithText("1 High St").onFirst().assertExists()
        // Its dialog isn't opened here: a text field in a dialog never lets Robolectric go idle.
        compose.onNodeWithText("Save Place").performScrollTo().assertExists()
    }

    @Test fun aStopAtASavedPlaceUsesItsName() {
        show(day(drive, places = listOf(HouseholdPlace("h", "Gym", 40.0, -74.0, 100.0))))
        compose.onNodeWithText("Gym").assertExists()
        compose.onNodeWithText("Save Place").assertDoesNotExist()
    }
}
