package com.robiem.narahem.data.household

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.FakeAndroidKeyStore
import com.robiem.narahem.data.account.Account
import com.robiem.narahem.data.location.LocalFix
import com.robiem.narahem.tracking.CompletedTrip
import com.robiem.narahem.tracking.TrackingDisabled
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/** [NativeHouseholdRepository] against [FakeHouseholdServer], with real libsodium encryption. */
@RunWith(AndroidJUnit4::class)
class NativeHouseholdRepositoryTest {
    private lateinit var fake: FakeHouseholdServer
    private lateinit var client: OkHttpClient
    private lateinit var address: String
    private lateinit var repo: NativeHouseholdRepository
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private val prefs get() = context.getSharedPreferences("server", Context.MODE_PRIVATE)

    /** Enrolls the phone in a household the owner started, approved by emailed code. */
    private fun joined() = runBlocking { fake.join(repo) }
    private fun resumeSharing() = prefs.edit().putBoolean("resume-sharing", true).commit()
    private fun count(route: String) = fake.log.count { it == route }

    @Before fun setUp() {
        DesktopSodium.install()
        FakeAndroidKeyStore.install()
        fake = FakeHouseholdServer()
        fake.start()
        client = fake.client
        address = fake.address
        repo = NativeHouseholdRepository(context, fake.accounts, client)
    }

    @After fun tearDown() {
        fake.stop()
    }

    private fun member(role: String = "member", verified: Boolean = true) =
        fake.phoneMember(role, verified)

    private fun fix(lat: Double = 51.5, lon: Double = -0.12) =
        LocalFix(lat, lon, 8f, speedMps = 3f, batteryPct = 80, charging = false)

    @Test fun phoneJoinsByEmailedCodeAndPinsTheOwnersRoot() = runBlocking<Unit> {
        fake.startWithOwner()
        repo.enroll(member(), address)
        assertEquals("email-code", repo.status(member()))
        assertEquals(64, repo.deviceFingerprint().length)
        assertEquals("", repo.ownerFingerprint())
        val code = repo.ownPairingCode()
        assertTrue(code.matches(Regex("[0-9]{6}")))
        repo.sendPhoneCode()
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.verifyPhoneCode("12") }
        }
        repo.verifyPhoneCode("654321")
        assertEquals("ready", repo.status(member()))
        assertEquals(
            HouseholdCrypto.sha(HouseholdCrypto.unb64(fake.ownerSigning.publicKey)),
            repo.ownerFingerprint()
        )
        assertEquals(fake.pairingHash(), repo.deviceFingerprint())
        assertEquals(fake.phoneAccount, repo.accountId())
        assertEquals(1, count("POST /api/phones/code"))
    }

    @Test fun enrollmentNeedsAVerifiedAccountAndHappensOnce() = runBlocking<Unit> {
        fake.startWithOwner()
        repo.enroll(member(verified = false), address)
        assertEquals("verify-email", repo.status(member(verified = false)))
        assertEquals("", repo.ownPairingCode())
        repo.enroll(member(), address)
        val first = repo.deviceFingerprint()
        repo.enroll(member(), address)
        assertEquals(first, repo.deviceFingerprint())
        assertEquals(1, count("POST /api/devices/register"))
        val badId = Account("Sam", true, fake.household, "not-an-id")
        repo.forgetLocalDevice()
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.enroll(badId, address) }
        }
    }

    @Test fun firstAdminDeviceStartsTheHouseholdWithAnEmailCode() = runBlocking<Unit> {
        repo.enroll(member("admin"), address)
        assertEquals("first-device", repo.status(member("admin")))
        repo.sendFirstDeviceCode()
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.bootstrapWithEmail("abc") }
        }
        repo.bootstrapWithEmail("123456")
        assertEquals("ready", repo.status(member("admin")))
        assertEquals(fake.anchor, fake.phoneIdentity().getString("signing_key"))
        assertEquals(64, repo.ownerFingerprint().length)
    }

    @Test fun approvedDeviceWaitsForASignedPairingApproval() = runBlocking<Unit> {
        fake.startWithOwner()
        repo.enroll(member(), address)
        // Listed in the roster, but without the owner's signed approval of this registration.
        fake.changes.add(fake.signedChange(fake.currentDevices() + fake.phoneIdentity()))
        fake.deviceStatus = "approved"
        assertEquals("pairing", repo.status(member()))
        fake.approvePhone()
        assertEquals("ready", repo.status(member()))
    }

    @Test fun pairingApprovalForAnotherRegistrationIsRejected() = runBlocking<Unit> {
        fake.startWithOwner()
        repo.enroll(member(), address)
        fake.changes.add(
            fake.signedChange(fake.currentDevices() + fake.phoneIdentity()) {
                put("pairing_target", fake.registration!!.getString("id"))
                put("pairing_hash", "0".repeat(64))
            }
        )
        fake.deviceStatus = "approved"
        val error = assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.status(member()) }
        }
        assertEquals("The signed approval is for another device", error.message)
    }

    @Test fun ownerFingerprintCanBeConfirmedByHand() = runBlocking<Unit> {
        fake.startWithOwner()
        repo.enroll(member(), address)
        fake.approvePhone()
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.verifyOwnerFingerprint("0".repeat(64)) }
        }
        repo.verifyOwnerFingerprint(
            HouseholdCrypto.sha(HouseholdCrypto.unb64(fake.ownerSigning.publicKey)).uppercase()
        )
        assertEquals("ready", repo.status(member()))
    }

    /** Appends a change after the phone joined and expects the next sync to reject it. */
    private fun rejects(message: String, change: () -> Unit) {
        joined()
        change()
        val error = assertThrows(Exception::class.java) { runBlocking { repo.syncRoster() } }
        assertEquals(message, error.message)
    }

    @Test fun rosterSignedWithTheWrongKeyIsRejected() = rejects("Invalid roster signature") {
        val forged = HouseholdCrypto.signingKeys()
        fake.changes.add(fake.signedChange(fake.currentDevices(), signWith = forged.privateKey))
    }

    @Test fun rosterFromAnUnknownSignerIsRejected() = rejects("Roster signer is not trusted") {
        fake.changes.add(fake.signedChange(fake.currentDevices(), signer = "f".repeat(32)))
    }

    @Test fun replacingAnExistingDevicesKeysIsRejected() =
        rejects("Existing device key substitution rejected") {
            val swapped = fake.currentDevices().map {
                if (it.getString("id") == fake.ownerId) {
                    JSONObject(it.toString()).put("box_key", HouseholdCrypto.boxKeys().publicKey)
                } else {
                    it
                }
            }
            fake.changes.add(fake.signedChange(swapped))
        }

    @Test fun rosterWithAWrongHashIsRejected() = rejects("Roster hash mismatch") {
        fake.changes.add(fake.signedChange(fake.currentDevices()).put("hash", "0".repeat(64)))
    }

    @Test fun rosterThatSkipsARevisionIsRejected() = rejects("Roster continuity rejected") {
        fake.changes.add(fake.signedChange(fake.currentDevices()) { put("revision", 9) })
    }

    @Test fun rosterRollbackIsRejected() = rejects("Membership rollback or fork rejected") {
        fake.changes.removeAt(fake.changes.lastIndex)
    }

    @Test fun rosterForkAtThePinnedRevisionIsRejected() = rejects("Pinned roster fork rejected") {
        val last = fake.changes.removeAt(fake.changes.lastIndex)
        fake.changes.add(fake.signedChange(fake.currentDevices() + fake.phoneIdentity()))
        assertTrue(last.getString("hash") != fake.changes.last().getString("hash"))
    }

    @Test fun changedHouseholdRootIsRejected() = rejects("Household pairing root changed") {
        fake.anchor = HouseholdCrypto.signingKeys().publicKey
    }

    @Test fun phoneRemovedFromTheRosterIsNoLongerTrusted() = rejects(
        "This device is no longer trusted"
    ) {
        fake.changes.add(fake.signedChange(listOf(fake.ownerIdentity())))
    }

    @Test fun duplicateRosterEntriesAreRejected() = rejects(
        "Unsorted/duplicate roster identities"
    ) {
        val owner = fake.ownerIdentity()
        val body = fake.signedChange(listOf(owner)).getJSONObject("body")
        body.put("devices", JSONArray().put(owner).put(owner))
        val signature = HouseholdCrypto.sign(body, fake.ownerSigning.privateKey)
        fake.changes.add(JSONObject().put("body", body).put("signature", signature).put("hash", ""))
    }

    @Test fun locationIsEncryptedOnlyForTheSavedAudience() = runBlocking<Unit> {
        joined()
        val other = "c".repeat(32)
        val otherBox = fake.addMember(other)
        fake.audience = listOf(fake.ownerAccount, other)
        assertEquals(setOf(fake.ownerAccount, other), repo.sharingAudience())
        repo.setSharingAudience(setOf(fake.ownerAccount))
        assertEquals(setOf(fake.ownerAccount), repo.sharingAudience())
        repo.publishLocation(fix(), 1_700_000_000_000)
        val body = fake.records.single().getJSONObject("body")
        val recipients = body.getJSONArray("recipients")
        val ids = (0 until recipients.length()).map {
            recipients.getJSONObject(it).getString("device_id")
        }
        assertEquals(setOf(fake.ownerId, fake.registration!!.getString("id")), ids.toSet())
        val ownerCopy = recipients.getJSONObject(ids.indexOf(fake.ownerId)).getString("box")
        val opened = HouseholdCrypto.open(
            ownerCopy,
            fake.ownerBox.publicKey,
            fake.ownerBox.privateKey
        )
        assertEquals(51.5, opened.getJSONObject("data").getDouble("lat"), 0.0)
        assertEquals(80, opened.getJSONObject("data").getInt("battery_pct"))
        assertThrows(Exception::class.java) {
            HouseholdCrypto.open(ownerCopy, otherBox.publicKey, otherBox.privateKey)
        }
        assertEquals(1L, body.getLong("sequence"))
        repo.publishLocation(fix(), 1_700_000_001_000)
        assertEquals(2L, fake.records.last().getJSONObject("body").getLong("sequence"))
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.publishLocation(fix(lat = 91.0), 0) }
        }
    }

    @Test fun newMembersAreAddedToAPinnedAudienceOnce() = runBlocking<Unit> {
        joined()
        val kim = HouseholdPerson("k".repeat(32), "Kim")
        val lee = HouseholdPerson("l".repeat(32), "Lee")
        fake.ownerViewer = fake.ownerAccount
        // The first look only learns who is already here.
        assertEquals(emptyList<String>(), repo.includeNewMembers(listOf(kim)))
        repo.setSharingAudience(setOf(fake.ownerAccount))
        assertEquals(listOf("Lee"), repo.includeNewMembers(listOf(kim, lee)))
        assertEquals(setOf(fake.ownerAccount, lee.id), repo.sharingAudience())
        // Someone the user removed stays removed, and a member is only announced once.
        assertEquals(emptyList<String>(), repo.includeNewMembers(listOf(kim, lee)))
        assertEquals(setOf(fake.ownerAccount, lee.id), repo.sharingAudience())
    }

    @Test fun pausedSharingRefusesLocationsAndCanResume() = runBlocking<Unit> {
        joined()
        repo.setSharing(false)
        assertFalse(repo.sharingEnabled())
        assertFalse(fake.sharing)
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.publishLocation(fix(), 1_700_000_000_000) }
        }
        repo.setSharing(true)
        assertTrue(repo.sharingEnabled())
        assertEquals("ready", repo.status(member()))
        repo.publishLocation(fix(), 1_700_000_000_000)
        assertEquals(1, fake.records.size)
    }

    @Test fun placesAreSavedEditedAndDeletedAgainstTheManifest() = runBlocking<Unit> {
        joined()
        fake.members =
            JSONArray().put(JSONObject().put("id", fake.ownerAccount).put("username", "Alex"))
        val alerts = mapOf(fake.ownerAccount to PlaceAlert(true, false))
        repo.savePlace("Home", 51.5, -0.12, 100.0, null, alerts)
        assertEquals("places-token", fake.headers["POST /api/records"])
        val home = repo.household().places.single()
        assertEquals("Home", home.name)
        assertEquals(PlaceAlert(true, false), home.alerts[fake.ownerAccount])
        val error = assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.savePlace("School", 51.5005, -0.12, 100.0, null, emptyMap()) }
        }
        assertTrue(error.message!!.startsWith("This area overlaps Home."))
        repo.savePlace("Home sweet home", 51.5, -0.12, 100.0, home, emptyMap())
        val renamed = repo.household().places.single()
        assertEquals("Home sweet home", renamed.name)
        assertEquals(home.recordId, fake.records.last().getJSONObject("body").getString("replaces"))
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.savePlace("Home", 51.5, -0.12, 100.0, home, emptyMap()) }
        }
        repo.deletePlace(renamed)
        assertTrue(repo.household().places.isEmpty())
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.savePlace("", 0.0, 0.0, 100.0, null, emptyMap()) }
        }
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking {
                repo.savePlace("Bad", 0.0, 0.0, 100.0, null, mapOf("x" to PlaceAlert(true, true)))
            }
        }
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.deletePlace(home.copy(recordId = null)) }
        }
    }

    @Test fun householdCombinesMembersProfilesAndLocations() = runBlocking<Unit> {
        joined()
        val owner = fake.ownerAccount
        fake.view["profile:$owner"] = JSONObject().put("id", "p").put("kind", "profile")
            .put("operation", "upsert").put("entity_id", owner)
            .put(
                "data",
                JSONObject().put("name", "Alex").put("photo", "data:image/jpeg;base64,AA==")
            )
        fake.view["location:$owner"] = JSONObject().put("id", "l").put("kind", "location")
            .put("operation", "upsert").put("entity_id", owner).put("captured_at", 1234L)
            .put("still_since", 1000L).put("last_contact", 1200L)
            .put(
                "data",
                JSONObject().put("lat", 1.5).put("lon", 2.5).put("accuracy", 9.0)
                    .put("speed_mps", 4.0).put("battery_pct", 55).put("charging", true)
                    .put("trip_id", "d".repeat(32))
            )
        // Members who can't list accounts fall back to the sharing audience names.
        fake.eligible = JSONArray().put(JSONObject().put("id", owner).put("name", "Owner"))
        val person = repo.household().people.single()
        // The server's name wins over the name saved with the profile photo, which can be stale.
        assertEquals("Owner", person.name)
        assertEquals("data:image/jpeg;base64,AA==", person.photo)
        assertEquals(1.5, person.latitude!!, 0.0)
        assertEquals(55, person.batteryPct)
        assertEquals(true, person.charging)
        assertEquals("d".repeat(32), person.tripId)
        assertEquals(1234L, person.capturedAt)
        fake.members = JSONArray().put(JSONObject().put("id", owner).put("username", "alex"))
        fake.view.remove("profile:$owner")
        assertEquals("alex", repo.household().people.single().name)
    }

    @Test fun profilePhotoIsCheckedAndReplacesTheCurrentProfile() = runBlocking<Unit> {
        val photo = "data:image/jpeg;base64,/9j/AA=="
        joined()
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.saveProfilePhoto("", photo) }
        }
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.saveProfilePhoto("Sam", "data:image/png;base64,AA==") }
        }
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.saveProfilePhoto("Sam", "data:image/jpeg;base64,<script>") }
        }
        fake.profileRecord = "e".repeat(32)
        repo.saveProfilePhoto("Sam", photo)
        val body = fake.records.single().getJSONObject("body")
        assertEquals("profile", body.getString("kind"))
        assertEquals("e".repeat(32), body.getString("replaces"))
        assertEquals(
            "Sam",
            fake.serverCopy(fake.records.single()).getJSONObject("data").getString("name")
        )
    }

    @Test fun queuedLocationsAndTripsUploadLater() = runBlocking<Unit> {
        joined()
        repo.queueLocation(fix(), System.currentTimeMillis())
        assertEquals(0, repo.pendingTrackingCount())
        assertEquals(0, repo.flushPendingTracking())
        resumeSharing()
        repo.queueLocation(fix(), System.currentTimeMillis())
        repo.queueLocation(fix(51.6), System.currentTimeMillis())
        repo.queueTrip(
            CompletedTrip(
                System.currentTimeMillis() - 60_000,
                System.currentTimeMillis(),
                12f,
                800.0,
                20,
                "9".repeat(32),
                listOf(listOf(51.5, -0.12), listOf(51.6, -0.1))
            )
        )
        assertEquals(3, repo.pendingTrackingCount())
        assertEquals(3, repo.flushPendingTracking())
        assertEquals(0, repo.pendingTrackingCount())
        assertEquals(
            setOf("location", "event"),
            fake.records.map {
                it.getJSONObject("body").getString("kind")
            }.toSet()
        )
        repo.clearPendingTracking()
    }

    @Test fun uploadsArePreparedAgainAfterTheRosterChanged() = runBlocking<Unit> {
        joined()
        resumeSharing()
        repo.queueLocation(fix(), System.currentTimeMillis())
        fake.failNext("POST /api/records", 409, "Stale membership")
        assertEquals(0, repo.flushPendingTracking())
        assertEquals(1, repo.pendingTrackingCount())
        assertEquals(1, repo.flushPendingTracking())
        assertEquals(1, fake.records.size)
    }

    @Test fun locationsPastTheRetentionWindowAreDropped() = runBlocking<Unit> {
        joined()
        resumeSharing()
        repo.queueLocation(fix(), System.currentTimeMillis())
        fake.failNext("POST /api/records", 422, "Outside the retention window")
        repo.flushPendingTracking()
        assertEquals(0, repo.pendingTrackingCount())
        assertTrue(fake.records.isEmpty())
    }

    @Test fun signedOutOrPausedDeviceStopsSharingAndClearsTheQueue() = runBlocking<Unit> {
        joined()
        resumeSharing()
        repo.queueLocation(fix(), System.currentTimeMillis())
        fake.failNext("GET /api/device", 401, "Sign in")
        assertThrows(TrackingDisabled::class.java) { runBlocking { repo.flushPendingTracking() } }
        assertFalse(prefs.getBoolean("resume-sharing", true))
        assertEquals(0, repo.pendingTrackingCount())
        resumeSharing()
        repo.queueLocation(fix(), System.currentTimeMillis())
        fake.sharing = false
        assertThrows(TrackingDisabled::class.java) { runBlocking { repo.flushPendingTracking() } }
        assertEquals(0, repo.pendingTrackingCount())
        resumeSharing()
        fake.sharing = true
        repo.queueLocation(fix(), System.currentTimeMillis())
        fake.failNext("POST /api/records", 403, "Forbidden")
        assertThrows(TrackingDisabled::class.java) { runBlocking { repo.flushPendingTracking() } }
    }

    @Test fun findMyPhoneAcceptsOnlyOwnerSignedCommandsOnce() = runBlocking<Unit> {
        joined()
        assertNull(repo.nextFindPhoneCommand())
        assertEquals(false, fake.bodies["PUT /api/find-phone/capability"]!!.getBoolean("enabled"))
        repo.setFindPhoneEnabled(true)
        assertTrue(repo.findPhoneEnabled())
        assertNull(repo.nextFindPhoneCommand())
        fake.findCommand = fake.ringCommand()
        val command = repo.nextFindPhoneCommand()
        assertEquals("ring", command!!.action)
        assertNull(repo.nextFindPhoneCommand())
        assertEquals("received", fake.bodies["POST /api/find-phone/report"]!!.getString("status"))
        fake.findCommand = fake.ringCommand(signWith = HouseholdCrypto.signingKeys().privateKey)
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.nextFindPhoneCommand() }
        }
        repo.queueFindReport(command.id, "rang")
        fake.failNext("POST /api/find-phone/report", 404, "Gone")
        repo.flushFindReport()
        val reports = count("POST /api/find-phone/report")
        repo.flushFindReport()
        assertEquals(reports, count("POST /api/find-phone/report"))
        repo.setFindPhoneEnabled(false)
        assertFalse(repo.findPhoneEnabled())
        assertNull(repo.nextFindPhoneCommand())
    }

    @Test fun tripsComeWithRouteOutlinesAndFullRoutes() = runBlocking<Unit> {
        joined()
        val owner = fake.ownerAccount
        val trip = JSONObject().put("id", "t1").put("trip_id", "9".repeat(32))
            .put("started_at", 1_000L).put("ended_at", 61_000L).put("device_id", fake.ownerId)
            .put("distance_m", 900.0).put("max_speed_mps", 12.0).put("samples", 30)
            .put("matched", true).put("start_label", "Home").put("end_label", "")
            .put(
                "route",
                JSONArray().put(JSONArray().put(1.0).put(2.0)).put(JSONArray().put(1.1).put(2.1))
            )
        fake.trips = JSONArray().put(trip)
        val (summaries, empty) = repo.tripSummaries(owner, 7)
        assertFalse(empty)
        assertEquals("Home", summaries.trips.single().startLabel)
        assertNull(summaries.trips.single().endLabel)
        assertEquals(listOf(1_000L, 61_000L), summaries.points.map { it.capturedAt })
        fake.tripDetails["t1"] = JSONObject()
            .put(
                "route",
                JSONArray().put(
                    JSONArray().put(1.0).put(2.0)
                ).put(JSONArray().put(1.05).put(2.05)).put(JSONArray().put(1.1).put(2.1))
            )
            .put("times", JSONArray().put(1_000L).put(0L).put(61_000L))
        val full = repo.tripHistory(owner, 7)
        assertEquals(3, full.points.size)
        assertEquals(31_000L, full.points[1].capturedAt)
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.tripSummaries("bad", 7) }
        }
        fake.trips = JSONArray()
        assertTrue(repo.tripSummaries(owner, 7).second)
    }

    @Test fun alertsSkipBlankTextAndAreShortened() = runBlocking<Unit> {
        joined()
        fake.alerts = JSONArray()
            .put(
                JSONObject().put(
                    "id",
                    "1"
                ).put(
                    "account_id",
                    fake.ownerAccount
                ).put("captured_at", 5L).put("text", "x".repeat(400))
            )
            .put(
                JSONObject().put(
                    "id",
                    "2"
                ).put("account_id", fake.ownerAccount).put("captured_at", 6L).put("text", "")
            )
        val alerts = repo.recentAlerts(-5)
        assertEquals(1, alerts.size)
        assertEquals(300, alerts.single().text.length)
        assertTrue(fake.log.contains("GET /api/alerts?since=0"))
    }

    @Test fun sharingChoicesLeaveOutAdminsAndFindTheOwnerViewer() = runBlocking<Unit> {
        joined()
        fake.eligible = JSONArray()
            .put(JSONObject().put("id", fake.ownerAccount).put("name", "Alex").put("role", "admin"))
            .put(JSONObject().put("id", "c".repeat(32)).put("name", "Kim").put("role", "member"))
        assertEquals(listOf("Kim"), repo.sharingChoices().map { it.name })
        assertNull(repo.ownerViewerId())
        fake.ownerViewer = "f".repeat(32)
        assertEquals("f".repeat(32), repo.ownerViewerId())
        fake.ownerViewer = "not-hex"
        assertNull(repo.ownerViewerId())
    }

    @Test fun serverDecidesWhenTheDeviceIsGoneRevokedOrReplaced() = runBlocking<Unit> {
        joined()
        fake.deviceStatus = "revoked"
        assertEquals("revoked", repo.status(member()))
        fake.deviceStatus = "pending"
        fake.replacementRequired = true
        assertEquals("replacement-required", repo.status(member()))
        fake.failNext("GET /api/device", 401, "Unknown device")
        assertEquals("register", repo.status(member()))
        assertEquals("", repo.deviceFingerprint())
    }

    @Test fun revokingOrDiscardingThePhoneDeletesItsKeys() = runBlocking<Unit> {
        joined()
        repo.revokeOwnPhone()
        assertEquals("revoked", fake.deviceStatus)
        assertEquals("", repo.deviceFingerprint())
        assertFalse(NativeHouseholdRepository(context, fake.accounts, client).restoreForService())
        repo.enroll(member(), address)
        repo.discardPendingPhone()
        assertEquals(1, count("DELETE /api/phones/pending"))
        assertEquals("", repo.deviceFingerprint())
    }

    @Test fun backgroundServiceRestoresTheStoredDevice() = runBlocking<Unit> {
        val fresh = NativeHouseholdRepository(context, fake.accounts, client)
        assertFalse(fresh.restoreForService())
        joined()
        val service = NativeHouseholdRepository(context, fake.accounts, client)
        assertTrue(service.restoreForService())
        assertEquals(repo.deviceFingerprint(), service.deviceFingerprint())
        service.publishLocation(fix(), System.currentTimeMillis())
        assertEquals(1, fake.records.size)
    }

    @Test fun permissionReportsAreSentOnlyWhenTheyChange() = runBlocking<Unit> {
        joined()
        repo.reportDevicePermissions()
        repo.reportDevicePermissions()
        assertEquals(1, count("PUT /api/device/permissions"))
        val sent = fake.bodies["PUT /api/device/permissions"]!!
        assertFalse(sent.getBoolean("foreground_location"))
        assertFalse(sent.has("lat"))
        resumeSharing()
        repo.reportDevicePermissions()
        assertEquals(2, count("PUT /api/device/permissions"))
    }

    @Test fun pushTokensAreUploadedOnceAndRemovedOnSignOut() = runBlocking<Unit> {
        val token = "t".repeat(40)
        repo.registerFcmSubscription(token)
        fake.startWithOwner()
        repo.enroll(member(), address)
        repo.registerFcmSubscription(token)
        assertEquals(0, count("PUT /api/push/subscription"))
        repo.verifyPhoneCode("654321")
        repo.registerFcmSubscription("short")
        repo.registerFcmSubscription("t".repeat(30) + " space")
        repo.registerFcmSubscription(token)
        repo.registerFcmSubscription(token)
        assertEquals(1, count("PUT /api/push/subscription"))
        repo.unsubscribeFcm()
        assertEquals(1, count("DELETE /api/push/subscription"))
        repo.registerFcmSubscription(token)
        assertEquals(2, count("PUT /api/push/subscription"))
    }

    @Test fun deviceApiErrorsCarryTheServersMessage() = runBlocking<Unit> {
        joined()
        fake.failNext("GET /api/sharing/audience", 500, "Database unavailable")
        val error = assertThrows(Exception::class.java) { runBlocking { repo.sharingAudience() } }
        assertEquals("Database unavailable", error.message)
        assertNotNull(repo.sharingAudience())
    }
}
