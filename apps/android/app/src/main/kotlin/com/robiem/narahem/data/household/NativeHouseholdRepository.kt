package com.robiem.narahem.data.household

import android.content.Context
import com.robiem.narahem.data.ServerHttp
import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.account.AccountRepository
import com.robiem.narahem.data.account.serverOrigin
import com.robiem.narahem.data.location.LocalFix
import com.robiem.narahem.data.trips.TripHistory
import com.robiem.narahem.data.trips.TripPoint
import com.robiem.narahem.findphone.FindPhoneCommand
import com.robiem.narahem.findphone.FindPhoneCommandValidator
import com.robiem.narahem.findphone.FindPhoneReplay
import com.robiem.narahem.findphone.FindPhoneSigner
import com.robiem.narahem.tracking.CompletedTrip
import com.robiem.narahem.tracking.ExpiredTrackingSample
import com.robiem.narahem.tracking.OfflineOutbox
import com.robiem.narahem.tracking.OfflineTrackingCodec
import com.robiem.narahem.tracking.QueuedTrackingDelivery
import com.robiem.narahem.tracking.ReprepareTrackingSample
import com.robiem.narahem.tracking.TrackingDisabled
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

/** Thrown when this device is registered but not yet in the signed roster. */
private class PendingPairingException :
    IllegalStateException("Waiting for a signed trusted-device approval.")

/** Thrown when a device API request fails, carrying the HTTP status. */
private class DeviceApiFailure(val status: Int, detail: String) : IOException(detail)

/**
 * [HouseholdRepository] for this phone. Manages the device keys and signed roster, encrypts and
 * uploads records, runs the offline queue and handles Find My Phone commands. [client] is replaced
 * only by tests.
 */
class NativeHouseholdRepository(
    context: Context,
    private val accounts: AccountRepository,
    private val client: OkHttpClient = ServerHttp.client
) : HouseholdRepository {
    private val store = SecureDeviceStore(context.applicationContext)
    private val appContext = context.applicationContext
    private val trackingPrefs = appContext.getSharedPreferences("server", Context.MODE_PRIVATE)
    private val finderClient = client.newBuilder().callTimeout(5, TimeUnit.SECONDS).build()
    private val publication = publicationLock
    private var vault: DeviceVault? = null
    private var currentRoster: JSONObject? = null
    private var rosters: MutableMap<Int, JSONObject> = mutableMapOf()
    private var baseUrl = ""
    private var sharingAllowed = true
    private var reportedFindCapability: Boolean? = null
    private var contextAt = 0L
    private var contextDevice: JSONObject? = null
    private var contextAudience: JSONObject? = null

    /** Returns the preference key for this device's Find My Phone state. */
    private fun findKey(suffix: String) = "find-phone-${vault?.id ?: "none"}-$suffix"

    /** Reads the Find My Phone setting for this device. */
    override fun findPhoneEnabled(): Boolean = trackingPrefs.getBoolean(findKey("enabled"), false)

    /** Returns the account this device belongs to. */
    fun accountId(): String? = vault?.accountId

    /** Returns the sharing state last reported by the server. */
    override fun sharingEnabled(): Boolean = sharingAllowed

    /** Returns the number of locations and trips waiting to upload. */
    fun pendingTrackingCount(): Int = pendingQueue().size()

    /** Returns the offline queue for the current device. Throws if the stored device changed. */
    private fun pendingQueue(): OfflineOutbox {
        val v = vault ?: error("No device registered")
        require(store.read()?.id == v.id) { "Device session changed" }
        val namespace = HouseholdCrypto.hashString("$baseUrl/${v.household}/${v.accountId}/${v.id}")
        return OfflineOutbox(appContext, namespace)
    }

    /** Sends a request authenticated as this device and converts failures into readable errors. */
    private suspend fun deviceRequest(
        path: String,
        payload: JSONObject? = null,
        method: String = "GET",
        extraHeaders: Map<String, String> = emptyMap()
    ): JSONObject = withContext(Dispatchers.IO) {
        val secret = vault ?: error("Device not registered")
        val origin = serverOrigin(baseUrl)
        val request = Request.Builder().url(origin.resolve(path) ?: error("Invalid API path"))
            .header("Authorization", "Bearer " + secret.credential)
            .header("X-NaraHem-Client", "native")
        extraHeaders.forEach { (name, value) -> request.header(name, value) }
        if (payload != null || method != "GET") {
            val body = (payload ?: JSONObject()).toString().toRequestBody(
                "application/json".toMediaType()
            )
            when (method) {
                "POST" -> request.post(body)
                "PUT" -> request.put(body)
                "DELETE" -> request.delete(body)
                else -> error("Invalid device method")
            }
        }
        (
            if (path.startsWith("/api/find-phone/")) finderClient else client
            ).newCall(request.build()).execute().use { response ->
            val text = response.body?.string().orEmpty()
            val json = runCatching { JSONObject(text) }.getOrDefault(JSONObject())
            if (!response.isSuccessful) {
                throw DeviceApiFailure(
                    response.code,
                    json.optString("detail").ifBlank { "Device API error: " + response.code }
                )
            }
            json
        }
    }

    /**
     * Reports permission flags (foreground and background location, notifications, Find My Phone,
     * Do Not Disturb access, sharing) when they change or every six hours. Never includes location
     * data.
     */
    override suspend fun reportDevicePermissions() {
        val notifications = appContext.getSystemService(android.app.NotificationManager::class.java)
        val fine =
            appContext.checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) ==
                android.content.pm.PackageManager.PERMISSION_GRANTED
        val coarse =
            appContext.checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION) ==
                android.content.pm.PackageManager.PERMISSION_GRANTED
        val foreground = fine || coarse
        val background = android.os.Build.VERSION.SDK_INT < 29 || appContext.checkSelfPermission(
            android.Manifest.permission.ACCESS_BACKGROUND_LOCATION
        ) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED
        val payload = JSONObject()
            .put("foreground_location", foreground)
            .put("background_location", foreground && background)
            .put("remote_alarm", findPhoneEnabled())
            .put("dnd_access", notifications.isNotificationPolicyAccessGranted)
            .put("notifications", notifications.areNotificationsEnabled())
            .put("sharing", trackingPrefs.getBoolean("resume-sharing", false))
        val sent = trackingPrefs.getString("permissions-sent", null)
        if (sent == payload.toString() &&
            System.currentTimeMillis() - trackingPrefs.getLong("permissions-sent-at", 0L) in
            0..21_600_000L
        ) {
            return
        }
        deviceRequest("/api/device/permissions", payload, "PUT")
        trackingPrefs.edit().putString("permissions-sent", payload.toString())
            .putLong("permissions-sent-at", System.currentTimeMillis()).apply()
    }

    /** Saves the Find My Phone setting and reports it to the server. */
    override suspend fun setFindPhoneEnabled(enabled: Boolean) {
        if (!enabled) {
            trackingPrefs.edit().putBoolean(findKey("enabled"), false).commit()
            reportedFindCapability = null
            runCatching {
                deviceRequest(
                    "/api/find-phone/capability",
                    JSONObject().put("enabled", false).put("platform", "android"),
                    "PUT"
                )
            }.onSuccess {
                reportedFindCapability = false
            }
            return
        }
        deviceRequest(
            "/api/find-phone/capability",
            JSONObject().put("enabled", enabled).put("platform", "android"),
            "PUT"
        )
        trackingPrefs.edit().putBoolean(findKey("enabled"), enabled).commit()
        reportedFindCapability = enabled
    }

    /** Stores a ring status report so it survives a restart until sent. */
    fun queueFindReport(id: String, status: String, reason: String = "") {
        trackingPrefs.edit().putString(
            findKey("report"),
            JSONObject().put(
                "command_id",
                id
            ).put("status", status).put("reason", reason).toString()
        ).commit()
    }

    /** Sends the stored ring report, if any. */
    suspend fun flushFindReport() {
        val text = trackingPrefs.getString(findKey("report"), null) ?: return
        try {
            deviceRequest("/api/find-phone/report", JSONObject(text), "POST")
        } catch (failure: DeviceApiFailure) {
            if (failure.status != 404 && failure.status != 410) throw failure
        }
        if (trackingPrefs.getString(findKey("report"), null) == text) {
            trackingPrefs.edit().remove(findKey("report")).commit()
        }
    }

    /**
     * Fetches the next ring or stop command, verifies the admin's signature, and marks it used
     * before returning it so it can't run twice.
     */
    suspend fun nextFindPhoneCommand(): FindPhoneCommand? {
        val enabled = findPhoneEnabled()
        if (reportedFindCapability != enabled) {
            deviceRequest(
                "/api/find-phone/capability",
                JSONObject().put("enabled", enabled).put("platform", "android"),
                "PUT"
            )
            reportedFindCapability = enabled
        }
        flushFindReport()
        if (!enabled) return null
        val envelope =
            deviceRequest("/api/find-phone/command").optJSONObject("command") ?: return null
        val body = envelope.getJSONObject("body")
        if (trackingPrefs.getString(findKey("last-id"), null) == body.optString("id")) return null
        syncRoster()
        val v = vault ?: error("Device unavailable")
        val initial = rosters[1]?.getJSONArray("devices") ?: error("Owner trust unavailable")
        val owner =
            (0 until initial.length()).map { initial.getJSONObject(it) }.firstOrNull {
                it.getString("signing_key") ==
                    v.anchor
            }?.getString("account_id")
                ?: error("Owner trust unavailable")
        val devices = currentRoster!!.getJSONArray("devices")
        val signers = (0 until devices.length()).map {
            devices.getJSONObject(it)
        }.map {
            FindPhoneSigner(
                it.getString("id"),
                it.getString("account_id"),
                it.getString("signing_key")
            )
        }
        val command = FindPhoneCommandValidator.validate(
            body,
            envelope.getString("signature"),
            v.household,
            v.id,
            owner,
            signers,
            System.currentTimeMillis() / 1000,
            HouseholdCrypto::verify
        )
        // Mark the command used before ringing, so a repeated poll or a restart can't ring it
        // again.
        val seen =
            FindPhoneReplay.consume(
                JSONObject(trackingPrefs.getString(findKey("seen"), "{}")!!),
                command,
                System.currentTimeMillis() / 1000
            )
                ?: return null
        require(
            trackingPrefs.edit().putString(
                findKey("last-id"),
                command.id
            ).putString(findKey("seen"), seen.toString()).commit()
        ) {
            "Cannot persist alarm replay protection"
        }
        queueFindReport(command.id, "received")
        return command
    }

    /** Writes the device vault to secure storage. */
    private fun save() {
        val value = vault ?: return
        store.write(value, baseUrl)
    }

    /**
     * Loads the stored device for the background service, which runs without an account session.
     */
    fun restoreForService(): Boolean {
        val restored = store.read() ?: return false
        val server = store.server() ?: return false
        vault = restored
        baseUrl = server
        return restored.anchor.isNotBlank()
    }

    /** Builds this device's registration body. */
    private fun ownRegistration(v: DeviceVault): JSONObject = JSONObject()
        .put("domain", "narahem.device.v1").put("household", v.household)
        .put("id", v.id).put("account_id", v.accountId)
        .put("signing_key", v.signingPublic).put("box_key", v.boxPublic)
        .also { if (v.registrationPlatform != null) it.put("platform", v.registrationPlatform) }

    /** Derives a six-digit code from a registration and the household root key. */
    private fun pairingCode(registration: JSONObject, anchor: String): String {
        require(HouseholdCrypto.unb64(anchor).size == 32) { "Household root key unavailable" }
        val registrationHash = HouseholdCrypto.hashString(HouseholdCrypto.canonical(registration))
        val digest = HouseholdCrypto.hashString("narahem.pairing-code.v1:$anchor:$registrationHash")
        return ((digest.take(12).toLong(16) % 1_000_000L).toInt()).toString().padStart(6, '0')
    }

    /**
     * Returns this device's pairing code. The approving device computes the same code
     * independently.
     */
    override suspend fun ownPairingCode(): String {
        val v = vault ?: return ""
        val root = if (v.anchor.isNotBlank()) {
            v.anchor
        } else {
            deviceRequest("/api/roster").optString("anchor")
        }
        if (root.isBlank()) return ""
        return pairingCode(ownRegistration(v), root)
    }

    /** Returns the hash of this device's registration. */
    override fun deviceFingerprint(): String {
        val v = vault ?: return ""
        return HouseholdCrypto.hashString(HouseholdCrypto.canonical(ownRegistration(v)))
    }

    /** Returns the hash of the household root key, or an empty string if it isn't known yet. */
    override fun ownerFingerprint(): String {
        val anchor = vault?.anchor.orEmpty()
        return if (anchor.isBlank()) "" else HouseholdCrypto.sha(HouseholdCrypto.unb64(anchor))
    }

    /** Generates keys and registers this device, once. A pending device can't publish anything. */
    override suspend fun enroll(account: Account, server: String) {
        baseUrl = serverOrigin(server).toString().removeSuffix("/")
        val old = store.read()
        if (old != null && old.accountId == account.id && old.household == account.household &&
            store.server() == baseUrl
        ) {
            vault = old
            return
        }
        if (!account.verified) return
        require(account.id.matches(Regex("[a-f0-9]{32}"))) {
            "Server did not return a valid account identity."
        }
        val signing = HouseholdCrypto.signingKeys()
        val box = HouseholdCrypto.boxKeys()
        val fresh = DeviceVault(
            HouseholdCrypto.randomId(), account.id, account.household,
            signing.publicKey, signing.privateKey, box.publicKey, box.privateKey, "",
            registrationPlatform = "android"
        )
        val registration = ownRegistration(fresh)
        val response = accounts.authenticated(
            "/api/devices/register",
            JSONObject()
                .put("id", fresh.id).put("name", "Android phone")
                .put("signing_key", fresh.signingPublic).put("box_key", fresh.boxPublic)
                .put("platform", "android")
                .put("signature", HouseholdCrypto.sign(registration, fresh.signingPrivate))
        )
        fresh.credential = response.getString("credential")
        vault = fresh
        save()
    }

    /**
     * Uploads an FCM token once this device is approved. Only a digest of the token is kept
     * locally, to skip repeat uploads.
     */
    suspend fun registerFcmSubscription(token: String) {
        val device = vault ?: return
        if (device.anchor.isBlank() || token.length !in 20..4096 ||
            token.any { it.isWhitespace() || it.code > 127 }
        ) {
            return
        }
        val marker = "fcm:${device.id}:${HouseholdCrypto.hashString(token)}"
        val previous = trackingPrefs.getString("fcm-upload-marker", null)
        val lastUpload = trackingPrefs.getLong("fcm-upload-at", 0L)
        if (marker == previous && System.currentTimeMillis() - lastUpload in 0..43_200_000L) return
        val result = deviceRequest(
            "/api/push/subscription",
            JSONObject().put("provider", "fcm").put("token", token),
            "PUT"
        )
        if (result.optBoolean("registered")) {
            trackingPrefs.edit().putString("fcm-upload-marker", marker)
                .putLong("fcm-upload-at", System.currentTimeMillis()).apply()
        }
    }

    /** Uploads the current FCM token for an approved device. */
    override suspend fun ensureFcmSubscription() {
        val device = vault ?: return
        if (device.anchor.isBlank()) return
        trackingPrefs.edit().putBoolean("fcm-signed-in", true).apply()
        @Suppress("DEPRECATION")
        val token = com.google.firebase.messaging.FirebaseMessaging.getInstance().token.await()
        registerFcmSubscription(token)
    }

    /** Removes the push token from the server and clears the local upload marker. */
    override suspend fun unsubscribeFcm() {
        trackingPrefs.edit().putBoolean("fcm-signed-in", false).apply()
        try {
            if (vault?.anchor?.isNotBlank() == true) {
                deviceRequest("/api/push/subscription", method = "DELETE")
            }
        } finally {
            trackingPrefs.edit().remove("fcm-upload-marker").remove("fcm-upload-at").apply()
        }
    }

    /** Deletes every device's offline queue. */
    override fun clearPendingTracking() {
        OfflineOutbox.clearAll(appContext)
    }

    /** Stops sharing and deletes this phone's household identity and queued data. */
    fun forgetLocalDevice() {
        trackingPrefs.edit().putBoolean("resume-sharing", false).apply()
        clearPendingTracking()
        vault = null
        currentRoster = null
        rosters.clear()
        store.clear()
    }

    /** Determines this device's setup state from the server and the signed roster. */
    override suspend fun status(account: Account): String {
        val v = vault ?: return if (account.verified) "register" else "verify-email"
        val device = try {
            deviceRequest("/api/device")
        } catch (failure: DeviceApiFailure) {
            if (failure.status != 401) throw failure
            forgetLocalDevice()
            return "register"
        }
        if (device.getString("status") == "revoked") return "revoked"
        v.sequence = maxOf(v.sequence, device.optLong("sequence"))
        sharingAllowed =
            device.optBoolean("sharing", true) &&
            !trackingPrefs.getBoolean("tracking-paused", false)
        save()
        if (device.getString("status") != "approved") {
            val household = accounts.authenticated("/api/household")
            return when {
                device.optBoolean("replacement_required") -> "replacement-required"
                household.optInt("revision") == 0 && account.role == "admin" -> "first-device"
                v.registrationPlatform == "android" -> "email-code"
                else -> "pending"
            }
        }
        if (v.anchor.isBlank()) {
            return try {
                syncRoster()
                "ready"
            } catch (waiting: PendingPairingException) {
                "pairing"
            }
        }
        syncRoster()
        return "ready"
    }

    /** Asks the server to email this phone's approval code. */
    override suspend fun sendPhoneCode() {
        val v = vault ?: error("Register this phone first")
        accounts.authenticated("/api/phones/code", JSONObject().put("device_id", v.id))
    }

    /** Submits the approval code and syncs the roster. */
    override suspend fun verifyPhoneCode(code: String) {
        require(code.matches(Regex("[0-9]{6}"))) { "Enter the six-digit emailed code." }
        val v = vault ?: error("Register this phone first")
        accounts.authenticated(
            "/api/phones/verify",
            JSONObject().put("device_id", v.id).put("code", code)
        )
        syncRoster()
    }

    /** Cancels the pending registration and deletes local keys. */
    override suspend fun discardPendingPhone() {
        val v = vault ?: return
        runCatching {
            accounts.authenticated(
                "/api/phones/pending",
                JSONObject().put("device_id", v.id),
                "DELETE"
            )
        }
        forgetLocalDevice()
    }

    /** Revokes this phone on the server and deletes local keys. */
    override suspend fun revokeOwnPhone() {
        deviceRequest("/api/phones/self-revoke", JSONObject(), "POST")
        forgetLocalDevice()
    }

    /** Requests the first-device email code. */
    override suspend fun sendFirstDeviceCode() {
        val v = vault ?: error("Device not registered")
        accounts.authenticated(
            "/api/device-bootstrap/email/request",
            JSONObject().put("device_id", v.id)
        )
    }

    /**
     * Signs the first roster with this device as the household root, verified by the emailed code.
     */
    override suspend fun bootstrapWithEmail(code: String) {
        require(code.matches(Regex("[0-9]{6}"))) { "Enter the six-digit email code." }
        val v = vault ?: error("Device not registered")
        val body = JSONObject().put("domain", "narahem.roster.v1")
            .put("household", v.household).put("revision", 1).put("previous", "")
            .put("signer", v.id).put("devices", JSONArray().put(v.identity()))
            .put("issued_at", System.currentTimeMillis() / 1000)
        deviceRequest(
            "/api/roster",
            JSONObject()
                .put("body", body).put("signature", HouseholdCrypto.sign(body, v.signingPrivate))
                .put("bootstrap_email_code", code),
            "POST"
        )
        v.anchor = v.signingPublic
        save()
        syncRoster()
    }

    /**
     * Pins the household root key after the user confirms its fingerprint through a trusted
     * channel.
     */
    override suspend fun verifyOwnerFingerprint(fingerprint: String) {
        val v = vault ?: error("Device not registered")
        val chain = deviceRequest("/api/roster")
        val anchor = chain.optString("anchor")
        require(
            anchor.isNotBlank() &&
                HouseholdCrypto.sha(HouseholdCrypto.unb64(anchor)) == fingerprint.trim().lowercase()
        ) {
            "Household fingerprint does not match the trusted owner device."
        }
        v.anchor = anchor
        save()
        syncRoster()
    }

    /**
     * Fetches and verifies every new signed roster revision, rejecting forks, rollbacks and key
     * substitutions. Returns the current roster.
     */
    suspend fun syncRoster(): JSONObject {
        val v = vault ?: error("Device not registered")
        val onboarding = v.anchor.isBlank()
        var candidateAnchor = v.anchor
        var proofVerified = false
        var after = 0
        var prevHash = ""
        var lastRevision = 0
        var prev: JSONObject? = null
        val verified = mutableMapOf<Int, JSONObject>()
        var remoteRevision: Int
        do {
            val page = deviceRequest("/api/roster?after=" + after)
            if (candidateAnchor.isBlank()) candidateAnchor = page.optString("anchor")
            require(
                candidateAnchor.isNotBlank() && page.getString("anchor") == candidateAnchor &&
                    page.getString("household") == v.household
            ) { "Household pairing root changed" }
            remoteRevision = page.getInt("revision")
            val entries = page.getJSONArray("changes")
            if (entries.length() == 0 && after < page.optInt("revision")) {
                throw SecurityException("Incomplete membership history")
            }
            for (index in 0 until entries.length()) {
                val change = entries.getJSONObject(index)
                val body = change.getJSONObject("body")
                val revision = body.getInt("revision")
                val devices = body.getJSONArray("devices")
                require(
                    body.getString("domain") == "narahem.roster.v1" &&
                        body.getString("household") == v.household &&
                        revision == lastRevision + 1 && body.getString("previous") == prevHash
                ) { "Roster continuity rejected" }
                val ids = (0 until devices.length()).map {
                    devices.getJSONObject(it).getString("id")
                }
                require(ids == ids.distinct().sorted()) { "Unsorted/duplicate roster identities" }
                val signer = if (prev == null) {
                    require(devices.length() == 1) { "Invalid genesis roster" }
                    devices.getJSONObject(0)
                } else {
                    val entriesBefore = prev.getJSONArray("devices")
                    (0 until entriesBefore.length()).map { entriesBefore.getJSONObject(it) }
                        .firstOrNull { it.getString("id") == body.getString("signer") }
                        ?: throw SecurityException("Roster signer is not trusted")
                }
                if (prev == null) {
                    require(signer.getString("signing_key") == candidateAnchor) {
                        "Household root changed"
                    }
                }
                require(
                    signer.getString("id") == body.getString("signer") &&
                        HouseholdCrypto.verify(
                            body,
                            change.getString("signature"),
                            signer.getString("signing_key")
                        )
                ) {
                    "Invalid roster signature"
                }
                if (prev != null) {
                    val previousDevices = prev.getJSONArray("devices")
                    for (n in 0 until previousDevices.length()) {
                        val earlier = previousDevices.getJSONObject(n)
                        val same = (0 until devices.length()).map { devices.getJSONObject(it) }
                            .firstOrNull { it.getString("id") == earlier.getString("id") }
                        if (same != null) {
                            require(
                                HouseholdCrypto.canonical(same) ==
                                    HouseholdCrypto.canonical(earlier)
                            ) {
                                "Existing device key substitution rejected"
                            }
                        }
                    }
                }
                val digest = HouseholdCrypto.hashString(
                    HouseholdCrypto.canonical(
                        JSONObject()
                            .put("body", body).put("signature", change.getString("signature"))
                    )
                )
                require(digest == change.getString("hash")) { "Roster hash mismatch" }
                if (onboarding && body.optString("pairing_target") == v.id) {
                    require(
                        prev != null && body.optString("pairing_hash") ==
                            HouseholdCrypto.hashString(
                                HouseholdCrypto.canonical(ownRegistration(v))
                            )
                    ) {
                        "The signed approval is for another device"
                    }
                    val matching = (0 until devices.length()).map { devices.getJSONObject(it) }
                        .firstOrNull { it.getString("id") == v.id }
                    require(
                        matching != null &&
                            HouseholdCrypto.canonical(matching) ==
                            HouseholdCrypto.canonical(v.identity())
                    ) {
                        "Approval substituted device keys"
                    }
                    proofVerified = true
                }
                if (revision == v.revision && v.revision > 0) {
                    require(digest == v.chainHash) { "Pinned roster fork rejected" }
                }
                prevHash = digest
                prev = body
                lastRevision = revision
                verified[revision] = body
            }
            after = lastRevision
            require(lastRevision <= 10000) { "Roster too large" }
        } while (after < remoteRevision)
        require(
            lastRevision >= v.revision && (lastRevision != v.revision || prevHash == v.chainHash)
        ) {
            "Membership rollback or fork rejected"
        }
        require(prev != null) { "Household has no approved devices" }
        val devices = prev.getJSONArray("devices")
        require(
            (0 until devices.length()).any {
                devices.getJSONObject(it).getString("id") == v.id
            }
        ) {
            "This device is no longer trusted"
        }
        if (onboarding) {
            if (!proofVerified) throw PendingPairingException()
            // Only pin after verifying the whole signed chain and the target key commitment signed
            // by an existing trusted member.
            v.anchor = candidateAnchor
        }
        v.revision = lastRevision
        v.chainHash = prevHash
        currentRoster = prev
        rosters = verified
        save()
        return prev
    }

    /** Fetches trip summaries with route outlines. The flag is true when there are no trips. */
    override suspend fun tripSummaries(accountId: String, days: Int): Pair<TripHistory, Boolean> {
        val list = serverTrips(accountId, days)
        return list to list.trips.isEmpty()
    }

    /** Fetches trip summaries and then each trip's full route. */
    override suspend fun tripHistory(accountId: String, days: Int): TripHistory =
        withServerRoutes(serverTrips(accountId, days))

    /** Fetches the server's trip list for a member and date range in one request. */
    private suspend fun serverTrips(accountId: String, days: Int): TripHistory {
        require(accountId.matches(Regex("[a-f0-9]{32}")))
        val earliestFast = System.currentTimeMillis() - days.coerceIn(1, 14) * 86400000L
        val latestFast = System.currentTimeMillis() + 300000L
        val indexed =
            deviceRequest(
                "/api/trips?account_id=$accountId&start=$earliestFast&end=$latestFast" +
                    "&include_routes=true"
            )
        val items = indexed.getJSONArray("trips")
        val indexedTrips = mutableListOf<HouseholdTrip>()
        val indexedPoints = mutableListOf<TripPoint>()
        for (n in 0 until items.length()) {
            val item = items.getJSONObject(n)
            val tripId = item.optString("trip_id").takeIf { it.matches(Regex("[a-f0-9]{32}")) }
            val eventId = item.getString("id")
            val start = item.getLong("started_at")
            val end = item.getLong("ended_at")
            val deviceId = item.getString("device_id")
            indexedTrips.add(
                HouseholdTrip(
                    eventId, accountId, start, end,
                    item.getDouble("distance_m"), item.getDouble("max_speed_mps"),
                    item.getInt("samples"), deviceId, tripId, true, item.optBoolean("matched"),
                    item.optBoolean("processing"), item.optBoolean("partial"),
                    startLabel = item.optString("start_label").takeIf {
                        it.isNotBlank()
                    }?.take(200),
                    endLabel = item.optString("end_label").takeIf { it.isNotBlank() }?.take(200)
                )
            )
            val route = item.optJSONArray("route") ?: continue
            if (route.length() < 2) continue
            for (i in 0 until route.length()) {
                val point = route.getJSONArray(i)
                val whenCaptured = start + (end - start) * i / (route.length() - 1)
                indexedPoints.add(
                    TripPoint(
                        "$eventId:$i", accountId, deviceId,
                        whenCaptured,
                        point.getDouble(0),
                        point.getDouble(1), 5.0, null, tripId, true
                    )
                )
            }
        }
        return TripHistory(indexedTrips, indexedPoints, false)
    }

    /** Fetches the full GPS route of each trip in parallel and adds the points to the history. */
    private suspend fun withServerRoutes(history: TripHistory): TripHistory = coroutineScope {
        val routes = history.trips.take(20).map { trip ->
            async { trip to runCatching { deviceRequest("/api/trips/${trip.id}") }.getOrNull() }
        }.awaitAll().filter { (_, detail) -> (detail?.optJSONArray("route")?.length() ?: 0) >= 2 }
        if (routes.isEmpty()) return@coroutineScope history
        val ids = routes.map { it.first.id }.toSet()
        val points = routes.flatMap { (trip, detail) ->
            val route = detail!!.getJSONArray("route")
            val times = detail.optJSONArray("times")?.takeIf { it.length() == route.length() }
            (0 until route.length()).mapNotNull { i ->
                val point = route.optJSONArray(i) ?: return@mapNotNull null
                TripPoint(
                    "${trip.id}:$i", trip.accountId, trip.deviceId,
                    times?.optLong(i)?.takeIf { it > 0 }
                        ?: (
                            trip.startedAt +
                                (trip.endedAt - trip.startedAt) * i / (route.length() - 1)
                            ),
                    point.getDouble(0), point.getDouble(1), 5.0, null, trip.tripId, true
                )
            }
        }
        history.copy(points = history.points.filter { it.id.substringBefore(":") !in ids } + points)
    }

    /**
     * Fetches arrival and departure alerts about other members since [since]. The server decides
     * and words them.
     */
    suspend fun recentAlerts(since: Long): List<ReceivedAlert> {
        val entries = deviceRequest(
            "/api/alerts?since=${since.coerceAtLeast(0)}"
        ).getJSONArray("alerts")
        return (0 until entries.length()).mapNotNull { index ->
            val item = entries.getJSONObject(index)
            val text = item.optString("text").takeIf { it.isNotBlank() } ?: return@mapNotNull null
            ReceivedAlert(
                item.getString("id"),
                item.getString("account_id"),
                item.getLong("captured_at"),
                text.take(300)
            )
        }
    }

    /** Fetches the latest location, profile and saved places that this device may read. */
    override suspend fun household(): HouseholdSnapshot {
        val v = vault ?: error("No device credentials")
        val roster = syncRoster()
        val membership = try {
            val accountsResponse = accounts.authenticated(
                "/api/household/members"
            ).getJSONArray("members")
            (0 until accountsResponse.length()).associate {
                val person = accountsResponse.getJSONObject(it)
                person.getString("id") to person.optString("username", "Member")
            }
        } catch (_: IllegalStateException) {
            val others = deviceRequest("/api/sharing/audience").getJSONArray("eligible_members")
            (0 until others.length()).associate {
                val person = others.getJSONObject(it)
                person.getString("id") to person.optString("name", "Member")
            }
        }
        val view = deviceRequest("/api/view")
        require(view.getInt("revision") == v.revision) { "Roster changed during location fetch" }
        val served = view.getJSONArray("records")
        val decrypted = (0 until served.length()).map { served.getJSONObject(it) }
        val profiles = decrypted.filter {
            it.getString("kind") == "profile" && it.getString("operation") == "upsert"
        }
            .associate { it.getString("entity_id") to it.getJSONObject("data") }
        val locations = decrypted.filter {
            it.getString("kind") == "location" && it.getString("operation") == "upsert"
        }
            .associateBy { it.getString("entity_id") }
        val people = membership.map { (id, name) ->
            val location = locations[id]
            val data = location?.getJSONObject("data")
            HouseholdPerson(
                id, profiles[id]?.optString("name")?.takeIf { it.isNotBlank() } ?: name,
                data?.optDouble("lat"), data?.optDouble("lon"), data?.optDouble("accuracy"),
                location?.optLong("captured_at") ?: 0, profiles[id]?.optString("photo"),
                data?.optDouble("speed_mps")?.takeIf { it.isFinite() },
                data?.takeIf { it.has("battery_pct") }?.optInt("battery_pct"),
                data?.takeIf { it.has("charging") }?.optBoolean("charging"),
                data?.optDouble("trip_max_speed_mps")?.takeIf { it.isFinite() },
                data?.optDouble("trip_distance_m")?.takeIf { it.isFinite() },
                data?.optDouble("recent_trip_max_speed_mps")?.takeIf { it.isFinite() },
                data?.optString("trip_id")?.takeIf { it.matches(Regex("[a-f0-9]{32}")) },
                location?.optLong("still_since")?.takeIf { it > 0 },
                location?.optLong("last_contact")?.takeIf { it > 0 }
            )
        }
        val places = decrypted.filter {
            it.getString("kind") == "place" && it.getString("operation") == "upsert"
        }.map {
            val data = it.getJSONObject("data")
            val alertData = data.optJSONObject("alerts") ?: JSONObject()
            val alerts = alertData.keys().asSequence().mapNotNull { id ->
                alertData.optJSONObject(id)?.let { rule ->
                    id to PlaceAlert(rule.optBoolean("arrival"), rule.optBoolean("departure"))
                }
            }.toMap()
            HouseholdPlace(
                it.getString("entity_id"),
                data.getString("name"),
                data.getDouble("lat"),
                data.getDouble("lon"),
                data.getDouble("radius"),
                it.getString("id"),
                alerts,
                data.toString()
            )
        }
        return HouseholdSnapshot(people, places)
    }

    /** Clears the cached roster, device state and audience. */
    private fun forgetEnvelopeContext() {
        contextAt = 0L
        contextDevice = null
        contextAudience = null
    }

    /**
     * Returns the roster, device state and audience used to build records, cached for up to a
     * minute.
     */
    private suspend fun envelopeContext(): Triple<JSONObject, JSONObject, JSONObject> {
        val now = System.currentTimeMillis()
        val roster = currentRoster
        val device = contextDevice
        val audience = contextAudience
        if (roster != null && device != null && audience != null && now - contextAt in 0..60_000L) {
            return Triple(roster, device, audience)
        }
        val fresh =
            Triple(
                syncRoster(),
                deviceRequest("/api/device"),
                deviceRequest("/api/sharing/audience")
            )
        contextAt = now
        contextDevice = fresh.second
        contextAudience = fresh.third
        return fresh
    }

    /** Builds a signed record encrypted for every allowed recipient, plus the server's copy. */
    private suspend fun prepareEnvelope(
        kind: String,
        id: String,
        data: JSONObject,
        replaces: String? = null,
        operation: String = "upsert",
        capturedAt: Long = System.currentTimeMillis()
    ): JSONObject {
        val saved = store.read() ?: error("Device not registered")
        require(saved.id == vault?.id) { "Device session changed" }
        vault = saved
        val v = saved
        if (kind == "place" || kind == "profile") forgetEnvelopeContext()
        val (roster, current, audienceReply) = envelopeContext()
        require(current.getString("status") == "approved") { "Device is not trusted" }
        if (kind == "location" || kind == "event") {
            require(
                current.optBoolean("sharing") && !trackingPrefs.getBoolean("tracking-paused", false)
            ) {
                "Device sharing is paused"
            }
        }
        val seq = maxOf(v.sequence, current.getLong("sequence")) + 1
        val pointer = if (kind == "profile") {
            deviceRequest("/api/profile/current").optString("replaces")
                .takeIf { it.matches(Regex("[a-f0-9]{32}")) }
        } else {
            replaces
        }
        val audience = if (kind == "location" || kind == "event") {
            val array = audienceReply.getJSONArray("account_ids")
            val policy = (0 until array.length()).map { array.getString(it) }.toSet()
            // The server may narrow the recipients but must never widen the audience saved on this
            // phone. The admin browser always sees a phone that shares its location.
            val owner = audienceReply.optJSONObject("owner_viewer")?.optString("id")
            v.audienceIds?.let { policy.intersect(it + setOfNotNull(owner)) } ?: policy
        } else {
            null
        }
        val body = JSONObject().put("domain", "narahem.record.v1")
            .put("household", v.household).put("revision", v.revision)
            .put("id", HouseholdCrypto.randomId()).put("sender", v.id)
            .put("sequence", seq).put("kind", kind).put("entity_id", id)
            .put("operation", operation).put("replaces", pointer ?: JSONObject.NULL)
            .put("captured_at", capturedAt)
        val payload = JSONObject().put("domain", "narahem.payload.v1")
        for (key in listOf(
            "household", "revision", "id", "sender", "sequence", "kind",
            "entity_id", "operation", "replaces", "captured_at"
        )) {
            payload.put(key, body.get(key))
        }
        payload.put("data", data)
        val devices = roster.getJSONArray("devices")
        val recipients = JSONArray()
        for (n in 0 until devices.length()) {
            val dev = devices.getJSONObject(n)
            if (audience != null && dev.getString("account_id") != v.accountId &&
                dev.getString("account_id") !in audience
            ) {
                continue
            }
            recipients.put(
                JSONObject().put("device_id", dev.getString("id"))
                    .put("box", HouseholdCrypto.seal(payload, dev.getString("box_key")))
            )
        }
        body.put("recipients", recipients)
        if (operation == "upsert" || kind == "place") {
            val serverKey =
                current.optString("trip_processing_key").takeIf { it.isNotBlank() && it != "null" }
                    ?: error("Server key unavailable")
            body.put("server_box", HouseholdCrypto.seal(payload, serverKey))
        }
        return JSONObject().put(
            "body",
            body
        ).put("signature", HouseholdCrypto.sign(body, v.signingPrivate))
    }

    /** Uploads a record and maps server rejections to specific exceptions. */
    private suspend fun sendEnvelope(envelope: JSONObject) {
        try {
            deviceRequest("/api/records", envelope, "POST")
            vault?.let {
                it.sequence = maxOf(it.sequence, envelope.getJSONObject("body").getLong("sequence"))
                save()
            }
        } catch (failure: DeviceApiFailure) {
            when {
                failure.status == 422 && failure.message.orEmpty().contains(
                    "retention window"
                ) -> throw ExpiredTrackingSample()

                failure.status == 409 && (
                    failure.message.orEmpty().contains("membership") ||
                        failure.message.orEmpty().contains("sharing audience") ||
                        failure.message.orEmpty().contains("sequence replay")
                    ) -> {
                    forgetEnvelopeContext()
                    throw ReprepareTrackingSample()
                }

                failure.status == 401 || failure.status == 403 -> {
                    trackingPrefs.edit().putBoolean("resume-sharing", false).apply()
                    throw TrackingDisabled()
                }

                else -> throw failure
            }
        }
    }

    /** Builds and uploads a record, retrying once with fresh state if the roster changed. */
    private suspend fun publish(
        kind: String,
        id: String,
        data: JSONObject,
        replaces: String? = null,
        operation: String = "upsert",
        capturedAt: Long = System.currentTimeMillis()
    ) = publication.withLock {
        var headers = emptyMap<String, String>()
        var pointer = replaces
        if (kind == "place") {
            val manifest = deviceRequest("/api/places/manifest")
            val snapshot = household()
            val old = snapshot.places.firstOrNull { it.id == id }
            val sameGeometry =
                operation == "upsert" && old != null && old.latitude == data.getDouble("lat") &&
                    old.longitude == data.getDouble("lon") && old.radius == data.getDouble("radius")
            if (operation == "upsert" && !sameGeometry) {
                val conflict = snapshot.places.firstOrNull {
                    it.id != id &&
                        PlaceMatching.distance(
                            data.getDouble("lat"),
                            data.getDouble("lon"),
                            it.latitude,
                            it.longitude
                        ) <
                        data.getDouble("radius") + it.radius
                }
                require(conflict == null) {
                    "This area overlaps ${conflict?.name}. Open Places to edit the existing " +
                        "place or change this area."
                }
            }
            val entries = manifest.getJSONArray("places")
            pointer =
                (0 until entries.length()).map { entries.getJSONObject(it) }.firstOrNull {
                    it.getString("id") ==
                        id
                }?.getString("record_id")
            require(replaces == null || old == null || old.recordId == replaces) {
                "This place changed. Refresh before editing."
            }
            headers = mapOf("X-Places-State" to manifest.getString("token"))
        }
        val envelope = prepareEnvelope(kind, id, data, pointer, operation, capturedAt)
        deviceRequest("/api/records", envelope, "POST", headers)
        vault?.let {
            it.sequence = maxOf(it.sequence, envelope.getJSONObject("body").getLong("sequence"))
            save()
        }
    }

    /** Adds a location to the offline queue if sharing is still enabled. */
    fun queueLocation(fix: LocalFix, capturedAt: Long) = OfflineOutbox.locked {
        if (trackingPrefs.getBoolean("resume-sharing", false)) {
            pendingQueue().append(OfflineTrackingCodec.location(fix, capturedAt))
        }
    }

    /** Adds a completed trip to the offline queue if sharing is still enabled. */
    fun queueTrip(summary: CompletedTrip) = OfflineOutbox.locked {
        if (trackingPrefs.getBoolean("resume-sharing", false)) {
            pendingQueue().append(OfflineTrackingCodec.trip(summary))
        }
    }

    /**
     * Uploads up to [limit] queued items, sending locations in batches. Returns the number sent.
     */
    suspend fun flushPendingTracking(limit: Int = 8): Int = outboxDeliveryLock.withLock {
        if (!trackingPrefs.getBoolean("resume-sharing", false)) return@withLock 0
        val queue = pendingQueue()
        if (queue.size() == 0) return@withLock 0
        publication.withLock {
            val saved = store.read() ?: error("Device not registered")
            require(saved.id == vault?.id) { "Device session changed" }
            vault = saved
            val current = try {
                deviceRequest("/api/device")
            } catch (failure: DeviceApiFailure) {
                if (failure.status == 401 || failure.status == 403) {
                    trackingPrefs.edit().putBoolean("resume-sharing", false).apply()
                    queue.clear()
                    throw TrackingDisabled()
                }
                throw failure
            }
            if (current.optString("status") != "approved" || !current.optBoolean("sharing")) {
                trackingPrefs.edit().putBoolean("resume-sharing", false).apply()
                queue.clear()
                throw TrackingDisabled()
            }
            val delivery = QueuedTrackingDelivery(
                queue,
                allowed = {
                    trackingPrefs.getBoolean("resume-sharing", false) &&
                        store.read()?.id == vault?.id
                },
                prepare = { item ->
                    val v = vault ?: error("Device not enrolled")
                    val pending = OfflineTrackingCodec.payload(item, v.accountId)
                    prepareEnvelope(
                        pending.kind,
                        pending.entityId,
                        pending.data,
                        capturedAt = item.getLong("captured")
                    )
                },
                send = { envelope ->
                    sendEnvelope(envelope)
                },
                onExpired = { queue.recordExpired() }
            )
            delivery.drain(limit)
        }
    }

    /** Validates and uploads one location immediately. */
    override suspend fun publishLocation(fix: LocalFix, capturedAt: Long) {
        require(fix.latitude in -90.0..90.0 && fix.longitude in -180.0..180.0) {
            "Invalid coordinates"
        }
        val v = vault ?: error("Device not enrolled")
        val payload = JSONObject().put("lat", fix.latitude)
            .put("lon", fix.longitude).put("accuracy", fix.accuracy.toDouble())
        fix.speedMps?.let { payload.put("speed_mps", it.toDouble()) }
        fix.batteryPct?.let { payload.put("battery_pct", it) }
        fix.charging?.let { payload.put("charging", it) }
        fix.tripMaxSpeedMps?.let { payload.put("trip_max_speed_mps", it) }
        fix.tripDistanceMeters?.let { payload.put("trip_distance_m", it) }
        fix.tripStartedAt?.let { payload.put("trip_started_at", it) }
        fix.tripId?.let { payload.put("trip_id", it) }
        fix.recentTripMaxSpeedMps?.let { payload.put("recent_trip_max_speed_mps", it) }
        publish("location", v.accountId, payload, capturedAt = capturedAt)
    }

    /**
     * Publishes a new or edited place, checking the place list hasn't changed since it was loaded.
     */
    override suspend fun savePlace(
        name: String,
        lat: Double,
        lon: Double,
        radius: Double,
        existing: HouseholdPlace?,
        alerts: Map<String, PlaceAlert>
    ) {
        require(
            name.isNotBlank() && name.length <= 80 && lat in -90.0..90.0 &&
                lon in -180.0..180.0 && radius in 1.0..10000.0
        ) { "Invalid place information" }
        require(existing == null || existing.recordId != null) {
            "Refresh the place before editing."
        }
        val rules = JSONObject()
        for ((id, alert) in alerts) {
            require(id.matches(Regex("[a-f0-9]{32}"))) { "Invalid alert member" }
            if (alert.arrival || alert.departure) {
                rules.put(
                    id,
                    JSONObject()
                        .put("arrival", alert.arrival).put("departure", alert.departure)
                )
            }
        }
        val data = JSONObject(existing?.extraData ?: "{}").put("name", name.trim())
            .put("lat", lat).put("lon", lon).put("radius", radius).put("alerts", rules)
        publish("place", existing?.id ?: HouseholdCrypto.randomId(), data, existing?.recordId)
    }

    /** Publishes a delete for the place. */
    override suspend fun deletePlace(place: HouseholdPlace) {
        require(place.recordId != null) { "Refresh the place before deleting." }
        publish("place", place.id, JSONObject(), place.recordId, "delete")
    }

    /** Returns the audience the server reports for this device. */
    override suspend fun sharingAudience(): Set<String> {
        val v = vault ?: error("Device not enrolled")
        val list = deviceRequest("/api/sharing/audience").getJSONArray("account_ids")
        val serverPolicy = (0 until list.length()).map { list.getString(it) }.toSet()
        return v.audienceIds?.intersect(serverPolicy) ?: serverPolicy
    }

    /** Returns the admin account the server offers as an optional viewer, if any. */
    override suspend fun ownerViewerId(): String? =
        deviceRequest("/api/sharing/audience").optJSONObject("owner_viewer")
            ?.optString("id")?.takeIf { it.matches(Regex("[a-f0-9]{32}")) }

    /** Returns the members the server lists as eligible viewers. */
    override suspend fun sharingChoices(): List<HouseholdPerson> {
        val response = deviceRequest("/api/sharing/audience")
        val list = response.optJSONArray("eligible_members")
            ?: error("Update the server to load all location visibility choices.")
        return (0 until list.length()).map { list.getJSONObject(it) }.filter {
            it.optString("role") !=
                "admin"
        }.map { item ->
            HouseholdPerson(item.getString("id"), item.getString("name"))
        }
    }

    /** Shares with members this phone hasn't seen before and returns their names. */
    override suspend fun includeNewMembers(choices: List<HouseholdPerson>): List<String> {
        val v = store.read() ?: return emptyList()
        val eligible = choices.map { it.id }.toSet()
        val known = v.knownMembers
        if (known == null) {
            v.knownMembers = eligible
            vault = v
            save()
            return emptyList()
        }
        val newcomers = eligible - known
        if (newcomers.isEmpty()) return emptyList()
        // Only a pinned list needs updating: without one the server already shares with everyone.
        // The server refuses members who have left, so keep only current viewers.
        v.audienceIds?.let { saved ->
            val viewers = eligible + setOfNotNull(ownerViewerId())
            setSharingAudience(saved.intersect(viewers) + newcomers)
        }
        val updated = store.read() ?: return emptyList()
        updated.knownMembers = known + eligible
        vault = updated
        save()
        return choices.filter { it.id in newcomers }.map { it.name }
    }

    /**
     * Saves the audience locally and on the server. Records are only ever encrypted for this saved
     * list, even if the server suggests more recipients.
     */
    override suspend fun setSharingAudience(ids: Set<String>): Unit = publication.withLock {
        val saved = store.read() ?: error("Device not enrolled")
        require(saved.id == vault?.id) { "Device session changed" }
        vault = saved
        val v = saved
        val ordered = JSONArray()
        ids.sorted().forEach { ordered.put(it) }
        deviceRequest("/api/sharing/audience", JSONObject().put("account_ids", ordered), "PUT")
        v.audienceIds = ids.toSet()
        save()
    }

    /** Validates the JPEG data URI and publishes it encrypted with the display name. */
    override suspend fun saveProfilePhoto(name: String, photo: String) {
        require(name.isNotBlank() && name.length <= 64) { "Profile name is invalid" }
        require(photo.startsWith("data:image/jpeg;base64,") && photo.length <= 14500) {
            "Profile photo is too large"
        }
        val encoded = photo.substringAfter(',')
        require(encoded.matches(Regex("[A-Za-z0-9+/=]+"))) { "Invalid profile photo" }
        val v = vault ?: error("Device not enrolled")
        publish("profile", v.accountId, JSONObject().put("name", name).put("photo", photo))
    }

    /**
     * Enables or disables sharing on the server. Disabling also clears the resume flag and the
     * offline queue, which makes the background service stop.
     */
    override suspend fun setSharing(enabled: Boolean) {
        if (!enabled) {
            trackingPrefs.edit().putBoolean(
                "resume-sharing",
                false
            ).putBoolean("tracking-paused", true).apply()
            sharingAllowed = false
            clearPendingTracking()
        }
        deviceRequest("/api/sharing", JSONObject().put("enabled", enabled), "PUT")
        if (enabled) trackingPrefs.edit().putBoolean("tracking-paused", false).apply()
        sharingAllowed = enabled
        forgetEnvelopeContext()
    }

    /**
     * Locks shared by every instance, so the activity and the background service never publish at
     * the same time.
     */
    companion object {
        private val publicationLock = Mutex()
        private val outboxDeliveryLock = Mutex()
    }
}
