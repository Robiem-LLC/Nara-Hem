package com.robiem.narahem

import androidx.compose.ui.test.junit4.ComposeTestRule
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.account.AccountRepository
import com.robiem.narahem.data.household.FakeHouseholdRepository
import com.robiem.narahem.data.location.FakeAddressLookup
import com.robiem.narahem.data.location.LocalFix
import com.robiem.narahem.data.location.LocationRepository
import com.robiem.narahem.data.settings.FakeAppSettings
import com.robiem.narahem.tracking.FakeTrackingController
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.shadows.ShadowToast

/** The signed-in screens of the real MainActivity, with a fake server and GPS. */
@RunWith(AndroidJUnit4::class)
class SignedInScreensTest {
    @get:Rule
    val compose: ComposeTestRule = createEmptyComposeRule()
    private var signedOut = false
    private lateinit var scenario: ActivityScenario<MainActivity>

    private val accounts = object : AccountRepository {
        override suspend fun signIn(server: String, email: String, password: String) =
            Account("Sam", verified = true, household = "Synthetic household", id = "account-1")

        override suspend fun signOut() {
            signedOut = true
        }
    }

    private val locations = object : LocationRepository {
        override suspend fun current() = LocalFix(40.0, -74.0, 20f)
    }

    /** Signs in to a household where this phone has reached [status]. */
    private val tracking = FakeTrackingController()

    private fun tab(name: String) = compose.onAllNodesWithText(name)[0].performClick()

    private fun signIn(status: String = "ready", joined: List<String> = emptyList()) {
        val household = FakeHouseholdRepository(deviceStatus = status).apply {
            enrolledStatus = status
            newMembers = joined
        }
        MainActivity.testContainer = object : AppContainer {
            override val accounts = this@SignedInScreensTest.accounts
            override val locations = this@SignedInScreensTest.locations
            override val household = household
            override val settings = FakeAppSettings()
            override val addresses = FakeAddressLookup()
            override val tracking = this@SignedInScreensTest.tracking
        }
        scenario = ActivityScenario.launch(MainActivity::class.java)
        type("Server address", "https://family.example")
        type("Email or phone number", "sam@example.invalid")
        click("Continue")
        type("Password", "synthetic long password")
        click("Sign in")
        // First sign-in on a set-up phone asks before loading the map provider's tiles.
        val consent = "Share your location with your household?"
        if (compose.onAllNodesWithText(consent).fetchSemanticsNodes().isNotEmpty()) click("Not now")
    }

    @After
    fun close() {
        scenario.close()
        MainActivity.testContainer = null
    }

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

    @Test
    fun signingInShowsTheFourTabs() {
        signIn()
        for (name in listOf("Map", "Trips", "Places", "Settings")) {
            assertTrue(name, compose.onAllNodesWithText(name).fetchSemanticsNodes().isNotEmpty())
        }
        compose.onNodeWithText("Server address").assertDoesNotExist()
    }

    @Test
    fun aPhoneThatIsNotSetUpShowsOnlyItsSetup() {
        signIn(status = "email-code")
        compose.onNodeWithText("Send verification code").assertExists()
        for (name in listOf("Map", "Trips", "Places")) {
            compose.onNodeWithText(name).assertDoesNotExist()
        }
    }

    @Test
    fun settingsShowTheAccountAndSignOut() {
        signIn()
        tab("Settings")
        compose.onNodeWithText("Sam").assertExists()
        click("Account & about")
        compose.onNodeWithText("Sign out").assertExists()
    }

    @Test
    fun placesOffersAddingAPlace() {
        signIn()
        tab("Places")
        compose.onNodeWithText("Add a Place").assertExists()
    }

    @Test
    fun tripsWithNoHouseholdDataSayNoTrips() {
        signIn()
        tab("Trips")
        compose.onNodeWithText("No trips").assertExists()
    }

    @Test
    fun signingOutReturnsToSignIn() {
        signIn()
        tab("Settings")
        click("Account & about")
        click("Sign out")
        compose.onNodeWithText("Server address").assertExists()
        assertTrue(signedOut)
    }

    @Test
    fun aNewMemberIsAnnouncedAndSentALocation() {
        signIn(joined = listOf("Kim"))
        compose.waitForIdle()
        assertEquals(
            "Kim has joined the household. Your location is being shared with them.",
            ShadowToast.getTextOfLatestToast()
        )
        assertEquals(1, tracking.checkIns)
    }
}
