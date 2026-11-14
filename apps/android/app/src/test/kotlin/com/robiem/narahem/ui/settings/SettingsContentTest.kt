package com.robiem.narahem.ui.settings

import androidx.compose.foundation.layout.Box
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.account.ContactDetails
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.theme.NaraHemTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** The settings screen on its own: state and permissions in, actions out. */
@RunWith(AndroidJUnit4::class)
class SettingsContentTest {
    @get:Rule
    val compose = createComposeRule()
    private val calls = mutableListOf<String>()

    private val events = object : SettingsEvents by NoSettingsEvents {
        override fun signOut() {
            calls += "sign-out"
        }

        override suspend fun requestContactChange(
            value: String,
            password: String,
            phone: Boolean
        ): String {
            calls += (if (phone) "phone-code-to:" else "code-to:") + value
            return value
        }

        override suspend fun contactDetails() =
            ContactDetails("sam@example.invalid", null, textingOn = true)

        override suspend fun confirmContactChange(code: String) {
            calls += "confirm:$code"
        }
    }

    private fun click(text: String) = compose.onNodeWithText(text).performScrollTo().performClick()

    private fun show(permissions: DevicePermissions) = compose.setContent {
        NaraHemTheme {
            Box {
                SettingsContent(
                    state = AppState(
                        restoring = false,
                        account = Account("Sam", verified = true, household = "Home", id = "1"),
                        deviceStatus = "ready"
                    ),
                    form = SettingsForm("Sam"),
                    server = "https://family.example",
                    email = "sam@example.invalid",
                    permissions = permissions,
                    addressLookup = false,
                    events = events,
                    onAllowLocation = { calls += "allow-location" },
                    onBackgroundLocation = { calls += "background" },
                    onFindPhoneAccess = { calls += "find-phone-access" },
                    onChoosePhoto = {},
                    onTakePhoto = {}
                )
            }
        }
    }

    @Test fun missingLocationPermissionOffersToAllowIt() {
        show(DevicePermissions(location = false))
        click("Allow location")
        click("Enable Find my phone access")
        click("Account & about")
        click("Sign out")
        assertEquals(listOf("allow-location", "find-phone-access", "sign-out"), calls)
    }

    @Test fun foregroundOnlyLocationOffersBackgroundAccess() {
        show(DevicePermissions(location = true, backgroundLocation = false))
        click("Enable background location")
        assertEquals(listOf("background"), calls)
    }

    @Test fun theAccountShowsItsEmailAndPhone() {
        show(DevicePermissions(location = true, backgroundLocation = true))
        click("Account & about")
        compose.waitForIdle()
        compose.onNodeWithText("sam@example.invalid").assertExists()
        compose.onNodeWithText("None").assertExists()
        click("Add")
        compose.onNodeWithText("Add phone number").assertExists()
        compose.onNodeWithText("New phone number").performTextInput("4155550123")
        compose.onNodeWithText("Password").performTextInput("synthetic long password")
        compose.onNodeWithText("Send code").performClick()
        compose.waitForIdle()
        assertEquals(listOf("phone-code-to:4155550123"), calls)
    }

    @Test fun changingEmailSendsACodeAndConfirmsIt() {
        show(DevicePermissions(location = true, backgroundLocation = true))
        click("Account & about")
        compose.waitForIdle()
        click("Change")
        compose.onNodeWithText("New email address").performTextInput("new@example.invalid")
        compose.onNodeWithText("Password").performTextInput("synthetic long password")
        compose.onNodeWithText("Send code").performClick()
        compose.waitForIdle()
        compose.onNodeWithText("Six-digit code").performTextInput("123456")
        compose.onNodeWithText("Confirm").performClick()
        compose.waitForIdle()
        assertEquals(listOf("code-to:new@example.invalid", "confirm:123456"), calls)
    }
}
