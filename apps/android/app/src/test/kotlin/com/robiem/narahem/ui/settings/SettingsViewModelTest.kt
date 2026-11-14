package com.robiem.narahem.ui.settings

import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.account.AccountRepository
import com.robiem.narahem.data.household.FakeHouseholdRepository
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.settings.FakeAppSettings
import com.robiem.narahem.tracking.FakeTrackingController
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.HouseholdSession
import com.robiem.narahem.ui.MainDispatcherRule
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SettingsViewModelTest {
    @get:Rule val main = MainDispatcherRule()
    private val account = Account("sam", true, "test", "a".repeat(32))
    private val household = FakeHouseholdRepository()
    private val tracking = FakeTrackingController()
    private val settings = FakeAppSettings()
    private var signedOut = false
    private val requests = mutableListOf<String>()

    private val accounts = object : AccountRepository {
        override suspend fun signIn(server: String, email: String, password: String) = account

        override suspend fun signOut() {
            signedOut = true
        }

        override suspend fun authenticated(path: String, payload: JSONObject?, method: String) =
            when (path) {
                "/api/account/username" -> {
                    requests += "$method $path"
                    JSONObject().put("username", payload!!.getString("username"))
                }

                else -> JSONObject().put("members", JSONArray())
            }

        override suspend fun requestEnrollment(server: String, email: String) = "Link sent."
    }

    /** A signed-in session on the test scheduler and its Settings view model. */
    private fun TestScope.screen(): Pair<HouseholdSession, SettingsViewModel> {
        val session = HouseholdSession(accounts, household, settings, this)
        session.current = AppState(account = account, restoring = false)
        return session to SettingsViewModel(session, accounts, household, tracking)
    }

    @Test fun findMyPhoneCanBeTurnedOnAndOff() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.setFindPhone(true)
        advanceUntilIdle()
        assertTrue(household.findPhone)
        assertTrue(session.current.findPhoneEnabled)
        assertTrue(session.current.message.startsWith("Find my phone enabled"))
        assertTrue("reportDevicePermissions" in household.calls)
        model.setFindPhone(false)
        advanceUntilIdle()
        assertFalse(household.findPhone)
        assertEquals(1, tracking.alarmStops)
        assertEquals("Find my phone disabled.", session.current.message)
        model.stopFindPhoneAlarm()
        assertEquals(2, tracking.alarmStops)
    }

    @Test fun phoneApprovalCodeIsRequestedAndConfirmed() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.requestPhoneCode()
        advanceUntilIdle()
        assertTrue(session.current.message.startsWith("Six-digit verification code sent"))
        model.confirmPhoneCode("123456")
        advanceUntilIdle()
        assertTrue("verifyPhoneCode" in household.calls)
        assertEquals("ready", session.current.deviceStatus)
        assertTrue(session.current.audienceLoaded)
        model.restartPhoneRegistration("https://family.example")
        advanceUntilIdle()
        assertEquals(listOf("discardPendingPhone", "enroll"), household.calls.takeLast(2))
    }

    @Test fun firstDeviceSetupAndFingerprintCheckRefreshTheDevice() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.sendBootstrapCode()
        advanceUntilIdle()
        assertTrue(session.current.message.contains("administrator email"))
        model.finishBootstrap("123456")
        advanceUntilIdle()
        model.verifyHousehold("owner-fingerprint")
        advanceUntilIdle()
        assertTrue(
            household.calls.containsAll(listOf("bootstrapWithEmail", "verifyOwnerFingerprint"))
        )
        assertEquals("owner-fingerprint", session.current.ownerFingerprint)
    }

    @Test fun revokingThePhoneSignsOutOrExplainsWhyItCouldNot() = runTest(main.dispatcher) {
        val (session, model) = screen()
        household.failing += "revokeOwnPhone"
        tracking.sharing = true
        model.revokeThisPhone()
        advanceUntilIdle()
        assertFalse(tracking.sharing)
        assertTrue(session.current.error)
        assertEquals("revokeOwnPhone failed", session.current.message)
        assertFalse(signedOut)
        household.failing.clear()
        model.revokeThisPhone()
        advanceUntilIdle()
        assertTrue(signedOut)
        assertNull(session.current.account)
    }

    @Test fun usernameMustBeValidBeforeItIsSent() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.changeUsername("x")
        advanceUntilIdle()
        assertTrue(session.current.error)
        assertTrue(requests.isEmpty())
        model.changeUsername("  sam.lee ")
        advanceUntilIdle()
        assertEquals(listOf("PUT /api/account/username"), requests)
        assertEquals("sam.lee", session.current.account!!.name)
        assertEquals("Username updated to sam.lee.", session.current.message)
    }

    @Test fun sharingCanBePausedAndResumed() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.setSharing(false)
        advanceUntilIdle()
        assertFalse(household.sharing)
        assertFalse(session.current.sharing)
        assertTrue(session.current.message.startsWith("Sharing paused"))
        model.setSharing(true)
        advanceUntilIdle()
        assertTrue(session.current.sharing)
        assertEquals("Sharing this phone's location is on.", session.current.message)
    }

    @Test fun audienceChangesNeedFreshChoices() = runTest(main.dispatcher) {
        val (session, model) = screen()
        val kim = "c".repeat(32)
        model.setSharingAudience(setOf(kim))
        advanceUntilIdle()
        assertEquals("Refresh location visibility choices first.", session.current.message)
        session.update {
            it.copy(audienceLoaded = true, audienceChoices = listOf(HouseholdPerson(kim, "Kim")))
        }
        model.setSharingAudience(setOf(kim, account.id))
        advanceUntilIdle()
        assertEquals(setOf(kim), household.audience)
        assertEquals(setOf(kim), session.current.audience)
        household.audience = emptySet()
        model.setSharingAudience(setOf(kim))
        advanceUntilIdle()
        assertTrue(household.audience.isEmpty())
        session.update { it.copy(syncProblem = true) }
        model.setSharingAudience(emptySet())
        advanceUntilIdle()
        assertEquals("Refresh household members before changing sharing.", session.current.message)
    }

    @Test fun ownerBrowserAccessNeedsAnOwnerViewer() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.setOwnerBrowserAccess(true)
        advanceUntilIdle()
        assertEquals("No approved household owner viewer is available.", session.current.message)
        val viewer = "f".repeat(32)
        session.update { it.copy(ownerViewerId = viewer, audienceLoaded = true) }
        model.setOwnerBrowserAccess(true)
        advanceUntilIdle()
        assertEquals(setOf(viewer), household.audience)
        assertTrue(session.current.message.contains("can now see"))
        model.setOwnerBrowserAccess(false)
        advanceUntilIdle()
        assertTrue(household.audience.isEmpty())
        assertTrue(session.current.message.contains("won't receive"))
    }

    @Test fun profilePhotoNeedsAnAccount() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.saveProfilePhoto("data:image/jpeg;base64,AA==")
        advanceUntilIdle()
        assertTrue("saveProfilePhoto" in household.calls)
        assertEquals("Your photo has been saved for the household map.", session.current.message)
        model.photoError("Photo too large")
        assertEquals("Photo too large", session.current.message)
        assertTrue(session.current.error)
        session.update { it.copy(account = null) }
        model.saveProfilePhoto("data:image/jpeg;base64,AA==")
        advanceUntilIdle()
        assertEquals("Sign in first", session.current.message)
    }

    @Test fun emailConfirmationLinkCanBeResent() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.resendEmailConfirmation("http://plain.example", "sam@example.invalid")
        advanceUntilIdle()
        assertTrue(session.current.fields.containsKey("server"))
        model.resendEmailConfirmation("https://family.example", "sam@example.invalid")
        advanceUntilIdle()
        assertEquals("enroll", session.current.onboarding)
        assertEquals("Link sent.", session.current.message)
    }

    @Test fun addressLookupDevicePrepAndSignOut() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.setAddressLookup(true)
        assertTrue(settings.addressLookup)
        assertTrue(session.phoneSettings.value.addressLookup)
        household.deviceStatus = "register"
        model.prepareDevice("https://family.example")
        advanceUntilIdle()
        assertTrue("enroll" in household.calls)
        tracking.sharing = true
        model.signOut()
        advanceUntilIdle()
        assertFalse(tracking.sharing)
        assertNull(session.current.account)
    }
}
