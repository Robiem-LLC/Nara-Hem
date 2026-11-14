package com.robiem.narahem.ui.signin

import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.theme.NaraHemTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** The signed-out screens on their own: state in, actions out. */
@RunWith(AndroidJUnit4::class)
class SignInContentTest {
    @get:Rule
    val compose = createComposeRule()
    private val events = mutableListOf<String>()

    private fun show(state: AppState, form: SignInForm) = compose.setContent {
        NaraHemTheme {
            SignInContent(
                state = state,
                form = form,
                onRetryRememberedSignIn = { events += "retry" },
                onResendInvitation = { events += "resend" },
                onShow = { events += "show:$it" },
                onFinishEnrollment = { events += "finish" },
                onRequestInvitation = { events += "request" },
                onSignIn = { events += "sign-in" }
            )
        }
    }

    @Test fun continueNeedsAnAddressAndThenAsksForThePassword() {
        val form = SignInForm()
        show(AppState(restoring = false), form)
        compose.onNodeWithText("Continue").performClick()
        assertEquals(true, form.firstStep)

        compose.onNodeWithText("Server address").performTextInput("https://family.example")
        compose.onNodeWithText("Email or phone number").performTextInput("sam@example.invalid")
        compose.onNodeWithText("Continue").performClick()
        assertEquals(false, form.firstStep)

        compose.onNodeWithText("Password").performTextInput("synthetic")
        compose.onNodeWithText("Sign in").performScrollTo().performClick()
        assertEquals("synthetic", form.password)
        assertEquals(listOf("sign-in"), events)
    }

    @Test fun enrollmentWaitsForMatchingPasswordsAndAUsername() {
        val form = SignInForm(server = "https://family.example", confirmation = "token")
        show(AppState(restoring = false, onboarding = "enroll"), form)
        compose.onNodeWithText("Display username").performTextInput("sam")
        compose.onNodeWithText("Choose password (new members)").performTextInput("one")
        compose.onNodeWithText("Confirm password").performTextInput("two")
        compose.onNodeWithText("Finish enrollment").performScrollTo().assertIsNotEnabled()

        compose.onNodeWithText("Request access").performScrollTo().performClick()
        assertEquals(listOf("show:request"), events)
    }
}
