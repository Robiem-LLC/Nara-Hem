package com.robiem.narahem.data.account

import org.json.JSONObject

/**
 * Account operations against the household server: sign-in, session restore, authenticated requests
 * and email enrollment.
 */
interface AccountRepository {
    /** Signs in with email and password and stores the refresh token for later sessions. */
    suspend fun signIn(server: String, email: String, password: String): Account

    /** Revokes the session on the server if reachable and clears the stored session either way. */
    suspend fun signOut()

    /** Restores the stored session for this server. Returns null if there is none. */
    suspend fun restoreSession(server: String): Account? = null

    /**
     * Sends a request as the signed-in account, refreshing the access token once if it has expired.
     */
    suspend fun authenticated(
        path: String,
        payload: JSONObject? = null,
        method: String = "GET"
    ): JSONObject = error("Authenticated service unavailable.")

    /**
     * Legacy invitation endpoint. The server now rejects it and directs users to the email link.
     */
    suspend fun claimInvitation(
        server: String,
        email: String,
        username: String,
        password: String
    ): String = error("Invitation setup unavailable")

    /**
     * Asks the server to email a new enrollment link to an invited address. Returns the server's
     * message.
     */
    suspend fun requestEnrollment(server: String, email: String): String =
        error("Invitation lookup is unavailable.")

    /**
     * Completes enrollment from an emailed link by setting the username and password, then signs
     * in.
     */
    suspend fun completeEnrollment(
        server: String,
        token: String,
        username: String,
        password: String
    ) {
        error("Enrollment is unavailable.")
    }

    /**
     * Registers the account invited at this email address or phone number with a username and
     * password. It stays unconfirmed until the code sent when approving this phone.
     */
    suspend fun register(server: String, contact: String, username: String, password: String) {
        error("Registration is unavailable.")
    }

    /** Submits a request for the admin to invite this person. */
    suspend fun requestInvitation(
        server: String,
        email: String,
        name: String,
        relationship: String
    ): String = error("Invitation requests are unavailable.")

    /**
     * Sends a six-digit code to a new email address or phone number for this account. Nothing
     * changes until [confirmContactChange]. Returns where the code went.
     */
    suspend fun requestContactChange(value: String, password: String, phone: Boolean): String =
        authenticated(
            "/api/account/contact",
            JSONObject().put("value", value).put("password", password)
                .put("kind", if (phone) "phone" else "email"),
            "POST"
        ).getString("to")

    /** Uses the new email address or phone number once its [code] is entered. */
    suspend fun confirmContactChange(code: String) {
        authenticated("/api/account/contact/verify", JSONObject().put("code", code), "POST")
    }

    /** Returns the account's email address and phone number, and whether the server can text. */
    suspend fun contactDetails(): ContactDetails {
        val session = authenticated("/api/session")
        val setup = authenticated("/api/setup")
        return ContactDetails(
            session.optString("email").takeUnless { session.isNull("email") || it.isBlank() },
            session.optString("phone").takeUnless { session.isNull("phone") || it.isBlank() },
            setup.optBoolean("texting")
        )
    }
}
