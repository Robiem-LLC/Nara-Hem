package com.robiem.narahem.ui.components

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.settings.SettingsForm
import com.robiem.narahem.ui.theme.NaraHemTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** The invitation, location consent and audience dialogs. */
@RunWith(AndroidJUnit4::class)
class DialogsTest {
    @get:Rule
    val compose = createComposeRule()
    private val calls = mutableListOf<String>()

    @Test fun invitationForAnotherServerNamesBothHosts() {
        compose.setContent {
            NaraHemTheme {
                InviteServerDialog(
                    "https://other.example",
                    "https://family.example",
                    onSwitch = { calls += "switch" },
                    onKeep = { calls += "keep" }
                )
            }
        }
        compose.onNodeWithText("points to other.example", substring = true).assertExists()
        compose.onNodeWithText("Keep family.example").performClick()
        compose.onNodeWithText("Switch to other.example").performClick()
        assertEquals(listOf("keep", "switch"), calls)
    }

    @Test fun locationConsentCanBeGivenOrPutOff() {
        compose.setContent {
            NaraHemTheme {
                LocationConsentDialog(onAccept = { calls += "accept" }, onDismiss = {
                    calls +=
                        "later"
                })
            }
        }
        compose.onNodeWithText("Not now").performClick()
        compose.onNodeWithText("Continue").performClick()
        assertEquals(listOf("later", "accept"), calls)
    }

    @Test fun audienceDialogTogglesMembersAndSavesTheChoice() {
        val form = SettingsForm("Sam").apply { openAudience(setOf("k")) }
        val state = AppState(
            restoring = false,
            account = Account("Sam", true, "Home", "me"),
            audienceLoaded = true,
            audience = setOf("k"),
            audienceChoices = listOf(
                HouseholdPerson("me", "Sam"),
                HouseholdPerson("k", "Kim"),
                HouseholdPerson("j", "Jo")
            )
        )
        val saved = mutableListOf<Set<String>>()
        compose.setContent { NaraHemTheme { AudienceDialog(state, form) { saved += it } } }
        compose.onNodeWithText("Sam").assertDoesNotExist()
        compose.onNodeWithText("Jo").performClick()
        compose.onNodeWithText("Kim").performClick()
        assertEquals(setOf("j"), form.audienceDraft)
        compose.onNodeWithText("Save sharing choices").performClick()
        assertEquals(listOf(setOf("j")), saved)
    }

    @Test fun audienceDialogExplainsWhenNobodyCanBeChosen() {
        val form = SettingsForm("Sam").apply { openAudience(emptySet()) }
        val state = AppState(restoring = false, account = Account("Sam", true, "Home", "me"))
        compose.setContent { NaraHemTheme { AudienceDialog(state, form) {} } }
        compose.onNodeWithText("Cannot load household members", substring = true).assertExists()
        compose.onNodeWithText("Cancel").performClick()
        assertFalse(form.audienceOpen)
    }
}
