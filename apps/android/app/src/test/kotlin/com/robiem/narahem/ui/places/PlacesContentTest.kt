package com.robiem.narahem.ui.places

import androidx.compose.foundation.layout.Box
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.location.LocalFix
import com.robiem.narahem.data.settings.MapCamera
import com.robiem.narahem.data.settings.PhoneAppSettings
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.theme.NaraHemTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** The places screen and its editor state on their own. */
@RunWith(AndroidJUnit4::class)
class PlacesContentTest {
    @get:Rule
    val compose = createComposeRule()
    private val home = HouseholdPlace("1", "Home", 40.0, -74.0, 100.0)

    @Test fun listsPlacesAndAsksForANewOne() {
        var newPlace = 0
        compose.setContent {
            NaraHemTheme {
                Box {
                    PlacesContent(
                        state = AppState(restoring = false, places = listOf(home)),
                        editor = PlaceEditorState(),
                        lastMapZoom = PhoneAppSettings.DEFAULT_ZOOM,
                        onNewPlace = { newPlace++ },
                        onFindAddress = {},
                        onSave = {},
                        onDelete = {}
                    )
                }
            }
        }
        compose.onNodeWithText("Home").assertExists()
        // A phone that is not yet a trusted household device cannot add places.
        compose.onNodeWithText("Add a Place").assertIsNotEnabled()
        assertEquals(0, newPlace)
    }

    @Test fun aNewPlaceStartsAtThisPhoneThenTheLastMapView() {
        val editor = PlaceEditorState()
        val account = Account("Sam", verified = true, household = "test", id = "me")
        val state = AppState(
            restoring = false,
            account = account,
            fix = LocalFix(41.0, -73.0, 10f),
            people = listOf(HouseholdPerson("me", "Sam", 42.0, -72.0))
        )
        editor.beginNew(state, MapCamera(43.0, -71.0, 12.0))
        assertTrue(editor.open)
        assertEquals("41.0" to "-73.0", editor.latitude to editor.longitude)

        editor.beginNew(state.copy(fix = null), MapCamera(43.0, -71.0, 12.0))
        assertEquals("42.0" to "-72.0", editor.latitude to editor.longitude)

        editor.beginNew(state.copy(fix = null, people = emptyList()), MapCamera(43.0, -71.0, 12.0))
        assertEquals("43.0" to "-71.0", editor.latitude to editor.longitude)
        assertEquals("100", editor.radius)

        editor.confirmingDelete = true
        editor.close()
        assertTrue(!editor.open && !editor.confirmingDelete)
    }
}
