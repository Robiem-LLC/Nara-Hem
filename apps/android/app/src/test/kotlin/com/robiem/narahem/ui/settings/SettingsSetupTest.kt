package com.robiem.narahem.ui.settings

import androidx.compose.foundation.layout.Box
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.theme.NaraHemTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/** Each device setup step in Settings, and the sharing and Find My Phone controls. */
@RunWith(AndroidJUnit4::class)
@Config(qualifiers = "w411dp-h891dp")
class SettingsSetupTest {
    @get:Rule
    val compose = createComposeRule()
    private val calls = mutableListOf<String>()
    private val form = SettingsForm("Sam")
    private val server = "https://family.example"

    private val events = object : SettingsEvents {
        override fun setFindPhone(enabled: Boolean) {
            calls += "find:$enabled"
        }
        override fun stopFindPhoneAlarm() {
            calls += "stop-alarm"
        }
        override fun requestPhoneCode() {
            calls += "phone-code"
        }
        override fun confirmPhoneCode(code: String) {
            calls += "confirm:$code"
        }
        override fun restartPhoneRegistration(server: String) {
            calls += "restart"
        }
        override fun prepareDevice(server: String) {
            calls += "prepare"
        }
        override fun revokeThisPhone() {
            calls += "revoke"
        }
        override fun changeUsername(username: String) {
            calls += "username:$username"
        }
        override fun sendBootstrapCode() {
            calls += "bootstrap-code"
        }
        override fun finishBootstrap(code: String) {
            calls += "bootstrap:$code"
        }
        override fun verifyHousehold(fingerprint: String) {
            calls += "verify:$fingerprint"
        }
        override fun setSharing(enabled: Boolean) {
            calls += "sharing:$enabled"
        }
        override fun setOwnerBrowserAccess(enabled: Boolean) {
            calls += "owner:$enabled"
        }
        override fun setAddressLookup(enabled: Boolean) {
            calls += "addresses:$enabled"
        }
        override fun resendEmailConfirmation(server: String, email: String) {
            calls += "resend:$email"
        }

        override fun signOut() {
            calls += "sign-out"
        }
    }

    private fun click(text: String) = compose.onNodeWithText(text).performScrollTo().performClick()

    private fun show(
        state: AppState,
        permissions: DevicePermissions = DevicePermissions(true, true, true)
    ) = compose.setContent {
        NaraHemTheme {
            Box {
                SettingsContent(
                    state = state,
                    form = form,
                    server = server,
                    email = "",
                    permissions = permissions,
                    addressLookup = false,
                    events = events,
                    onAllowLocation = { calls += "allow-location" },
                    onBackgroundLocation = { calls += "background" },
                    onFindPhoneAccess = { calls += "dnd" },
                    onChoosePhoto = { calls += "choose-photo" },
                    onTakePhoto = { calls += "take-photo" }
                )
            }
        }
    }

    private fun state(status: String) = AppState(
        restoring = false,
        account = Account("Sam", verified = true, household = "Home", id = "me"),
        deviceStatus = status
    )

    /** Switches in the open Permissions section, top to bottom: sharing, Find My Phone. */
    private fun switch(index: Int): SemanticsNodeInteraction =
        compose.onAllNodes(isToggleable())[index]

    @Test fun unregisteredPhoneCanRegisterAgain() {
        show(state("register"))
        click("Register this phone")
        assertEquals(listOf("restart"), calls)
    }

    @Test fun unconfirmedEmailCanBeResentToTheAccountName() {
        show(state("verify-email"))
        click("Resend confirmation email")
        assertEquals(listOf("resend:Sam"), calls)
    }

    @Test fun firstAdminDeviceIsTrustedWithAnEmailedCode() {
        show(state("first-device"))
        click("Email my six-digit code")
        compose.onNodeWithText("Six-digit code").performTextReplacement("123456")
        click("Trust this device")
        assertEquals(listOf("bootstrap-code", "bootstrap:123456"), calls)
    }

    @Test fun phoneIsVerifiedWithASixDigitCode() {
        show(state("email-code"))
        click("Send verification code")
        compose.onNodeWithText("Verify and register this phone").assertIsNotEnabled()
        compose.onNodeWithText("Six-digit code").performTextReplacement("654321")
        click("Verify and register this phone")
        click("Start registration again")
        assertEquals(listOf("phone-code", "confirm:654321", "restart"), calls)
    }

    @Test fun replacementNeedsTheOldPhoneRevoked() {
        show(state("replacement-required"))
        compose.onNodeWithText("already has a registered phone", substring = true).assertExists()
        click("Check again")
        assertEquals(listOf("restart"), calls)
    }

    @Test fun pairingShowsTheCodeAndOffersManualRecovery() {
        show(state("pairing").copy(pairingCode = "424242"))
        compose.onNodeWithText("424242").assertExists()
        click("Advanced manual recovery")
        compose.onNodeWithText("Trusted owner fingerprint").performTextReplacement("abc")
        click("Verify manually")
        assertEquals(listOf("verify:abc"), calls)
    }

    @Test fun pendingPhoneWaitsWithoutManualRecovery() {
        show(state("pending"))
        compose.onNodeWithText("Checking…").assertExists()
        compose.onNodeWithText("Advanced manual recovery").assertDoesNotExist()
    }

    @Test fun unknownStateOffersToRetryEnrollment() {
        show(state("something-else"))
        click("Retry device enrollment")
        assertEquals(listOf("prepare"), calls)
    }

    @Test fun readyPhoneControlsSharingAudienceAndFindMyPhone() {
        val kim = HouseholdPerson("k", "Kim")
        show(
            state("ready").copy(
                findPhoneEnabled = true,
                audienceLoaded = true,
                audienceChoices = listOf(kim),
                audience = setOf("k"),
                ownerViewerId = "owner"
            )
        )
        click("Permissions")
        compose.onNodeWithText("On · sharing with selected household members").assertExists()
        switch(0).assertIsOn().performScrollTo().performClick()
        compose.onNodeWithText("Who can see this phone? (1 other members)").assertIsEnabled()
        click("Who can see this phone? (1 other members)")
        assertTrue(form.audienceOpen)
        assertEquals(setOf("k"), form.audienceDraft)
        compose.onNodeWithText("Stop alarm").assertDoesNotExist()
        compose.onNodeWithText("Show nearby street addresses").assertDoesNotExist()
        switch(1).assertIsOn().performScrollTo().performClick()
        click("Profile")
        compose.onNodeWithText("Display username").performTextReplacement("sam.lee")
        click("Change username")
        assertEquals(listOf("sharing:false", "find:false", "username:sam.lee"), calls)
    }

    @Test fun aloneInTheHouseholdTheAudienceCannotBeChosen() {
        show(
            state(
                "ready"
            ).copy(sharing = false, audienceLoaded = true, audienceChoices = emptyList())
        )
        click("Permissions")
        compose.onNodeWithText("Off · location updates paused").assertExists()
        compose.onNodeWithText(
            "No other eligible household members",
            substring = true
        ).assertExists()
        compose.onNodeWithText("Who can see this phone? (0 other members)").assertIsNotEnabled()
    }

    @Test fun missingBackgroundPermissionOffersToAllowIt() {
        show(state("ready"), DevicePermissions(location = true))
        compose.onNodeWithText("Background location: Always allowed").assertDoesNotExist()
        compose.onNodeWithText("Enable background location").assertExists()
        click("Profile")
        compose.onNodeWithText("Choose photo").performScrollTo().performClick()
        compose.onNodeWithText("Take photo").performScrollTo().performClick()
        assertTrue(calls.containsAll(listOf("choose-photo", "take-photo")))
    }
}
