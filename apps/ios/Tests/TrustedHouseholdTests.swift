import CoreLocation
import XCTest

@testable import NaraHem

/// TrustedHousehold and its records against FakeHouseholdServer, with real libsodium encryption.
@MainActor
final class TrustedHouseholdTests: XCTestCase {
    private var fake: FakeHouseholdServer!
    private var api: NaraHemAPI!
    private var household: TrustedHousehold!
    private let address = FakeHouseholdServer.address

    override func setUp() async throws {
        SecureVault.memory = [:]
        for key in ["household-device-v1", "ios-native-session"] { SecureVault.delete(key) }
        fake = FakeHouseholdServer()
        api = NaraHemAPI(configuration: fake.start())
        household = TrustedHousehold(api: api)
    }

    override func tearDown() async throws {
        if let id = household.identity?.id { SecureVault.delete("ios.find.replay." + id) }
        for key in ["household-device-v1", "ios-native-session"] { SecureVault.delete(key) }
        FakeHouseholdServer.active = nil
        SecureVault.memory = nil
    }

    /// Signs in to the fake server.
    @discardableResult
    private func signIn() async throws -> NaraHemAccount {
        try await api.signIn(server: address, identifier: "sam@example.invalid", password: "pw")
    }

    /// Starts the owner's household and lets this iPhone join by emailed code.
    @discardableResult
    private func joined() async throws -> NaraHemAccount {
        fake.startWithOwner()
        let account = try await signIn()
        try await household.enroll(account: account, server: address)
        try await household.verifyPhoneCode("654321")
        return account
    }

    /// Expects `body` to throw an error whose message is `message`.
    private func rejects(
        _ message: String, file: StaticString = #filePath, line: UInt = #line,
        _ body: () async throws -> Void
    ) async {
        do {
            try await body()
            XCTFail("Expected: \(message)", file: file, line: line)
        } catch {
            XCTAssertEqual(error.localizedDescription, message, file: file, line: line)
        }
    }

    /// Expects `body` to throw any error.
    private func fails(
        file: StaticString = #filePath, line: UInt = #line, _ body: () async throws -> Void
    ) async {
        do {
            try await body()
            XCTFail("Expected an error", file: file, line: line)
        } catch {}
    }

    private func fix(_ lat: Double = 51.5, speed: Double = 3) -> LocalLocation {
        LocalLocation(
            CLLocation(
                coordinate: CLLocationCoordinate2D(latitude: lat, longitude: -0.12), altitude: 0,
                horizontalAccuracy: 8, verticalAccuracy: 5, course: 0, speed: speed,
                timestamp: Date()),
            tripId: nil, batteryPct: 80, charging: false)
    }

    func testPhoneJoinsByEmailedCodeAndPinsTheOwnersRoot() async throws {
        fake.startWithOwner()
        let account = try await signIn()
        XCTAssertEqual(account.name, "sam")
        var state = try await household.status(account: account)
        XCTAssertEqual(state, "register")
        try await household.enroll(account: account, server: address)
        state = try await household.status(account: account)
        XCTAssertEqual(state, "email-code")
        let code = try await household.ownCode()
        XCTAssertEqual(code.count, 6)
        try await household.requestPhoneCode()
        await rejects("Enter the six-digit email code") {
            try await self.household.verifyPhoneCode("12")
        }
        try await household.verifyPhoneCode("654321")
        state = try await household.status(account: account)
        XCTAssertEqual(state, "ready")
        XCTAssertEqual(household.identity?.anchor, fake.ownerSigning.pub)
        XCTAssertEqual(fake.count("POST /api/phones/code"), 1)
        let restored = TrustedHousehold(api: api)
        XCTAssertTrue(restored.restore(account: account, server: address))
        XCTAssertFalse(restored.restore(account: account, server: "https://other.test"))
        XCTAssertTrue(TrustedHousehold(api: api).restoreDevice())
    }

    func testEnrollmentNeedsAVerifiedAccountAndHappensOnce() async throws {
        fake.startWithOwner()
        fake.verified = false
        let unverified = try await signIn()
        let state = try await household.status(account: unverified)
        XCTAssertEqual(state, "verify-email")
        await rejects("Administrator approval is required first") {
            try await self.household.enroll(account: unverified, server: self.address)
        }
        fake.verified = true
        let account = try await signIn()
        try await household.enroll(account: account, server: address)
        let first = household.identity?.id
        try await household.enroll(account: account, server: address)
        XCTAssertEqual(household.identity?.id, first)
        XCTAssertEqual(fake.count("POST /api/devices/register"), 1)
    }

    func testFirstAdminDeviceStartsTheHouseholdWithAnEmailCode() async throws {
        fake.role = "admin"
        let account = try await signIn()
        try await household.enroll(account: account, server: address)
        var state = try await household.status(account: account)
        XCTAssertEqual(state, "first-device")
        let pairingCode = try await household.ownCode()
        XCTAssertEqual(pairingCode, "")
        try await household.sendBootstrapCode()
        await rejects("Enter the six-digit email code") {
            try await self.household.bootstrap(code: "abc")
        }
        try await household.bootstrap(code: "123456")
        state = try await household.status(account: account)
        XCTAssertEqual(state, "ready")
        XCTAssertEqual(fake.anchor, household.identity?.signing.pub)
    }

    func testApprovedDeviceWaitsForASignedPairingApproval() async throws {
        fake.startWithOwner()
        let account = try await signIn()
        try await household.enroll(account: account, server: address)
        fake.changes.append(fake.signedChange(fake.currentDevices + [fake.phoneIdentity]))
        fake.deviceStatus = "approved"
        var state = try await household.status(account: account)
        XCTAssertEqual(state, "pairing")
        fake.approvePhone()
        state = try await household.status(account: account)
        XCTAssertEqual(state, "ready")
    }

    func testPairingApprovalForAnotherRegistrationIsRejected() async throws {
        fake.startWithOwner()
        let account = try await signIn()
        try await household.enroll(account: account, server: address)
        let phoneId = fake.phoneIdentity["id"] as! String
        fake.changes.append(
            fake.signedChange(fake.currentDevices + [fake.phoneIdentity]) { body in
                body["pairing_target"] = phoneId
                body["pairing_hash"] = String(repeating: "0", count: 64)
            })
        fake.deviceStatus = "approved"
        await rejects("Signed pairing did not bind this device") {
            _ = try await self.household.status(account: account)
        }
    }

    /// Joins, applies `change` on the server, and expects the next sync to fail with `message`.
    private func rosterRejected(_ message: String, _ change: () -> Void) async throws {
        try await joined()
        change()
        await rejects(message) { _ = try await self.household.syncRoster() }
    }

    func testRosterSignedWithTheWrongKeyIsRejected() async throws {
        try await rosterRejected("Invalid signed membership change") {
            let forged = try! HouseholdCipher.signingKeys()
            fake.changes.append(fake.signedChange(fake.currentDevices, signWith: forged.secret))
        }
    }

    func testRosterFromAnUnknownSignerIsRejected() async throws {
        try await rosterRejected("Untrusted roster signer") {
            fake.changes.append(
                fake.signedChange(fake.currentDevices, signer: String(repeating: "f", count: 32)))
        }
    }

    func testReplacingAnExistingDevicesKeysIsRejected() async throws {
        try await rosterRejected("Device public key substitution rejected") {
            let swapped = fake.currentDevices.map { device -> Wire.Object in
                guard (device["id"] as? String) == fake.ownerId else { return device }
                var changed = device
                changed["box_key"] = try! HouseholdCipher.boxKeys().pub
                return changed
            }
            fake.changes.append(fake.signedChange(swapped))
        }
    }

    func testRosterWithAWrongHashIsRejected() async throws {
        try await rosterRejected("Roster hash mismatch") {
            var change = fake.signedChange(fake.currentDevices)
            change["hash"] = String(repeating: "0", count: 64)
            fake.changes.append(change)
        }
    }

    func testRosterThatSkipsARevisionIsRejected() async throws {
        try await rosterRejected("Roster continuity rejected") {
            fake.changes.append(fake.signedChange(fake.currentDevices) { $0["revision"] = 9 })
        }
    }

    func testRosterRollbackIsRejected() async throws {
        try await rosterRejected("Membership rollback detected") {
            fake.changes.removeLast()
        }
    }

    func testRosterForkAtThePinnedRevisionIsRejected() async throws {
        try await rosterRejected("Pinned membership fork") {
            fake.changes.removeLast()
            fake.changes.append(fake.signedChange(fake.currentDevices + [fake.phoneIdentity]))
        }
    }

    func testChangedHouseholdRootIsRejected() async throws {
        try await rosterRejected("Household root changed") {
            fake.anchor = try! HouseholdCipher.signingKeys().pub
        }
    }

    func testPhoneRemovedFromTheRosterIsNoLongerTrusted() async throws {
        try await rosterRejected("This iPhone is no longer an approved device") {
            fake.changes.append(fake.signedChange([fake.ownerIdentity]))
        }
    }

    func testDuplicateRosterEntriesAreRejected() async throws {
        try await rosterRejected("Unsorted or duplicate roster devices") {
            fake.changes.append(
                fake.signedChange([fake.ownerIdentity]) { body in
                    body["devices"] = [self.fake.ownerIdentity, self.fake.ownerIdentity]
                })
        }
    }

    func testLocationsAreEncryptedOnlyForTheSavedAudience() async throws {
        try await joined()
        let other = String(repeating: "c", count: 32)
        let otherBox = fake.addMember(other)
        fake.audience = [fake.ownerAccount, other]
        fake.eligible = [
            ["id": fake.ownerAccount, "name": "Alex", "role": "admin"],
            ["id": other, "name": "Kim", "role": "member"],
        ]
        fake.ownerViewer = String(repeating: "e", count: 32)
        try await household.refreshAudience()
        XCTAssertEqual(household.audience, [fake.ownerAccount, other])
        XCTAssertEqual(household.choices.map(\.name), ["Kim"])
        await rejects("Refresh and select only current approved viewers") {
            try await self.household.setAudience(["9"])
        }
        try await household.setAudience([fake.ownerViewer!])
        fake.audience = [fake.ownerAccount, other]
        try await household.setSharing(true)
        try await household.publishLocation(fix())
        let body = try Wire.dict(fake.records[0], "body")
        let recipients = try Wire.array(body, "recipients").map { $0["device_id"] as! String }
        XCTAssertEqual(Set(recipients), [household.identity!.id])
        let ownerCopy = try fake.serverCopy(fake.records[0])
        XCTAssertEqual(try Wire.dict(ownerCopy, "data")["battery_pct"] as? Int, 80)
        try await household.setAudience([])
        household.identity?.pinnedAudience = nil
        fake.audience = [fake.ownerAccount, other]
        try await household.publishLocation(fix())
        let wider = try Wire.array(try Wire.dict(fake.records[1], "body"), "recipients")
        XCTAssertEqual(wider.count, 3)
        let boxes = try wider.map { try Wire.string($0, "box") }
        XCTAssertTrue(
            boxes.contains {
                (try? HouseholdCipher.open($0, publicKey: otherBox.pub, secret: otherBox.secret))
                    != nil
            })
        XCTAssertEqual(try Wire.integer(try Wire.dict(fake.records[1], "body"), "sequence"), 2)
    }

    func testNewMembersAreAddedToAPinnedAudienceOnce() async throws {
        try await joined()
        let kim = String(repeating: "c", count: 32)
        let lee = String(repeating: "d", count: 32)
        fake.ownerViewer = fake.ownerAccount
        fake.eligible = [["id": kim, "name": "Kim", "role": "member"]]
        // The first look only learns who is already here.
        let first = try await household.refreshAudience()
        XCTAssertEqual(first, [])
        try await household.setAudience([fake.ownerAccount])
        fake.eligible.append(["id": lee, "name": "Lee", "role": "member"])
        let joinedNames = try await household.refreshAudience()
        XCTAssertEqual(joinedNames, ["Lee"])
        XCTAssertEqual(household.identity?.pinnedAudience, [fake.ownerAccount, lee].sorted())
        // Someone the user removed stays removed, and a member is only announced once.
        let again = try await household.refreshAudience()
        XCTAssertEqual(again, [])
        XCTAssertEqual(household.identity?.pinnedAudience, [fake.ownerAccount, lee].sorted())
    }

    func testJoinedMessageNamesEveryNewMember() {
        XCTAssertEqual(
            joinedMessage(["Kim"]),
            "Kim has joined the household. Your location is being shared with them.")
        XCTAssertEqual(
            joinedMessage(["Kim", "Lee", "Ari"]),
            "Kim, Lee and Ari have joined the household. Your location is being shared with them.")
    }

    func testPausedSharingRefusesLocations() async throws {
        try await joined()
        try await household.setSharing(false)
        XCTAssertFalse(fake.sharing)
        await rejects("Location sharing is paused") {
            try await self.household.publishLocation(self.fix())
        }
        await rejects("Location sharing is paused") {
            try await self.household.publishLocations([self.fix()])
        }
    }

    func testLocationBatchesSignEachFix() async throws {
        try await joined()
        try await household.setSharing(true)
        await rejects("A GPS batch needs an enrolled iPhone") {
            try await self.household.publishLocations([])
        }
        try await household.publishLocations([fix(51.5), fix(51.6), fix(51.7)])
        XCTAssertEqual(fake.records.count, 3)
        XCTAssertEqual(household.identity?.sequence, 3)
    }

    func testPlacesAreSavedEditedAndDeletedAgainstTheManifest() async throws {
        try await joined()
        fake.members = [["id": fake.ownerAccount, "username": "alex"]]
        try await household.savePlace(
            name: "Home", lat: 51.5, lon: -0.12, radius: 100, existing: nil,
            alerts: [fake.ownerAccount: ["arrival": true]])
        XCTAssertEqual(fake.headers["POST /api/records"]?["X-Places-State"], "places-token")
        let home = try XCTUnwrap(household.places.first)
        XCTAssertEqual(home.name, "Home")
        await rejects("Place overlaps Home") {
            try await self.household.savePlace(
                name: "School", lat: 51.5005, lon: -0.12, radius: 100, existing: nil)
        }
        try await household.savePlace(
            name: "Home sweet home", lat: 51.5, lon: -0.12, radius: 100, existing: home)
        XCTAssertEqual(household.places.first?.name, "Home sweet home")
        var stale = household.places[0]
        stale.recordId = "old"
        await rejects("Place changed; refresh before editing") {
            try await self.household.savePlace(
                name: "Home", lat: 51.6, lon: -0.12, radius: 100, existing: stale)
        }
        try await household.deletePlace(household.places[0])
        XCTAssertTrue(household.places.isEmpty)
        await rejects("Enter a place name, coordinates and radius (1–10,000 m)") {
            try await self.household.savePlace(
                name: " ", lat: 0, lon: 0, radius: 100, existing: nil)
        }
    }

    func testSnapshotCombinesMembersProfilesAndLatestLocations() async throws {
        try await joined()
        let owner = fake.ownerAccount
        fake.members = [["id": owner, "username": "alex"], ["id": "x"], ["name": "no id"]]
        fake.view = [
            (
                "profile:\(owner)",
                [
                    "id": "p", "kind": "profile", "operation": "upsert", "entity_id": owner,
                    "data": ["name": "Old name", "photo": "data:image/jpeg;base64,AA=="],
                ]
            ),
            (
                "location:old",
                [
                    "id": "l1", "kind": "location", "operation": "upsert", "entity_id": owner,
                    "captured_at": 1000, "data": ["lat": 1.0, "lon": 2.0],
                ]
            ),
            (
                "location:new",
                [
                    "id": "l2", "kind": "location", "operation": "upsert", "entity_id": owner,
                    "captured_at": 2000, "still_since": 1500, "last_contact": 1900,
                    "data": [
                        "lat": 1.5, "lon": 2.5, "accuracy": 9, "speed_mps": 4, "battery_pct": 55,
                        "charging": true, "trip_id": String(repeating: "d", count: 32),
                    ] as Wire.Object,
                ]
            ),
            (
                "note",
                [
                    "id": "n", "kind": "note", "operation": "upsert", "entity_id": "z",
                    "data": Wire.Object(),
                ]
            ),
        ]
        let snapshot = try await household.snapshot()
        XCTAssertEqual(snapshot.members.count, 2)
        let alex = snapshot.members[0]
        // The server's username wins over the name saved with the profile photo.
        XCTAssertEqual(alex.name, "alex")
        XCTAssertEqual(alex.photo, "data:image/jpeg;base64,AA==")
        XCTAssertEqual(alex.lat, 1.5)
        XCTAssertEqual(alex.battery, 55)
        XCTAssertEqual(alex.charging, true)
        XCTAssertEqual(alex.stillSince, 1500)
        XCTAssertEqual(snapshot.members[1].name, "Member")
        fake.view = [
            (
                "place:bad",
                [
                    "id": "q", "kind": "place", "operation": "upsert", "entity_id": "bad",
                    "data": ["name": "Moon", "lat": 95.0, "lon": 0.0, "radius": 10.0]
                        as Wire.Object,
                ]
            )
        ]
        await rejects("Invalid encrypted place geometry") {
            _ = try await self.household.snapshot()
        }
    }

    func testProfilePhotoReplacesTheCurrentProfile() async throws {
        try await joined()
        fake.profileRecord = String(repeating: "e", count: 32)
        try await household.savePhoto(jpeg: Data([0xFF, 0xD8, 0xFF]), name: "Sam")
        let body = try Wire.dict(fake.records[0], "body")
        XCTAssertEqual(body["replaces"] as? String, fake.profileRecord)
        XCTAssertEqual(
            try Wire.dict(try fake.serverCopy(fake.records[0]), "data")["name"] as? String, "Sam")
        await rejects("Crop or reduce photo size before sharing") {
            try await self.household.savePhoto(jpeg: Data(count: 20_000), name: "Sam")
        }
    }

    func testTripSummariesAndRoutes() async throws {
        try await joined()
        try await household.setSharing(true)
        var trip = HouseholdTrip(
            id: "t1", accountId: fake.ownerAccount, deviceId: fake.ownerId, startedAt: 1000,
            endedAt: 61000, distance: 900, maxSpeed: 12, samples: 30, tripId: Wire.freshId())
        trip.originName = "Home"
        trip.start = [1, 2]
        trip.end = [1.1, 2.1]
        trip.preview = [[1, 2], [1.1, 2.1]]
        try await household.publishTrip(trip)
        XCTAssertEqual(try Wire.string(try Wire.dict(fake.records[0], "body"), "kind"), "event")
        fake.trips = [
            [
                "id": "t1", "device_id": fake.ownerId, "started_at": 1000, "ended_at": 61000,
                "distance_m": 900, "max_speed_mps": 12, "samples": 30, "matched": true,
                "start_label": "Home", "end_label": "", "preview": [[1.0, 2.0], [1.1, 2.1]],
            ],
            ["id": "broken"],
        ]
        let (summaries, points, processing, roads) = try await household.trips(
            accountId: fake.ownerAccount, days: 30)
        XCTAssertEqual(summaries.map(\.id), ["t1"])
        XCTAssertEqual(summaries[0].startLabel, "Home")
        XCTAssertNil(summaries[0].endLabel)
        XCTAssertTrue(points.isEmpty)
        XCTAssertEqual(processing, true)
        XCTAssertEqual(roads, false)
        fake.tripDetails["t1"] = [
            "route": [[1.0, 2.0], [1.05, 2.05], [1.1, 2.1]], "times": [1000, 31000, 61000],
        ]
        let route = try await household.tripRoute(summaries[0])
        XCTAssertEqual(route.map(\.capturedAt), [1000, 31000, 61000])
        fake.tripDetails["t1"] = ["route": [[1.0, 2.0], [1.1, 2.1]]]
        let lastTime = try await household.tripRoute(summaries[0]).last?.capturedAt
        XCTAssertEqual(lastTime, 61000)
        fake.tripDetails["t1"] = [:]
        let noRoute = try await household.tripRoute(summaries[0]).isEmpty
        XCTAssertTrue(noRoute)
    }

    func testAlertsSkipBlankTextAndAreShortened() async throws {
        try await joined()
        fake.alerts = [
            [
                "id": "1", "account_id": fake.ownerAccount, "captured_at": 5,
                "text": String(repeating: "x", count: 400),
            ],
            ["id": "2", "account_id": fake.ownerAccount, "captured_at": 6, "text": ""],
        ]
        let alerts = try await household.recentAlerts(since: -5)
        XCTAssertEqual(alerts.count, 1)
        XCTAssertEqual(alerts[0].text.count, 300)
        XCTAssertTrue(fake.log.contains("GET /api/alerts?since=0"))
    }

    func testFindMyPhoneAcceptsOnlyOwnerSignedCommandsOnce() async throws {
        try await joined()
        var found = try await household.findCommand()
        XCTAssertNil(found)
        try await household.setFindPhone(true)
        XCTAssertTrue(household.findPhoneEnabled)
        found = try await household.findCommand()
        XCTAssertNil(found)
        fake.findCommand = fake.ringCommand()
        found = try await household.findCommand()
        let command = try XCTUnwrap(found)
        XCTAssertEqual(command.1, "ring")
        found = try await household.findCommand()
        XCTAssertNil(found)
        await household.reportFind(command.0, state: "ringing")
        XCTAssertEqual(fake.bodies["POST /api/find-phone/report"]?["status"] as? String, "ringing")
        fake.findCommand = fake.ringCommand(signWith: try HouseholdCipher.signingKeys().secret)
        await rejects("Find-phone command is not signed by the approved household owner") {
            _ = try await self.household.findCommand()
        }
        var expired = fake.ringCommand()
        var body = try Wire.dict(expired, "body")
        body["expires_at"] = Wire.timestamp() - 1
        expired["body"] = body
        fake.findCommand = expired
        await rejects("Invalid find-phone command") { _ = try await self.household.findCommand() }
        try await household.setFindPhone(false)
        XCTAssertFalse(household.findPhoneEnabled)
    }

    func testPermissionsAndPushTokensAreReported() async throws {
        try await joined()
        try await household.reportDevicePermissions(
            foreground: true, background: false, alarm: true, notifications: true, sharing: true)
        let sent = try XCTUnwrap(fake.bodies["PUT /api/device/permissions"])
        XCTAssertEqual(sent["dnd_access"] as? Bool, false)
        XCTAssertNil(sent["lat"])
        try await household.subscribePush(token: "abc", environment: "development")
        XCTAssertEqual(fake.bodies["PUT /api/push/subscription"]?["provider"] as? String, "apns")
        try await household.unsubscribePush()
        XCTAssertEqual(fake.count("DELETE /api/push/subscription"), 1)
    }

    func testServerDecidesWhenTheDeviceIsGoneRevokedOrReplaced() async throws {
        let account = try await joined()
        fake.deviceStatus = "revoked"
        var state = try await household.status(account: account)
        XCTAssertEqual(state, "revoked")
        fake.deviceStatus = "pending"
        fake.replacementRequired = true
        state = try await household.status(account: account)
        XCTAssertEqual(state, "replacement-required")
        fake.failNext("GET /api/device", 401, "Unknown device")
        state = try await household.status(account: account)
        XCTAssertEqual(state, "register")
        XCTAssertNil(household.identity)
        await rejects("Approve this iPhone first") {
            _ = try await self.household.device("/api/device")
        }
    }

    func testRevokingOrDiscardingThePhoneDeletesItsKeys() async throws {
        let account = try await joined()
        try await household.revokeThisPhone()
        XCTAssertEqual(fake.deviceStatus, "revoked")
        XCTAssertNil(household.identity)
        XCTAssertFalse(TrustedHousehold(api: api).restoreDevice())
        fake.deviceStatus = "pending"
        try await household.enroll(account: account, server: address)
        await household.discardPendingPhone()
        XCTAssertEqual(fake.count("DELETE /api/phones/pending"), 1)
        XCTAssertNil(household.identity)
    }

    func testErrorsCarryTheServersMessage() async throws {
        try await joined()
        fake.failNext("GET /api/sharing/audience", 500, "Database unavailable")
        await rejects("Database unavailable") { try await self.household.refreshAudience() }
        await fails {
            _ = try await self.household.tripRoute(
                HouseholdTrip(
                    id: "missing", accountId: "", deviceId: "", startedAt: 0, endedAt: 0,
                    distance: 0, maxSpeed: 0, samples: 0, tripId: nil))
        }
    }
}
