package com.robiem.narahem.ui

import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.account.AccountRepository
import com.robiem.narahem.data.account.AccountRequestException
import com.robiem.narahem.data.household.FakeHouseholdRepository
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.household.HouseholdRepository
import com.robiem.narahem.data.household.HouseholdTrip
import com.robiem.narahem.data.location.AddressLookup
import com.robiem.narahem.data.location.FakeAddressLookup
import com.robiem.narahem.data.location.LocalFix
import com.robiem.narahem.data.location.LocationRepository
import com.robiem.narahem.data.settings.AppSettings
import com.robiem.narahem.data.settings.FakeAppSettings
import com.robiem.narahem.data.settings.MapCamera
import com.robiem.narahem.data.trips.TripHistory
import com.robiem.narahem.tracking.FakeTrackingController
import com.robiem.narahem.tracking.TrackingController
import com.robiem.narahem.ui.map.MapViewModel
import com.robiem.narahem.ui.places.PlacesViewModel
import com.robiem.narahem.ui.settings.SettingsViewModel
import com.robiem.narahem.ui.signin.SignInViewModel
import com.robiem.narahem.ui.trips.TripsViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AppViewModelTest {
    @Test fun pendingEmailAndLocalFixRemainSeparateFromSharing() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            var signedOut = false
            val accounts = object : AccountRepository {
                override suspend fun signIn(server: String, email: String, password: String) =
                    Account("Synthetic", false, "test")
                override suspend fun signOut() {
                    signedOut = true
                }
            }
            val locations = object : LocationRepository {
                override suspend fun current() = LocalFix(1.0, 2.0, 30f)
            }
            val model = ViewModels(accounts, locations)
            model.signInScreen.signIn(
                "https://example.invalid",
                "test@example.invalid",
                "synthetic"
            )
            advanceUntilIdle()
            assertFalse(model.state.value.account!!.verified)
            model.mapScreen.locate()
            advanceUntilIdle()
            assertEquals(1.0, model.state.value.fix!!.latitude, 0.0)
            model.settingsScreen.signOut()
            advanceUntilIdle()
            assertTrue(signedOut)
            assertNull(model.state.value.fix)
            assertNull(model.state.value.account)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test fun wrongPasswordStaysOnSignInWithoutRequestingEnrollment() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            var requested = false
            var completed = false
            val accounts = object : AccountRepository {
                override suspend fun signIn(
                    server: String,
                    email: String,
                    password: String
                ): Account = throw AccountRequestException(401, "Complete your invitation.")
                override suspend fun signOut() {}
                override suspend fun requestEnrollment(server: String, email: String): String {
                    requested = true
                    return "Check your email"
                }
                override suspend fun completeEnrollment(
                    server: String,
                    token: String,
                    username: String,
                    password: String,
                    contact: String
                ) {
                    completed = true
                }
            }
            val model =
                ViewModels(
                    accounts,
                    object : LocationRepository {
                        override suspend fun current(): LocalFix = error("Unused")
                    }
                )
            model.signInScreen.signIn("example.invalid", "member@example.invalid", "test")
            advanceUntilIdle()
            assertFalse(requested)
            assertEquals("signin", model.state.value.onboarding)
            assertTrue(model.state.value.message.contains("Email or password"))
            model.signInScreen.findInvitation("example.invalid", "member@example.invalid")
            advanceUntilIdle()
            assertTrue(requested)
            assertEquals("enroll", model.state.value.onboarding)
            assertNull(model.state.value.account)
            model.signInScreen.completeInvitation("example.invalid", "token", "user", "password")
            advanceUntilIdle()
            assertTrue(completed)
            assertEquals("signin", model.state.value.onboarding)
            assertNull(model.state.value.account)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test fun invalidServerHighlightsAddressWithoutSendingCredentials() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val accounts = object : AccountRepository {
                override suspend fun signIn(
                    server: String,
                    email: String,
                    password: String
                ): Account = error("Must not send credentials")
                override suspend fun signOut() {}
            }
            val model =
                ViewModels(
                    accounts,
                    object : LocationRepository {
                        override suspend fun current(): LocalFix = error("Unused")
                    }
                )
            model.signInScreen.signIn("http://example.invalid", "member@example.invalid", "test")
            advanceUntilIdle()
            assertTrue(model.state.value.error)
            assertTrue(model.state.value.fields.containsKey("server"))
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test fun locationRequiresSignInAndDeniedPermissionHasFeedback() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            var called = false
            val accounts = object : AccountRepository {
                override suspend fun signIn(server: String, email: String, password: String) =
                    error("Unused")
                override suspend fun signOut() {}
            }
            val locations = object : LocationRepository {
                override suspend fun current(): LocalFix {
                    called = true
                    error("Unused")
                }
            }
            val model = ViewModels(accounts, locations)
            model.mapScreen.locate()
            advanceUntilIdle()
            assertFalse(called)
            assertEquals("Sign in first.", model.state.value.message)
            model.app.permissionDenied()
            assertTrue(model.state.value.message.contains("permission was denied"))
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test fun cachedPhoneLocationSeedsReopenAndLateGpsCannotRestoreSignedOutLocation() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val accounts = object : AccountRepository {
                override suspend fun signIn(server: String, email: String, password: String) =
                    Account("Synthetic", true, "test")
                override suspend fun signOut() {}
            }
            val model = ViewModels(
                accounts,
                object : LocationRepository {
                    override fun lastKnown() = LocalFix(1.0, 2.0, 20f)
                    override suspend fun current(): LocalFix {
                        kotlinx.coroutines.delay(1000)
                        return LocalFix(3.0, 4.0, 10f)
                    }
                }
            )
            model.signInScreen.signIn(
                "https://example.invalid",
                "test@example.invalid",
                "synthetic"
            )
            advanceUntilIdle()
            model.mapScreen.centerMapOnPhone()
            assertEquals(1.0, model.state.value.fix!!.latitude, 0.0)
            runCurrent()
            model.settingsScreen.signOut()
            advanceUntilIdle()
            assertNull(model.state.value.account)
            assertNull(model.state.value.fix)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test fun trustedPhoneLoadsHouseholdAndSavesAndDeletesPlaces() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val accounts = object : AccountRepository {
                override suspend fun signIn(server: String, email: String, password: String) =
                    Account("Sam", verified = true, household = "test", id = "account-1")
                override suspend fun signOut() {}
            }
            val locations = object : LocationRepository {
                override suspend fun current() = LocalFix(1.0, 2.0, 30f)
            }
            val household = FakeHouseholdRepository(
                people = listOf(HouseholdPerson("account-2", "Alex", 40.0, -74.0))
            )
            val model = ViewModels(accounts, locations, household)
            model.signInScreen.signIn("https://example.invalid", "sam@example.invalid", "synthetic")
            advanceUntilIdle()
            model.app.session.refreshHousehold()
            advanceUntilIdle()
            assertEquals("ready", model.state.value.deviceStatus)
            assertEquals(listOf("Alex"), model.state.value.people.map { it.name })

            model.placesScreen.savePlace("Home", 40.0, -74.0, 100.0)
            advanceUntilIdle()
            val home = model.state.value.places.single()
            assertEquals("Home", home.name)
            assertEquals("Place saved.", model.state.value.message)

            model.placesScreen.deletePlace(home)
            advanceUntilIdle()
            assertTrue(model.state.value.places.isEmpty())
            assertEquals("Place deleted.", model.state.value.message)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test fun phoneSettingsAndBackgroundSharingFollowConsentAndDeviceState() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val settings = FakeAppSettings()
            val tracking = FakeTrackingController()
            val model = ViewModels(
                signedInAccounts(),
                fixedLocation(),
                FakeHouseholdRepository(),
                settings = settings,
                tracking = tracking
            )
            model.signInScreen.signIn("HTTPS://Family.Example/", "sam@example.invalid", "synthetic")
            advanceUntilIdle()
            assertEquals("https://family.example", settings.serverUrl)
            assertEquals("https://family.example", model.app.savedServer)

            model.app.session.refreshHousehold()
            advanceUntilIdle()
            // Without consent to share, the service stays off even with permission.
            model.app.syncBackgroundSharing(hasLocation = true)
            assertFalse(tracking.sharing)

            model.app.acceptMapConsent()
            assertTrue(settings.mapConsent)
            assertTrue(model.app.phoneSettings.value.mapConsent)
            model.app.syncBackgroundSharing(hasLocation = true)
            assertTrue(tracking.sharing)
            model.app.syncBackgroundSharing(hasLocation = false)
            assertFalse(tracking.sharing)

            model.mapScreen.rememberMapCamera(MapCamera(40.0, -74.0, 12.0))
            assertEquals(12.0, settings.mapCamera!!.zoom, 0.0)
            assertTrue(model.app.takeFirstLaunchLocationPrompt())
            assertFalse(model.app.takeFirstLaunchLocationPrompt())

            model.app.syncBackgroundSharing(hasLocation = true)
            model.settingsScreen.setFindPhone(false)
            advanceUntilIdle()
            assertEquals(1, tracking.alarmStops)
            model.settingsScreen.signOut()
            advanceUntilIdle()
            assertFalse(tracking.sharing)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test fun addressSearchReportsWhereItFoundThePlaceOrExplains() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val addresses = FakeAddressLookup(found = mapOf("Library" to (40.5 to -74.5)))
            val model = ViewModels(signedInAccounts(), fixedLocation(), addresses = addresses)
            var found: Pair<Double, Double>? = null
            model.placesScreen.findAddress(" Library ") { lat, lon -> found = lat to lon }
            advanceUntilIdle()
            assertEquals(40.5 to -74.5, found)

            model.placesScreen.findAddress("Nowhere") { _, _ -> error("Nothing should be found") }
            advanceUntilIdle()
            assertTrue(model.state.value.error)
            assertTrue(model.state.value.message.startsWith("Address not found"))
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test fun memberTripsLoadIntoTheSharedStateAndClearAtSignOut() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val trip = HouseholdTrip("trip-1", "account-2", 1_000, 61_000, 1200.0, 15.0, 30)
            val household = FakeHouseholdRepository(
                trips = TripHistory(listOf(trip), emptyList(), hasEarlier = true)
            )
            val model = ViewModels(signedInAccounts(), fixedLocation(), household)
            val trips = TripsViewModel(model.app.session, household, FakeAddressLookup())
            model.signInScreen.signIn("https://example.invalid", "sam@example.invalid", "x")
            advanceUntilIdle()

            trips.loadMemberTrips("account-2", days = 7)
            advanceUntilIdle()
            assertEquals("account-2", model.state.value.tripsForMember)
            assertEquals(7, model.state.value.tripDays)
            assertEquals(listOf("trip-1"), model.state.value.trips.map { it.id })
            assertTrue(model.state.value.tripHistoryPartial)
            assertFalse(model.state.value.tripsLoading)

            model.settingsScreen.signOut()
            advanceUntilIdle()
            assertNull(model.state.value.tripsForMember)
            assertTrue(model.state.value.trips.isEmpty())
        } finally {
            Dispatchers.resetMain()
        }
    }
}

private fun signedInAccounts() = object : AccountRepository {
    override suspend fun signIn(server: String, email: String, password: String) =
        Account("Sam", verified = true, household = "test", id = "account-1")

    override suspend fun signOut() {}
}

private fun fixedLocation() = object : LocationRepository {
    override suspend fun current() = LocalFix(1.0, 2.0, 30f)
}

/** The app and screen view models around one session, with in-memory fakes by default. */
private class ViewModels(
    accounts: AccountRepository,
    locations: LocationRepository,
    household: HouseholdRepository? = null,
    settings: AppSettings = FakeAppSettings(),
    addresses: AddressLookup = FakeAddressLookup(),
    tracking: TrackingController = FakeTrackingController()
) {
    val app = AppViewModel(accounts, household, settings, tracking)
    val signInScreen = SignInViewModel(app.session, accounts)
    val mapScreen = MapViewModel(app.session, locations, household, addresses)
    val placesScreen = PlacesViewModel(app.session, household, addresses)
    val settingsScreen = SettingsViewModel(app.session, accounts, household, tracking)
    val state = app.state
}
