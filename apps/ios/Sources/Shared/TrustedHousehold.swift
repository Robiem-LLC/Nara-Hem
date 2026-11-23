import Foundation

/// This iPhone as a household device: its keys, the verified signed roster, and the device API
/// calls that use them.
@MainActor
final class TrustedHousehold {
    let api: NaraHemAPI
    var identity: TrustedIdentity?
    var currentRoster: Wire.Object?
    var rosters: [Int: Wire.Object] = [:]
    var sharing = false
    var findPhoneEnabled = false
    var members: [HouseholdMember] = []
    var places: [SavedPlace] = []
    var audience: Set<String> = []
    var choices: [AudienceChoice] = []
    var ownerViewerId: String?

    /// Set in the notification extension, which reads the identity but must never save it over the
    /// app's newer state.
    var readOnly = false

    /// Creates a household on the given API.
    init(api: NaraHemAPI) { self.api = api }

    /// Stores the identity in the keychain. Does nothing when readOnly.
    func save() throws {
        guard let identity, !readOnly else { return }
        let stored = try JSONEncoder().encode(identity)
        guard SecureVault.put(stored, key: "household-device-v1") else {
            throw NaraHemProtocolError.rejected(
                "Unable to protect this iPhone identity in Keychain")
        }
    }

    /// Loads the stored identity if it belongs to this account and server.
    func restore(account: NaraHemAccount, server: String) -> Bool {
        guard let data = SecureVault.get("household-device-v1"),
            let record = try? JSONDecoder().decode(TrustedIdentity.self, from: data),
            record.accountId == account.id, record.household == account.household,
            record.server == (try? NaraHemAPI.serverURL(server).absoluteString)
        else {
            return false
        }
        identity = record
        // Older versions stored this in the app-only keychain group; move it so the notification
        // extension can read it.
        SecureVault.share("household-device-v1")
        return true
    }

    /// Loads the stored device identity without an account session, for the notification extension.
    func restoreDevice() -> Bool {
        guard let data = SecureVault.get("household-device-v1"),
            let record = try? JSONDecoder().decode(TrustedIdentity.self, from: data),
            !record.credential.isEmpty
        else { return false }
        identity = record
        readOnly = true
        return true
    }

    /// Generates keys and registers this device with the server.
    func enroll(account: NaraHemAccount, server: String) async throws {
        let origin = try NaraHemAPI.serverURL(server).absoluteString
        if restore(account: account, server: origin) { return }
        // An account registered in the app isn't confirmed yet; the code that approves this
        // phone confirms it, so it may register.
        let signing = try HouseholdCipher.signingKeys()
        let box = try HouseholdCipher.boxKeys()
        var fresh = TrustedIdentity(
            server: origin, id: Wire.freshId(), accountId: account.id,
            household: account.household, signing: signing, box: box, credential: "")
        let response = try await api.accountRequest(
            "/api/devices/register",
            payload: [
                "id": fresh.id, "name": "iPhone", "signing_key": signing.pub,
                "box_key": box.pub, "platform": "ios",
                "signature": try HouseholdCipher.sign(fresh.registration, key: signing.secret),
            ],
            method: "POST")
        fresh.credential = try Wire.string(response, "credential")
        identity = fresh
        try save()
    }

    /// Sends a request authenticated as this device.
    func device(
        _ path: String, payload: Wire.Object? = nil, method: String = "GET",
        headers: [String: String] = [:]
    ) async throws -> Wire.Object {
        guard let identity else {
            throw NaraHemProtocolError.rejected("Approve this iPhone first")
        }
        return try await api.deviceRequest(
            path, credential: identity.credential, payload: payload, method: method,
            headers: headers)
    }

    /// Uploads the APNs token. Only allowed once the device is approved.
    func subscribePush(token: String, environment: String) async throws {
        _ = try await device(
            "/api/push/subscription",
            payload: [
                "provider": "apns", "token": token, "environment": environment,
            ], method: "PUT")
    }

    /// Removes the APNs token from the server.
    func unsubscribePush() async throws {
        _ = try await device("/api/push/subscription", method: "DELETE")
    }

    /// Determines this device's setup state from the server and the signed roster.
    func status(account: NaraHemAccount) async throws -> String {
        guard identity != nil else { return "register" }
        let device: Wire.Object
        do { device = try await self.device("/api/device") } catch NaraHemProtocolError.http(
            let status, _) where status == 401
        {
            clearDevice()
            return "register"
        }
        let state = try Wire.string(device, "status")
        if state == "revoked" { return "revoked" }
        if var v = identity {
            v.sequence = max(v.sequence, (try? Wire.integer(device, "sequence")) ?? 0)
            identity = v
            try save()
        }
        sharing = (device["sharing"] as? Bool) ?? true
        if state != "approved" {
            let household = try await api.accountRequest("/api/household")
            if (device["replacement_required"] as? Bool) == true { return "replacement-required" }
            if ((try? Wire.integer(household, "revision")) ?? 0) == 0 && account.role == "admin" {
                return "first-device"
            }
            return "email-code"
        }
        do { _ = try await syncRoster(); return "ready" } catch NaraHemProtocolError.rejected(
            let message) where message == "Waiting for signed device approval"
        { return "pairing" }
    }

    /// Returns this device's six-digit pairing code.
    func ownCode() async throws -> String {
        guard let identity else { throw NaraHemProtocolError.rejected("Register iPhone first") }
        let root: String
        if identity.anchor.isEmpty {
            root = (try? Wire.string(try await device("/api/roster"), "anchor")) ?? ""
        } else {
            root = identity.anchor
        }
        if root.isEmpty { return "" }
        return try Wire.pairingCode(registration: identity.registration, anchor: root)
    }

    /// Requests the email with this phone's approval code.
    func requestPhoneCode() async throws {
        guard let id = identity?.id else {
            throw NaraHemProtocolError.rejected("Register this phone first")
        }
        _ = try await api.accountRequest(
            "/api/phones/code",
            payload: ["device_id": id], method: "POST")
    }

    /// Submits the approval code and syncs the roster that now includes this phone.
    func verifyPhoneCode(_ code: String) async throws {
        guard code.count == 6 && code.allSatisfy(\.isNumber),
            let id = identity?.id
        else {
            throw NaraHemProtocolError.rejected("Enter the six-digit email code")
        }
        _ = try await api.accountRequest(
            "/api/phones/verify",
            payload: ["device_id": id, "code": code], method: "POST")
        _ = try await syncRoster()
    }

    /// Cancels an unfinished registration and deletes the local identity.
    func discardPendingPhone() async {
        if let id = identity?.id {
            _ = try? await api.accountRequest(
                "/api/phones/pending",
                payload: ["device_id": id], method: "DELETE")
        }
        clearDevice()
    }

    /// Revokes this phone on the server and deletes the local identity.
    func revokeThisPhone() async throws {
        _ = try await device("/api/phones/self-revoke", payload: [:], method: "POST")
        clearDevice()
    }

    /// Deletes the local identity.
    private func clearDevice() {
        SecureVault.delete("household-device-v1")
        identity = nil
        currentRoster = nil
        rosters.removeAll()
    }

    /// Requests the first-device email code.
    func sendBootstrapCode() async throws {
        guard let identity else { throw NaraHemProtocolError.rejected("Register iPhone first") }
        _ = try await api.accountRequest(
            "/api/device-bootstrap/email/request",
            payload: ["device_id": identity.id], method: "POST")
    }

    /// Signs the first roster with this device as the household root, verified by the emailed code.
    func bootstrap(code: String) async throws {
        guard code.count == 6, code.allSatisfy(\.isNumber), var v = identity else {
            throw NaraHemProtocolError.rejected("Enter the six-digit email code")
        }
        let body: Wire.Object = [
            "domain": "narahem.roster.v1",
            "household": v.household, "revision": 1, "previous": "",
            "signer": v.id, "devices": [v.record], "issued_at": Wire.timestamp(),
        ]
        _ = try await device(
            "/api/roster",
            payload: [
                "body": body,
                "signature": try HouseholdCipher.sign(body, key: v.signing.secret),
                "bootstrap_email_code": code,
            ], method: "POST")
        v.anchor = v.signing.pub
        identity = v
        try save()
        _ = try await syncRoster()
    }

    /// Fetches and verifies every new signed roster revision, rejecting forks, rollbacks and key
    /// substitutions. Returns the current roster.
    func syncRoster() async throws -> Wire.Object {
        guard var v = identity else {
            throw NaraHemProtocolError.rejected("Register this iPhone first")
        }
        let onboarding = v.anchor.isEmpty
        var candidateAnchor = v.anchor
        var verifiedPairing = false
        var after = 0
        var previousHash = ""
        var previousBody: Wire.Object?
        var revisions: [Int: Wire.Object] = [:]
        var lastRevision = 0
        var remoteRevision = 0
        repeat {
            let page = try await device("/api/roster?after=\(after)")
            if candidateAnchor.isEmpty { candidateAnchor = try Wire.string(page, "anchor") }
            guard try Wire.string(page, "anchor") == candidateAnchor,
                try Wire.string(page, "household") == v.household,
                (try? Wire.bytes(candidateAnchor, length: 32)) != nil
            else {
                throw NaraHemProtocolError.rejected("Household root changed")
            }
            remoteRevision = try Wire.integer(page, "revision")
            let changes = try Wire.array(page, "changes")
            if changes.isEmpty && after < remoteRevision {
                throw NaraHemProtocolError.rejected("Incomplete signed roster")
            }
            for change in changes {
                let body = try Wire.dict(change, "body")
                let revision = try Wire.integer(body, "revision")
                let devices = try Wire.array(body, "devices")
                guard try Wire.string(body, "domain") == "narahem.roster.v1",
                    try Wire.string(body, "household") == v.household, revision == lastRevision + 1,
                    try Wire.string(body, "previous") == previousHash
                else {
                    throw NaraHemProtocolError.rejected("Roster continuity rejected")
                }
                let ids = try devices.map { try Wire.string($0, "id") }
                guard ids == Array(Set(ids)).sorted() else {
                    throw NaraHemProtocolError.rejected("Unsorted or duplicate roster devices")
                }
                let signer = try rosterSigner(
                    for: body, devices: devices, after: previousBody, anchor: candidateAnchor)
                let digest = try verifiedDigest(of: change, body: body, signer: signer)
                if onboarding && (body["pairing_target"] as? String) == v.id {
                    guard previousBody != nil,
                        (body["pairing_hash"] as? String)
                            == Wire.hash(try Wire.canonical(v.registration)),
                        let matched = devices.first(where: { ($0["id"] as? String) == v.id }),
                        try Wire.canonical(matched) == Wire.canonical(v.record)
                    else {
                        throw NaraHemProtocolError.rejected(
                            "Signed pairing did not bind this device")
                    }
                    verifiedPairing = true
                }
                if revision == v.revision && v.revision > 0 && digest != v.chainHash {
                    throw NaraHemProtocolError.rejected("Pinned membership fork")
                }
                previousHash = digest
                previousBody = body
                revisions[revision] = body
                lastRevision = revision
            }
            after = lastRevision
            if lastRevision > 10000 {
                throw NaraHemProtocolError.rejected("Roster history exceeds safety limit")
            }
        } while after < remoteRevision
        guard
            lastRevision >= v.revision
                && (lastRevision != v.revision || previousHash == v.chainHash),
            let last = previousBody
        else { throw NaraHemProtocolError.rejected("Membership rollback detected") }
        guard try Wire.array(last, "devices").contains(where: { ($0["id"] as? String) == v.id })
        else {
            throw NaraHemProtocolError.rejected("This iPhone is no longer an approved device")
        }
        if onboarding && !verifiedPairing {
            throw NaraHemProtocolError.rejected("Waiting for signed device approval")
        }
        if onboarding { v.anchor = candidateAnchor }
        v.revision = lastRevision
        v.chainHash = previousHash
        identity = v
        currentRoster = last
        rosters = revisions
        try save()
        return last
    }

    /// Returns the device that signed a roster change. It must be in the previous roster, and no
    /// existing device's keys may change. The first roster may only contain the household root
    /// device.
    private func rosterSigner(
        for body: Wire.Object, devices: [Wire.Object], after previousBody: Wire.Object?,
        anchor candidateAnchor: String
    ) throws -> Wire.Object {
        guard let old = previousBody else {
            guard devices.count == 1, let first = devices.first else {
                throw NaraHemProtocolError.rejected("Invalid genesis roster")
            }
            guard first["signing_key"] as? String == candidateAnchor else {
                throw NaraHemProtocolError.rejected("Genesis trust anchor mismatch")
            }
            return first
        }
        guard
            let trusted = try Wire.array(old, "devices").first(where: {
                ($0["id"] as? String) == (body["signer"] as? String)
            })
        else { throw NaraHemProtocolError.rejected("Untrusted roster signer") }
        for prior in try Wire.array(old, "devices") {
            if let match = devices.first(where: {
                ($0["id"] as? String) == (prior["id"] as? String)
            }),
                try Wire.canonical(match) != Wire.canonical(prior)
            {
                throw NaraHemProtocolError.rejected("Device public key substitution rejected")
            }
        }
        return trusted
    }

    /// Verifies a roster change's signature and returns its hash, which the next change must
    /// reference.
    private func verifiedDigest(
        of change: Wire.Object, body: Wire.Object, signer: Wire.Object
    ) throws -> String {
        guard (signer["id"] as? String) == (body["signer"] as? String),
            HouseholdCipher.verify(
                body, signature: try Wire.string(change, "signature"),
                key: try Wire.string(signer, "signing_key"))
        else {
            throw NaraHemProtocolError.rejected("Invalid signed membership change")
        }
        let digest = Wire.hash(
            try Wire.canonical([
                "body": body, "signature": Wire.string(change, "signature"),
            ]))
        guard digest == (try Wire.string(change, "hash")) else {
            throw NaraHemProtocolError.rejected("Roster hash mismatch")
        }
        return digest
    }
}
