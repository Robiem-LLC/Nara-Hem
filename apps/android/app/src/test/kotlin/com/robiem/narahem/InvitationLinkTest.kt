package com.robiem.narahem

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.ui.test.junit4.ComposeTestRule
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Invitation links (narahem://join?server=...&token=...) open the app on enrollment. */
@RunWith(AndroidJUnit4::class)
class InvitationLinkTest {
    @get:Rule
    val compose: ComposeTestRule = createEmptyComposeRule()

    private fun launch(server: String, token: String): ActivityScenario<MainActivity> {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val link = Uri.parse("narahem://join?server=" + Uri.encode(server) + "&token=$token")
        return ActivityScenario.launch(
            Intent(Intent.ACTION_VIEW, link, context, MainActivity::class.java)
        )
    }

    @Test
    fun linkOnFreshInstallOpensEnrollmentForThatServer() {
        launch("https://family.example", "synthetic-token").use {
            compose.onNodeWithText("https://family.example").assertExists()
            compose.onNodeWithText("synthetic-token").assertExists()
            compose.onNodeWithText("Finish enrollment").assertExists()
        }
    }

    @Test
    fun linkForAnotherServerAsksBeforeSwitching() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("server", Context.MODE_PRIVATE).edit()
            .putString("url", "https://home.example").commit()
        launch("https://other.example", "synthetic-token").use {
            compose.onNodeWithText("Different server in this link").assertExists()
            compose.onNodeWithText("Keep home.example").performClick()
            compose.onNodeWithText("Different server in this link").assertDoesNotExist()
            compose.onNodeWithText("https://home.example").assertExists()
            compose.onNodeWithText("Finish enrollment").assertDoesNotExist()
        }
    }

    @Test
    fun switchingToTheLinkServerOpensEnrollment() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("server", Context.MODE_PRIVATE).edit()
            .putString("url", "https://home.example").commit()
        launch("https://other.example", "synthetic-token").use {
            compose.onNodeWithText("Switch to other.example").performClick()
            compose.onNodeWithText("https://other.example").assertExists()
            compose.onNodeWithText("Finish enrollment").assertExists()
        }
    }
}
