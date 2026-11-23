package com.robiem.narahem.data.account

import android.content.Context
import com.robiem.narahem.data.ServerHttp
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/**
 * [AccountRepository] backed by the server's HTTPS API. Holds the access token in memory and the
 * refresh token in [RememberedSessionStore].
 */
class ServerAccountRepository(
    private val client: OkHttpClient =
        ServerHttp.client.newBuilder().connectTimeout(15, TimeUnit.SECONDS).build(),
    context: Context? = null
) : AccountRepository {
    private val remembered = context?.let(::RememberedSessionStore)
    private val refreshMutex = Mutex()
    private var server: HttpUrl? = null
    private var token: String? = null
    private var refreshGrant: String? = null

    /**
     * Sends a JSON request and returns the response body. Network failures become readable
     * IOExceptions and error responses become [AccountRequestException].
     */
    private suspend fun request(
        origin: HttpUrl,
        path: String,
        payload: JSONObject? = null,
        bearer: String? = null,
        method: String = "GET"
    ): JSONObject = withContext(Dispatchers.IO) {
        val builder = Request.Builder().url(
            origin.resolve(path)!!
        ).header("X-NaraHem-Client", "native")
        bearer?.let { builder.header("Authorization", "Bearer $it") }
        if (method == "PUT") {
            builder.put(
                (payload ?: JSONObject()).toString().toRequestBody("application/json".toMediaType())
            )
        } else {
            payload?.let {
                builder.post(it.toString().toRequestBody("application/json".toMediaType()))
            }
        }
        val response = try {
            client.newCall(builder.build()).execute()
        } catch (failure: UnknownHostException) {
            throw IOException(
                "Server address could not be found. Check the address and your network.",
                failure
            )
        } catch (failure: SocketTimeoutException) {
            throw IOException(
                "The server took too long to respond. Check the address, port and connection.",
                failure
            )
        } catch (failure: SSLException) {
            throw IOException(
                "Could not establish trusted HTTPS. Check the server certificate; local HTTP " +
                    "is not supported.",
                failure
            )
        } catch (failure: IOException) {
            throw IOException(
                "Could not connect to the server. Check the address, port, Wi-Fi or VPN.",
                failure
            )
        }
        response.use {
            val body = response.body?.string().orEmpty()
            val json = runCatching { JSONObject(body) }.getOrElse {
                if (response.isSuccessful) {
                    throw IOException(
                        "The server returned an unexpected page. Check the Nära Hem address."
                    )
                }
                JSONObject()
            }
            if (!response.isSuccessful) {
                val detail = json.optString("detail").takeIf { it.isNotBlank() }
                val fields = mutableMapOf<String, String>()
                val issues = json.optJSONArray("fields")
                if (issues != null) {
                    for (index in 0 until issues.length()) {
                        val issue = issues.optJSONObject(index) ?: continue
                        fields[issue.optString("field")] =
                            issue.optString("message", "Check this field.")
                    }
                }
                val message = when (response.code) {
                    401 -> if (path.startsWith("/api/native/session")) {
                        "Remembered sign-in expired. Sign in with your password again."
                    } else {
                        "Email or password is incorrect, or your invitation still " +
                            "needs to be completed."
                    }

                    404 ->
                        "This address does not provide the expected Nära Hem service. " +
                            "Check the server address."

                    in 300..399 ->
                        "The server redirected this request. Enter its final " + "HTTPS address."

                    else -> detail ?: "Server request failed (${response.code})."
                }
                throw AccountRequestException(response.code, message, fields)
            }
            json
        }
    }

    /** Validates the input, signs in, stores the refresh token and loads the account. */
    override suspend fun signIn(server: String, email: String, password: String): Account {
        val origin = serverOrigin(server)
        if (email.trim().isEmpty()) {
            throw AccountRequestException(
                0,
                "Enter your email address or phone number.",
                mapOf("email" to "Enter your email address or phone number.")
            )
        }
        if (password.isEmpty()) {
            throw AccountRequestException(
                0,
                "Enter your password, or use Find my invitation if you have not created one.",
                mapOf("password" to "Enter your password, or find your invitation.")
            )
        }
        val login =
            request(
                origin,
                "/api/login",
                JSONObject().put(
                    "email",
                    email.trim()
                ).put("password", password).put("native", true)
            )
        val access = login.optString("access_token")
        if (access.isBlank()) {
            throw IOException(
                "The server did not provide a native sign-in token. Update the server or " +
                    "check its address."
            )
        }
        try {
            val account = fetchAccount(origin, access)
            this.server = origin
            token = access
            refreshGrant = login.optString("refresh_token").takeIf { it.isNotBlank() }
            refreshGrant?.let { remembered?.write(RememberedSession(origin.toString(), it)) }
            return account
        } catch (failure: Exception) {
            runCatching { request(origin, "/api/logout", JSONObject(), access) }
            throw failure
        }
    }

    /** Loads the account and household name using the given access token. */
    private suspend fun fetchAccount(origin: HttpUrl, access: String): Account {
        val session = request(origin, "/api/session", bearer = access)
        val household = request(origin, "/api/household", bearer = access)
        return Account(
            session.optString("username").takeUnless { it.isBlank() || it == "null" }
                ?: if (session.optString("role") == "admin") "Admin" else "Member",
            session.getBoolean("verified"),
            household.getString("id"),
            session.optString("id"),
            session.optString("role", "member")
        )
    }

    /**
     * Exchanges the refresh token for a new access token and refresh token. The new refresh token
     * is saved before use because the old one is already spent.
     */
    private suspend fun rotate(origin: HttpUrl): String {
        val old = refreshGrant ?: error("Sign in required.")
        try {
            val result = request(
                origin,
                "/api/native/session/refresh",
                JSONObject().put("refresh_token", old)
            )
            val nextAccess = result.getString("access_token")
            val nextRefresh = result.getString("refresh_token")
            // Save the new refresh token before using it; the old one is already spent.
            remembered?.write(RememberedSession(origin.toString(), nextRefresh))
            refreshGrant = nextRefresh
            token = nextAccess
            return nextAccess
        } catch (expired: AccountRequestException) {
            if (expired.status == 401) {
                remembered?.clear()
                refreshGrant = null
                token = null
            }
            throw expired
        }
    }

    /** Restores the session from the stored refresh token if it belongs to this server. */
    override suspend fun restoreSession(server: String): Account? {
        val saved = remembered?.read() ?: return null
        val origin = serverOrigin(server)
        if (saved.server != origin.toString()) return null
        refreshMutex.withLock {
            this.server = origin
            refreshGrant = saved.refreshToken
            try {
                rotate(origin)
            } catch (expired: AccountRequestException) {
                if (expired.status == 401) {
                    this.server = null
                    return null
                }
                throw expired
            }
        }
        return fetchAccount(origin, token ?: error("Sign in required."))
    }

    /** Validates the form, then calls the legacy claim endpoint, which the server rejects. */
    override suspend fun claimInvitation(
        server: String,
        email: String,
        username: String,
        password: String
    ): String {
        if (!username.matches(Regex("[a-zA-Z0-9_.-]{3,64}"))) {
            throw AccountRequestException(
                0,
                "Choose a username with 3–64 letters, numbers, dots, dashes or underscores."
            )
        }
        if (password.length !in 15..128) {
            throw AccountRequestException(0, "Choose a password with 15–128 characters.")
        }
        return request(
            serverOrigin(server),
            "/api/enrollment/claim",
            JSONObject().put(
                "email",
                email.trim()
            ).put("username", username).put("password", password)
        ).getString("message")
    }

    /** Asks the server to email a new enrollment link. */
    override suspend fun requestEnrollment(server: String, email: String): String {
        if (email.trim().isEmpty()) {
            throw AccountRequestException(
                0,
                "Enter your invited email address or phone number.",
                mapOf("email" to "Enter your invited email address or phone number.")
            )
        }
        return request(
            serverOrigin(server),
            "/api/enrollment/request",
            JSONObject().put("email", email.trim())
        ).getString("message")
    }

    /**
     * Takes the six-digit code texted to [contact], or extracts the token from the pasted email
     * link, then sets the username and password.
     */
    override suspend fun completeEnrollment(
        server: String,
        token: String,
        username: String,
        password: String,
        contact: String
    ) {
        val entered = token.trim()
        val code = entered.takeIf { it.matches(Regex("[0-9]{6}")) }
        val extracted = if ("#verify=" in entered) {
            entered.substringAfter("#verify=").substringBefore("&")
        } else {
            entered
        }
        if (code == null && extracted.length !in 20..128) {
            val problem = "Enter the code from your text, or paste the link from your email."
            throw AccountRequestException(0, problem, mapOf("token" to problem))
        }
        if (username.isNotEmpty() && !username.matches(Regex("[a-zA-Z0-9_.-]{3,64}"))) {
            throw AccountRequestException(
                0,
                "Username: 3–64 letters, numbers, dots, dashes or underscores.",
                mapOf("username" to "Use 3–64 letters, numbers, dots, dashes or underscores.")
            )
        }
        if (password.isNotEmpty() && password.length !in 15..128) {
            throw AccountRequestException(
                0,
                "Choose a password with 15–128 characters.",
                mapOf("password" to "Choose a password with 15–128 characters.")
            )
        }
        val body = JSONObject().put(
            "username",
            username.ifEmpty { null } ?: JSONObject.NULL
        ).put(
            "password",
            password.ifEmpty { null } ?: JSONObject.NULL
        )
        if (code != null) {
            body.put("email", contact.trim()).put("code", code)
        } else {
            body.put("token", extracted)
        }
        request(serverOrigin(server), "/api/enrollment/verify", body)
    }

    /** Validates and submits an invitation request. */
    override suspend fun requestInvitation(
        server: String,
        email: String,
        name: String,
        relationship: String
    ): String {
        require(email.trim().isNotEmpty()) { "Enter your email address or phone number." }
        if (name.trim().isEmpty()) {
            throw AccountRequestException(
                0,
                "Enter your name.",
                mapOf("name" to "Enter your name.")
            )
        }
        if (relationship.trim().isEmpty()) {
            throw AccountRequestException(
                0,
                "Explain how you know this household.",
                mapOf("relationship" to "Explain how you know this household.")
            )
        }
        return request(
            serverOrigin(server),
            "/api/invitation-requests",
            JSONObject()
                .put(
                    "email",
                    email.trim()
                ).put("name", name.trim()).put("relationship", relationship.trim())
        ).getString("message")
    }

    /**
     * Sends a request with the access token, rotating the refresh token and retrying once on HTTP
     * 401.
     */
    override suspend fun authenticated(
        path: String,
        payload: JSONObject?,
        method: String
    ): JSONObject {
        val origin = server ?: error("Sign in first.")
        val bearer = token ?: error("Sign in first.")
        require(path.startsWith("/api/")) { "Only Nära Hem API requests are allowed." }
        return try {
            request(origin, path, payload, bearer, method)
        } catch (expired: AccountRequestException) {
            if (expired.status != 401 || refreshGrant == null) throw expired
            refreshMutex.withLock {
                val current = if (bearer != token) {
                    token ?: error("Sign in required.")
                } else {
                    rotate(origin)
                }
                request(origin, path, payload, current, method)
            }
        }
    }

    /** Revokes the session on the server when possible and always clears it locally. */
    override suspend fun signOut() {
        val origin = server
        val access = token
        val grant = refreshGrant ?: remembered?.read()?.refreshToken
        var failure: Exception? = null
        server = null
        token = null
        refreshGrant = null
        remembered?.clear()
        if (origin != null && grant != null) {
            try {
                request(
                    origin,
                    "/api/native/session/revoke",
                    JSONObject().put("refresh_token", grant)
                )
            } catch (e: Exception) {
                failure = e
            }
        }
        if (origin != null && access != null) {
            try {
                request(origin, "/api/logout", JSONObject(), access)
            } catch (e: Exception) {
                failure = e
            }
        }
        if (failure != null) throw failure
    }
}
