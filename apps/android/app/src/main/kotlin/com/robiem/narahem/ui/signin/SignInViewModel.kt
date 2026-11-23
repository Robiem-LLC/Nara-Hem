package com.robiem.narahem.ui.signin

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.robiem.narahem.data.account.AccountRepository
import com.robiem.narahem.data.account.AccountRequestException
import com.robiem.narahem.data.account.validateServer
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.HouseholdSession
import kotlinx.coroutines.launch

/** View model for sign-in, session restore, and invitation enrollment. */
class SignInViewModel(
    private val session: HouseholdSession,
    private val accounts: AccountRepository
) : ViewModel() {
    /** Runs [task] through [HouseholdSession.work]. */
    private fun work(task: suspend () -> Unit) = session.work(task)

    /** Restores the stored session at launch using the refresh token. */
    fun restoreSession(server: String) {
        if (!session.current.restoring) return
        viewModelScope.launch {
            try {
                val account = accounts.restoreSession(server)
                if (account != null) {
                    session.rememberServer(server)
                    session.current = AppState(account = account, restoring = false)
                } else {
                    session.update { it.copy(restoring = false) }
                }
            } catch (failure: Exception) {
                session.update {
                    it.copy(
                        restoring = false,
                        error = true,
                        syncProblem = true,
                        message = "Unable to reconnect. Your sign-in is remembered; check " +
                            "the network and reopen or retry."
                    )
                }
            }
        }
    }

    /** Retries restoring the stored session, for example after a network error. */
    fun retryRememberedSession(server: String) {
        if (session.current.account != null) return
        session.update { it.copy(restoring = true, message = "", error = false) }
        restoreSession(server)
    }

    /** Signs in and prepares the device. */
    fun signIn(server: String, email: String, password: String) = work {
        validateServer(server)
        try {
            val account = accounts.signIn(server, email, password)
            session.rememberServer(server)
            session.current =
                AppState(account = account, busy = true, restoring = false, message = "Signed in.")
        } catch (failure: AccountRequestException) {
            if (failure.status != 401) throw failure
            session.update {
                it.copy(
                    onboarding = "signin",
                    error = true,
                    message = "Email or password is incorrect. Please try again."
                )
            }
        }
    }

    /** Switches between the sign-in and invitation screens. */
    fun onboarding(screen: String) {
        if (!session.current.busy) {
            session.update {
                it.copy(onboarding = screen, message = "", error = false, fields = emptyMap())
            }
        }
    }

    /**
     * Calls the legacy invitation endpoint, which the server rejects with directions to the email
     * link.
     */
    fun claimInvitation(server: String, email: String, username: String, password: String) = work {
        validateServer(server)
        val message = accounts.claimInvitation(server, email, username, password)
        session.update { it.copy(onboarding = "signin", message = message) }
    }

    /** Asks the server for a new invitation link by email, or a code by text. */
    fun findInvitation(server: String, email: String) = work {
        validateServer(server)
        val message = accounts.requestEnrollment(server, email)
        session.update { it.copy(onboarding = "enroll", message = message) }
    }

    /** Completes an invitation and signs in. */
    fun completeInvitation(
        server: String,
        token: String,
        username: String,
        password: String,
        contact: String = ""
    ) = work {
        validateServer(server)
        accounts.completeEnrollment(server, token, username, password, contact)
        session.update {
            it.copy(
                onboarding = "signin",
                message = "Account confirmed. Sign in with your chosen password for a new " +
                    "invitation, or your existing password for an existing account. " +
                    "Device approval is a separate step."
            )
        }
    }

    /** Sends a request for the admin to invite this person. */
    fun requestInvitation(server: String, email: String, name: String, relationship: String) =
        work {
            validateServer(server)
            val message = accounts.requestInvitation(server, email, name, relationship)
            session.update { it.copy(message = message, onboarding = "signin") }
        }
}
