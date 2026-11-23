package com.robiem.narahem.ui.signin

import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.account.AccountRepository
import com.robiem.narahem.data.account.AccountRequestException
import com.robiem.narahem.data.settings.FakeAppSettings
import com.robiem.narahem.ui.HouseholdSession
import com.robiem.narahem.ui.MainDispatcherRule
import java.io.IOException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SignInViewModelTest {
    @get:Rule val main = MainDispatcherRule()
    private val server = "https://family.example"
    private val settings = FakeAppSettings()
    private var restored: Account? = null
    private var restoreFails = false
    private var signInStatus = 0
    private val calls = mutableListOf<String>()

    private val accounts = object : AccountRepository {
        override suspend fun signIn(server: String, email: String, password: String): Account {
            if (signInStatus != 0) {
                throw AccountRequestException(signInStatus, "Server error $signInStatus")
            }
            return Account("sam", true, "test")
        }

        override suspend fun signOut() {}

        override suspend fun restoreSession(server: String): Account? {
            if (restoreFails) throw IOException("Offline")
            return restored
        }

        override suspend fun claimInvitation(
            server: String,
            email: String,
            username: String,
            password: String
        ) = "Use the emailed link.".also { calls += "claim" }

        override suspend fun requestEnrollment(server: String, email: String) = "Link sent.".also {
            calls +=
                "enroll"
        }

        override suspend fun completeEnrollment(
            server: String,
            token: String,
            username: String,
            password: String
        ) {
            calls += "complete"
        }

        override suspend fun register(
            server: String,
            contact: String,
            username: String,
            password: String
        ) {
            calls += "register:$contact:$username"
        }

        override suspend fun requestInvitation(
            server: String,
            email: String,
            name: String,
            relationship: String
        ) = "Request sent.".also { calls += "request" }
    }

    private fun TestScope.screen(): Pair<HouseholdSession, SignInViewModel> {
        val session = HouseholdSession(accounts, null, settings, this)
        return session to SignInViewModel(session, accounts)
    }

    @Test fun rememberedSessionIsRestoredOnce() = runTest(main.dispatcher) {
        val (session, model) = screen()
        restored = Account("sam", true, "test")
        model.restoreSession(server)
        advanceUntilIdle()
        assertEquals("sam", session.current.account!!.name)
        assertEquals(server, settings.serverUrl)
        restored = null
        model.restoreSession(server)
        advanceUntilIdle()
        assertEquals("sam", session.current.account!!.name)
        model.retryRememberedSession(server)
        assertFalse(session.current.restoring)
    }

    @Test fun noRememberedSessionShowsSignIn() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.restoreSession(server)
        advanceUntilIdle()
        assertFalse(session.current.restoring)
        assertNull(session.current.account)
    }

    @Test fun offlineRestoreKeepsTheSessionAndCanRetry() = runTest(main.dispatcher) {
        val (session, model) = screen()
        restoreFails = true
        model.restoreSession(server)
        advanceUntilIdle()
        assertTrue(session.current.syncProblem)
        assertTrue(session.current.message.startsWith("Unable to reconnect"))
        restoreFails = false
        restored = Account("sam", true, "test")
        model.retryRememberedSession(server)
        advanceUntilIdle()
        assertEquals("sam", session.current.account!!.name)
    }

    @Test fun signInReportsWrongPasswordsAndOtherErrors() = runTest(main.dispatcher) {
        val (session, model) = screen()
        signInStatus = 401
        model.signIn(server, "sam@example.invalid", "wrong")
        advanceUntilIdle()
        assertEquals("Email or password is incorrect. Please try again.", session.current.message)
        signInStatus = 503
        model.signIn(server, "sam@example.invalid", "pw")
        advanceUntilIdle()
        assertEquals("Server error 503", session.current.message)
        signInStatus = 0
        model.signIn(server, "sam@example.invalid", "pw")
        advanceUntilIdle()
        assertEquals("Signed in.", session.current.message)
    }

    @Test fun registeringSignsStraightIn() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.register(server, "+14155550123", "John Doe", "a long synthetic password")
        advanceUntilIdle()
        assertEquals("register:+14155550123:John Doe", calls.first())
        assertEquals("Signed in.", session.current.message)
    }

    @Test fun invitationStepsMoveBetweenScreens() = runTest(main.dispatcher) {
        val (session, model) = screen()
        model.onboarding("request")
        assertEquals("request", session.current.onboarding)
        model.findInvitation(server, "sam@example.invalid")
        advanceUntilIdle()
        assertEquals("enroll", session.current.onboarding)
        model.completeInvitation(server, "token", "sam", "password")
        advanceUntilIdle()
        assertEquals("signin", session.current.onboarding)
        assertTrue(session.current.message.startsWith("Email confirmed."))
        model.claimInvitation(server, "sam@example.invalid", "sam", "password")
        advanceUntilIdle()
        assertEquals("Use the emailed link.", session.current.message)
        model.requestInvitation(server, "sam@example.invalid", "Sam", "Child")
        advanceUntilIdle()
        assertEquals("Request sent.", session.current.message)
        assertEquals(listOf("enroll", "complete", "claim", "request"), calls)
        model.requestInvitation("not a url/", "sam@example.invalid", "Sam", "Child")
        advanceUntilIdle()
        assertTrue(session.current.fields.containsKey("server"))
    }
}
