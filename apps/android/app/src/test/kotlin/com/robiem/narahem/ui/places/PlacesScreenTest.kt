package com.robiem.narahem.ui.places

import android.content.Intent
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Box
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onLast
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.theme.NaraHemTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

/** The places list and the details step of the place editor (the map step needs MapLibre). */
@RunWith(AndroidJUnit4::class)
@Config(qualifiers = "w411dp-h891dp")
class PlacesScreenTest {
    @get:Rule
    val compose = createAndroidComposeRule<ComponentActivity>()
    private val home = HouseholdPlace("1", "Home", 40.0, -74.0, 100.0, recordId = "r1")
    private val corner = HouseholdPlace("2", "Corner shop", 40.0005, -74.0, 80.0, recordId = "r2")
    private val kim = HouseholdPerson("k", "Kim")
    private val calls = mutableListOf<String>()

    private fun show(state: AppState, editor: PlaceEditorState = PlaceEditorState()) =
        compose.setContent {
            NaraHemTheme {
                Box {
                    PlacesContent(
                        state = state,
                        editor = editor,
                        lastMapZoom = 15.0,
                        onNewPlace = { calls += "new" },
                        onFindAddress = { calls += "find" },
                        onSave = { calls += "save" },
                        onDelete = { calls += "delete:${it.id}" },
                        loadMap = false
                    )
                }
            }
        }

    private fun ready(role: String = "member") = AppState(
        restoring = false,
        deviceStatus = "ready",
        account = Account("Sam", true, "test", "me", role),
        people = listOf(kim)
    )

    @Test fun emptyListInvitesTheFirstPlace() {
        show(ready())
        compose.onNodeWithText("No saved places yet.", substring = true).assertExists()
        compose.onNodeWithText("Add a Place").assertIsEnabled().performClick()
        assertEquals(listOf("new"), calls)
    }

    @Test fun overlappingPlacesAreFlaggedAndDirectionsOpenAnotherApp() {
        show(ready().copy(places = listOf(home, corner)))
        compose.onNodeWithText("Overlaps Corner shop.", substring = true).assertExists()
        compose.onNodeWithText("Overlaps Home.", substring = true).assertExists()
        compose.onAllNodesWithText("Directions")[0].performClick()
        val opened = shadowOf(compose.activity).nextStartedActivity
        assertEquals(Intent.ACTION_VIEW, opened.action)
        assertTrue(opened.data.toString().startsWith("geo:0,0?q="))
    }

    @Test fun tappingAPlaceOpensItsBoundaryStep() {
        val editor = PlaceEditorState()
        show(ready().copy(places = listOf(home)), editor)
        compose.onNodeWithText("Home").performClick()
        assertTrue(editor.open)
        assertEquals("Home" to "100", editor.name to editor.radius)
        compose.onNodeWithText("Edit boundary · 1 of 2").assertExists()
        compose.onNodeWithText("Boundary radius: 100 metres").assertExists()
        compose.onNodeWithText("Exact (1–10,000)").performTextReplacement("12")
        compose.onNodeWithText("Small radii are supported", substring = true).assertExists()
        compose.onNodeWithText("▸ Advanced: exact coordinates").performClick()
        compose.onNodeWithText("Latitude").performTextReplacement("41.5")
        compose.onNodeWithText("Use").performClick()
        assertEquals("41.5" to 1, editor.latitude to editor.recenter)
        compose.onNodeWithText("Search address or business").performTextReplacement("Town hall")
        compose.onNodeWithText("Find").performClick()
        compose.onNodeWithText("Next").performClick()
        assertEquals(listOf("find"), calls)
        assertEquals("details", editor.step)
    }

    @Test fun detailsStepNamesThePlace() {
        val editor = PlaceEditorState().apply {
            beginNew(ready(), null)
            latitude = "40.0"
            longitude = "-74.0"
            step = "details"
        }
        show(ready(), editor)
        compose.onNodeWithText("Add place").assertExists()
        compose.onNodeWithText("Place details · 2 of 2").assertExists()
        compose.onNodeWithText("Save").assertIsNotEnabled()
        compose.onNodeWithText("Name this place").performTextReplacement("School")
        assertEquals("School", editor.name)
        // Everyone sharing their location gets a place's alerts; there are no per-person switches.
        compose.onAllNodesWithText("Arrives").assertCountEquals(0)
        compose.onNodeWithText("Save").assertIsEnabled().performClick()
        assertEquals(listOf("save"), calls)
        compose.onNodeWithText("Edit boundary").performClick()
        assertEquals("map", editor.step)
    }

    @Test fun adminsCanDeleteAPlaceAfterConfirming() {
        val editor = PlaceEditorState().apply {
            editing = home
            name = home.name
            latitude = "40.0"
            longitude = "-74.0"
            step = "details"
            open = true
        }
        show(ready(role = "admin").copy(places = listOf(home)), editor)
        compose.onNodeWithText("Edit place").assertExists()
        compose.onNodeWithText("Delete place").performScrollTo().performClick()
        assertTrue(editor.confirmingDelete)
        compose.onNodeWithText("Delete Home?").assertExists()
        // The dialog's Cancel, not the editor's.
        compose.onAllNodesWithText("Cancel").onLast().performClick()
        assertFalse(editor.confirmingDelete)
        compose.onNodeWithText("Delete place").performScrollTo().performClick()
        compose.onNodeWithText("Delete").performClick()
        assertEquals(listOf("delete:1"), calls)
    }

    @Test fun membersCannotDeleteAndErrorsShowInTheEditor() {
        val editor = PlaceEditorState().apply {
            editing = home
            name = home.name
            latitude = "40.0"
            longitude = "-74.0"
            step = "details"
            open = true
        }
        show(ready().copy(error = true, message = "This area overlaps School."), editor)
        compose.onNodeWithText("Delete place").assertDoesNotExist()
        compose.onNodeWithText("This area overlaps School.").assertExists()
        compose.onNodeWithText("Cancel").performClick()
        assertFalse(editor.open)
    }
}
