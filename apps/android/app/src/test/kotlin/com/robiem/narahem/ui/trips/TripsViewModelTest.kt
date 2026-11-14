package com.robiem.narahem.ui.trips

import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.account.AccountRepository
import com.robiem.narahem.data.household.FakeHouseholdRepository
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.household.HouseholdTrip
import com.robiem.narahem.data.location.FakeAddressLookup
import com.robiem.narahem.data.settings.FakeAppSettings
import com.robiem.narahem.data.trips.TripHistory
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.HouseholdSession
import com.robiem.narahem.ui.MainDispatcherRule
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class TripsViewModelTest {
    @get:Rule val main = MainDispatcherRule()
    private val member = "c".repeat(32)
    private val trip = HouseholdTrip("t1", member, 1_000, 61_000, 900.0, 12.0, 30)

    private val household =
        FakeHouseholdRepository(trips = TripHistory(listOf(trip), emptyList(), true))

    private val accounts = object : AccountRepository {
        override suspend fun signIn(server: String, email: String, password: String) =
            Account("sam", true, "test")

        override suspend fun signOut() {}
    }

    private fun TestScope.screen(): Pair<HouseholdSession, TripsViewModel> {
        val session = HouseholdSession(accounts, household, FakeAppSettings(), this)
        session.current = AppState(account = Account("sam", true, "test", "a".repeat(32)))
        return session to TripsViewModel(session, household, FakeAddressLookup(::nearby))
    }

    /** Answers north of the equator and fails elsewhere, like a lookup that went offline. */
    private fun nearby(latitude: Double, longitude: Double): String =
        if (latitude > 0) "1 High St" else error("Offline at $longitude")

    @Test fun summariesThenFullHistoryLoadForTheChosenMember() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.loadMemberTrips(member, days = 3)
        assertTrue(session.current.tripsLoading)
        assertEquals(3, session.current.tripDays)
        advanceUntilIdle()
        assertEquals(listOf(trip), session.current.trips)
        assertTrue(session.current.tripHistoryPartial)
        assertFalse(session.current.tripsLoading)
        assertTrue("tripHistory" in household.calls)
        model.clearMemberTrips()
        assertNull(session.current.tripsForMember)
        assertTrue(session.current.trips.isEmpty())
    }

    @Test fun completeSummariesSkipTheFullHistory() = runTest(main.dispatcher) {
        val (session, model) = screen()
        household.summariesComplete = true
        model.loadMemberTrips(member)
        advanceUntilIdle()
        assertEquals(listOf(trip), session.current.trips)
        assertFalse("tripHistory" in household.calls)
    }

    @Test fun failuresExplainWhetherSummariesWereShown() = runTest(main.dispatcher) {
        val (session, model) = screen()
        household.failing += "tripSummaries"
        model.loadMemberTrips(member)
        advanceUntilIdle()
        assertEquals("Could not load trip history. Retry when online.", session.current.tripsError)
        household.failing.clear()
        household.failing += "tripHistory"
        model.loadMemberTrips(member)
        advanceUntilIdle()
        assertEquals(
            "Detailed routes could not load. Retry when online.",
            session.current.tripsError
        )
        assertEquals(listOf(trip), session.current.trips)
    }

    @Test fun openTabRefreshesEveryTwentyFiveSeconds() = runTest(main.dispatcher) {
        val (session, model) = screen()
        session.update { it.copy(people = listOf(HouseholdPerson(member, "Kim"))) }
        val refresh = backgroundScope.launch { model.refreshTripsWhileOpen { null } }
        advanceTimeBy(24_000)
        runCurrent()
        assertNull(session.current.tripsForMember)
        advanceTimeBy(2_000)
        runCurrent()
        assertEquals(member, session.current.tripsForMember)
        refresh.cancel()
    }

    @Test fun addressesNearTripEndsFailQuietly() = runTest(main.dispatcher) {
        val (_, model) = screen()
        assertEquals("1 High St", model.addressNear(1.0, 2.0))
        assertNull(model.addressNear(-1.0, 2.0))
    }
}
