package com.robiem.narahem.data.household

import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.account.AccountRepository
import java.util.concurrent.CopyOnWriteArrayList
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONArray
import org.json.JSONObject

/**
 * An in-memory household server and owner device for testing [NativeHouseholdRepository]. It
 * answers the device API over a MockWebServer, the account API through [accounts], and signs roster
 * changes the way the owner's trusted device would.
 */
internal class FakeHouseholdServer : Dispatcher() {
    val household = "test-household"
    val ownerAccount = "a".repeat(32)
    val phoneAccount = "b".repeat(32)
    val ownerId = HouseholdCrypto.randomId()
    val ownerSigning = HouseholdCrypto.signingKeys()
    val ownerBox = HouseholdCrypto.boxKeys()
    val serverBox = HouseholdCrypto.boxKeys()
    val credential = "device-credential"

    /** Signed roster changes, oldest first: each has body, signature and hash. */
    val changes = mutableListOf<JSONObject>()
    var anchor = ""
    var registration: JSONObject? = null
    var deviceStatus = "pending"
    var sharing = true
    var sequence = 0L
    var replacementRequired = false
    var audience = listOf(ownerAccount)
    var eligible = JSONArray()
    var ownerViewer: String? = null
    var members: JSONArray? = null
    var findCommand: JSONObject? = null
    var trips = JSONArray()
    val tripDetails = mutableMapOf<String, JSONObject>()
    var alerts = JSONArray()
    var profileRecord: String? = null

    /** Records the server accepted, as sent. */
    val records = CopyOnWriteArrayList<JSONObject>()

    /** Decrypted record state the server shows in /api/view, keyed by kind and entity ID. */
    val view = linkedMapOf<String, JSONObject>()

    /** Every request as "METHOD /path?query", in order. */
    val log = CopyOnWriteArrayList<String>()

    /** Request bodies and headers, keyed like [log], last one wins. */
    val bodies = mutableMapOf<String, JSONObject>()
    val headers = mutableMapOf<String, String?>()

    /** One-off failures keyed by "METHOD /path": the status and detail of the next reply. */
    val failures = mutableMapOf<String, MutableList<Pair<Int, String>>>()

    /** The account API, answered in process. Throws like the real repository on errors. */
    val accounts = object : AccountRepository {
        override suspend fun signIn(server: String, email: String, password: String) =
            Account("Sam", true, household, phoneAccount)

        override suspend fun signOut() {}

        override suspend fun authenticated(
            path: String,
            payload: JSONObject?,
            method: String
        ): JSONObject = synchronized(this@FakeHouseholdServer) {
            // Like the real client, a body with the default method is sent as a POST.
            val route = (if (payload != null && method == "GET") "POST" else method) + " " + path
            log.add(route)
            payload?.let { bodies[route] = it }
            failures[route]?.removeFirstOrNull()?.let { throw IllegalStateException(it.second) }
            when (route) {
                "POST /api/devices/register" -> {
                    val p = payload!!
                    registration = JSONObject().put("domain", "narahem.device.v1")
                        .put("household", household).put("id", p.getString("id"))
                        .put("account_id", phoneAccount)
                        .put("signing_key", p.getString("signing_key"))
                        .put("box_key", p.getString("box_key")).put("platform", "android")
                    check(
                        HouseholdCrypto.verify(
                            registration!!,
                            p.getString("signature"),
                            p.getString("signing_key")
                        )
                    )
                    JSONObject().put("credential", credential)
                }

                "GET /api/household" -> JSONObject().put("revision", changes.size)

                "GET /api/household/members" ->
                    JSONObject().put(
                        "members",
                        members ?: throw IllegalStateException("Admins only")
                    )

                "POST /api/phones/verify" -> {
                    require(payload!!.getString("code") == "654321") { "Wrong code" }
                    approvePhone()
                    JSONObject()
                }

                else -> JSONObject()
            }
        }
    }

    private val web = MockWebServer()

    /** HTTPS address of the running server, from [start]. */
    lateinit var address: String

    /** An HTTP client that trusts the server's test certificate, from [start]. */
    lateinit var client: OkHttpClient

    /** Returns the hash the owner signs to approve this exact phone registration. */
    fun pairingHash(): String = HouseholdCrypto.hashString(HouseholdCrypto.canonical(registration))

    /** Stops the server. */
    fun stop() = web.shutdown()

    /** Starts serving over HTTPS on localhost with a throwaway certificate. */
    fun start() {
        val certificate = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val serverTls = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientTls =
            HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        web.useHttps(serverTls.sslSocketFactory(), false)
        web.dispatcher = this
        web.start()
        address = web.url("/").toString()
        client = OkHttpClient.Builder()
            .sslSocketFactory(clientTls.sslSocketFactory(), clientTls.trustManager).build()
    }

    /** The phone's signed-in account. */
    fun phoneMember(role: String = "member", verified: Boolean = true) =
        Account("Sam", verified, household, phoneAccount, role)

    /** Starts the household with the owner and lets [repo]'s phone join it by emailed code. */
    suspend fun join(repo: NativeHouseholdRepository) {
        startWithOwner()
        repo.enroll(phoneMember(), address)
        repo.verifyPhoneCode("654321")
    }

    /** Makes the next request to [route] fail with [status] and [detail]. */
    fun failNext(route: String, status: Int, detail: String = "Failed") {
        failures.getOrPut(route) { mutableListOf() }.add(status to detail)
    }

    /** Returns the owner's roster entry. */
    fun ownerIdentity(): JSONObject = JSONObject()
        .put("id", ownerId).put("account_id", ownerAccount)
        .put("signing_key", ownerSigning.publicKey).put("box_key", ownerBox.publicKey)

    /** Returns the phone's roster entry, from its registration. */
    fun phoneIdentity(): JSONObject {
        val r = registration ?: error("Phone not registered")
        return JSONObject()
            .put("id", r.getString("id")).put("account_id", r.getString("account_id"))
            .put("signing_key", r.getString("signing_key")).put("box_key", r.getString("box_key"))
    }

    /** Returns the devices in the latest roster. */
    fun currentDevices(): List<JSONObject> {
        val last = changes.lastOrNull() ?: return emptyList()
        val devices = last.getJSONObject("body").getJSONArray("devices")
        return (0 until devices.length()).map { devices.getJSONObject(it) }
    }

    /**
     * Builds a signed roster change after the current one. [edit] can change the body after
     * signing-relevant fields are set; [signWith] defaults to the owner's key.
     */
    fun signedChange(
        devices: List<JSONObject>,
        signer: String = ownerId,
        signWith: String = ownerSigning.privateKey,
        extra: JSONObject.() -> Unit = {}
    ): JSONObject {
        val body = JSONObject().put("domain", "narahem.roster.v1").put("household", household)
            .put("revision", changes.size + 1)
            .put("previous", changes.lastOrNull()?.getString("hash") ?: "")
            .put("signer", signer)
            .put("devices", JSONArray(devices.sortedBy { it.getString("id") }))
            .put("issued_at", System.currentTimeMillis() / 1000)
        body.extra()
        val signature = HouseholdCrypto.sign(body, signWith)
        val hash = HouseholdCrypto.hashString(
            HouseholdCrypto.canonical(JSONObject().put("body", body).put("signature", signature))
        )
        return JSONObject().put("body", body).put("signature", signature).put("hash", hash)
    }

    /** Starts the household with the owner device as its only member and root. */
    fun startWithOwner() {
        changes.add(signedChange(listOf(ownerIdentity())))
        anchor = ownerSigning.publicKey
    }

    /** The owner signs a roster that adds the registered phone, as approving it would. */
    fun approvePhone() {
        changes.add(
            signedChange(
                currentDevices().filter {
                    it.getString("id") != phoneIdentity().getString("id")
                } + phoneIdentity()
            ) {
                put("pairing_target", registration!!.getString("id"))
                put("pairing_hash", pairingHash())
            }
        )
        deviceStatus = "approved"
    }

    /** The owner signs a roster that adds another member's device. Returns its box keys. */
    fun addMember(accountId: String): HouseholdCrypto.KeyPair {
        val box = HouseholdCrypto.boxKeys()
        val device = JSONObject().put("id", HouseholdCrypto.randomId()).put("account_id", accountId)
            .put(
                "signing_key",
                HouseholdCrypto.signingKeys().publicKey
            ).put("box_key", box.publicKey)
        changes.add(signedChange(currentDevices() + device))
        return box
    }

    /** Builds a Find My Phone command for the phone, signed by the owner device. */
    fun ringCommand(
        action: String = "ring",
        signWith: String = ownerSigning.privateKey
    ): JSONObject {
        val now = System.currentTimeMillis() / 1000
        val body = JSONObject().put("domain", "narahem.find-phone.v1").put("household", household)
            .put("target", registration!!.getString("id")).put("issuer", ownerId)
            .put("id", HouseholdCrypto.randomId()).put("action", action)
            .put("issued_at", now).put("expires_at", now + 60)
        return JSONObject().put("body", body).put("signature", HouseholdCrypto.sign(body, signWith))
    }

    /** Decrypts a record's server copy with the server key. */
    fun serverCopy(record: JSONObject): JSONObject = HouseholdCrypto.open(
        record.getJSONObject("body").getString("server_box"),
        serverBox.publicKey,
        serverBox.privateKey
    )

    /** Answers device API requests. */
    override fun dispatch(request: RecordedRequest): MockResponse = synchronized(this) {
        val url = request.requestUrl!!
        val path = url.encodedPath
        val route = "${request.method} $path"
        log.add("${request.method} ${url.encodedPath}${url.encodedQuery?.let { "?$it" } ?: ""}")
        val text = request.body.readUtf8()
        val payload = if (text.isBlank()) JSONObject() else JSONObject(text)
        bodies[route] = payload
        headers[route] = request.getHeader("X-Places-State")
        if (request.getHeader("Authorization") != "Bearer $credential") return reply(401, "Sign in")
        failures[route]?.removeFirstOrNull()?.let { return reply(it.first, it.second) }
        if (deviceStatus == "revoked" && path != "/api/device") return reply(403, "Revoked")
        val result: JSONObject = when (route) {
            "GET /api/device" -> JSONObject().put("status", deviceStatus).put("sequence", sequence)
                .put("sharing", sharing).put("trip_processing_key", serverBox.publicKey)
                .put("replacement_required", replacementRequired)

            "GET /api/roster" -> {
                val after = url.queryParameter("after")?.toInt() ?: 0
                JSONObject().put("anchor", anchor).put("household", household)
                    .put("revision", changes.size)
                    .put("changes", JSONArray(changes.drop(after).take(2)))
            }

            "POST /api/roster" -> {
                if (payload.getString("bootstrap_email_code") != "123456") {
                    return reply(400, "Wrong code")
                }
                val body = payload.getJSONObject("body")
                val signature = payload.getString("signature")
                val hash = HouseholdCrypto.hashString(
                    HouseholdCrypto.canonical(
                        JSONObject().put("body", body).put("signature", signature)
                    )
                )
                changes.add(
                    JSONObject().put("body", body).put("signature", signature).put("hash", hash)
                )
                anchor = body.getJSONArray("devices").getJSONObject(0).getString("signing_key")
                deviceStatus = "approved"
                JSONObject()
            }

            "GET /api/sharing/audience" -> JSONObject().put("account_ids", JSONArray(audience))
                .put("eligible_members", eligible)
                .put(
                    "owner_viewer",
                    ownerViewer?.let { JSONObject().put("id", it) } ?: JSONObject.NULL
                )

            "PUT /api/sharing/audience" -> JSONObject().also {
                val ids = payload.getJSONArray("account_ids")
                audience = (0 until ids.length()).map { ids.getString(it) }
            }

            "PUT /api/sharing" -> JSONObject().also { sharing = payload.getBoolean("enabled") }

            "POST /api/phones/self-revoke" -> JSONObject().also { deviceStatus = "revoked" }

            "PUT /api/push/subscription" -> JSONObject().put("registered", true)

            "GET /api/find-phone/command" -> JSONObject().put(
                "command",
                findCommand ?: JSONObject.NULL
            )

            "GET /api/view" -> JSONObject().put("revision", changes.size)
                .put("records", JSONArray(view.values.toList()))

            "GET /api/places/manifest" -> JSONObject().put("token", "places-token").put(
                "places",
                JSONArray(
                    view.values.filter { it.getString("kind") == "place" }.map {
                        JSONObject().put(
                            "id",
                            it.getString("entity_id")
                        ).put("record_id", it.getString("id"))
                    }
                )
            )

            "GET /api/profile/current" -> JSONObject().put(
                "replaces",
                profileRecord ?: JSONObject.NULL
            )

            "POST /api/records" -> accept(payload)

            "GET /api/trips" -> JSONObject().put("trips", trips)

            "GET /api/alerts" -> JSONObject().put("alerts", alerts)

            else -> if (path.startsWith("/api/trips/")) {
                tripDetails[path.removePrefix("/api/trips/")] ?: return reply(404, "No trip")
            } else {
                JSONObject()
            }
        }
        return MockResponse().setBody(result.toString())
    }

    /** Checks a record's signature and applies it to [view], as the real server would. */
    private fun accept(envelope: JSONObject): JSONObject {
        val body = envelope.getJSONObject("body")
        val sender = currentDevices().first { it.getString("id") == body.getString("sender") }
        require(
            HouseholdCrypto.verify(
                body,
                envelope.getString("signature"),
                sender.getString("signing_key")
            )
        )
        records.add(envelope)
        sequence = maxOf(sequence, body.getLong("sequence"))
        val key = body.getString("kind") + ":" + body.getString("entity_id")
        if (body.getString("operation") == "delete") {
            view.remove(key)
        } else {
            val data = serverCopy(envelope).getJSONObject("data")
            view.remove(key)
            view[key] =
                JSONObject().put("id", body.getString("id")).put("kind", body.getString("kind"))
                    .put("operation", "upsert").put("entity_id", body.getString("entity_id"))
                    .put("captured_at", body.getLong("captured_at")).put("data", data)
        }
        return JSONObject()
    }

    /** Builds an error reply with a detail message. */
    private fun reply(status: Int, detail: String) = MockResponse().setResponseCode(
        status
    ).setBody(JSONObject().put("detail", detail).toString())
}
