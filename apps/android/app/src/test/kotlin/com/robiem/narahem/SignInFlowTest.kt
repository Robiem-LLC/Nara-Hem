package com.robiem.narahem

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** The signed-out screens, driven through the real MainActivity (no server is contacted). */
@RunWith(AndroidJUnit4::class)
class SignInFlowTest {
    @get:Rule
    val compose = createAndroidComposeRule<MainActivity>()

    private fun click(text: String) {
        val node = compose.onNodeWithText(text)
        // Dialogs and fixed bars have nothing to scroll; screens usually do.
        runCatching { node.performScrollTo() }
        node.performClick()
    }

    private fun type(label: String, value: String) {
        val node = compose.onNodeWithText(label)
        runCatching { node.performScrollTo() }
        node.performTextInput(value)
    }

    private fun showsPasswordStep() {
        type("Server address", "https://family.example")
        type("Email or phone number", "sam@example.invalid")
        click("Continue")
    }

    @Test
    fun freshInstallAsksForServerAndEmailFirst() {
        compose.onNodeWithText("YOUR HOME. YOUR DATA.").assertIsDisplayed()
        compose.onNodeWithText("Server address").assertExists()
        compose.onNodeWithText("Email or phone number").assertExists()
        compose.onNodeWithText("Continue").assertExists()
        compose.onNodeWithText("Password").assertDoesNotExist()
        compose.onNodeWithText("Request household access").assertExists()
    }

    @Test
    fun continueNeedsBothServerAndEmail() {
        type("Server address", "https://family.example")
        click("Continue")
        compose.onNodeWithText("Password").assertDoesNotExist()
        compose.onNodeWithText("Continue").assertExists()
    }

    @Test
    fun passwordStepOffersSignInInvitationAndGoingBack() {
        showsPasswordStep()
        compose.onNodeWithText("Password").assertExists()
        compose.onNodeWithText("Sign in").assertIsEnabled()
        compose.onNodeWithText("Set up invited account").assertExists()
        compose.onNodeWithText("Continue").assertDoesNotExist()
        click("Show")
        compose.onNodeWithText("Hide").assertExists()
        click("Hide")
        compose.onNodeWithText("Show").assertExists()
        click("Change email or phone")
        compose.onNodeWithText("Continue").assertExists()
        compose.onNodeWithText("Password").assertDoesNotExist()
    }

    @Test
    fun requestingAccessAsksForNameAndRelationship() {
        click("Request household access")
        compose.onNodeWithText("Your name").assertExists()
        compose.onNodeWithText("Relationship to household").assertExists()
        compose.onNodeWithText("Request invitation").assertIsEnabled()
        click("Back")
        compose.onNodeWithText("Continue").assertExists()
        compose.onNodeWithText("Your name").assertDoesNotExist()
    }

    @Test
    fun invitedAccountSetupGoesFromResendToEnrollment() {
        showsPasswordStep()
        click("Set up invited account")
        compose.onNodeWithText("Send me a code").assertExists()
        click("Enter code or link")
        compose.onNodeWithText("Code from your text, or link from your email").assertExists()
        compose.onNodeWithText("Finish enrollment").assertIsNotEnabled()
        type("Display username", "Sam")
        type("Choose password (new members)", "synthetic long password")
        type("Confirm password", "synthetic long password")
        compose.onNodeWithText("Finish enrollment").assertIsEnabled()
        // A mismatched confirmation disables the button again.
        type("Confirm password", "!")
        compose.onNodeWithText("Finish enrollment").assertIsNotEnabled()
        // Leaving enrollment returns to the password step, not the first step.
        click("Back to sign-in")
        compose.onNodeWithText("Sign in").assertExists()
        compose.onNodeWithText("Continue").assertDoesNotExist()
    }

    @Test
    fun usernameMustBeAtLeastThreeCharacters() {
        click("Request household access")
        click("Back")
        showsPasswordStep()
        click("Set up invited account")
        click("Enter code or link")
        type("Display username", "Sa")
        type("Choose password (new members)", "synthetic long password")
        type("Confirm password", "synthetic long password")
        compose.onNodeWithText("Finish enrollment").assertIsNotEnabled()
        type("Display username", "m")
        compose.onNodeWithText("Finish enrollment").assertIsEnabled()
    }
}
