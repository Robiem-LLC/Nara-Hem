import Foundation

@testable import NaraHem

/// An in-memory household server and owner device for testing TrustedHousehold and NaraHemAPI.
/// Requests reach it through FakeServerProtocol instead of the network. It signs roster changes the
/// way the owner's trusted device would.
final class FakeHouseholdServer {
    static let address = "https://household.test"
    let household = "0123456789abcdef0123456789abcdef"
    let ownerAccount = String(repeating: "a", count: 32)
    let phoneAccount = String(repeating: "b", count: 32)
    let ownerId = Wire.freshId()
    let ownerSigning = try! HouseholdCipher.signingKeys()
    let ownerBox = try! HouseholdCipher.boxKeys()
    let serverBox = try! HouseholdCipher.boxKeys()
    let credential = "device-credential"
    var accessToken = "access-1"
    var refreshToken = "refresh-1"
    var role = "member"
    var verified = true

    /// Signed roster changes, oldest first: each has body, signature and hash.
    var changes: [Wire.Object] = []
    var anchor = ""
    var registration: Wire.Object?
    var deviceStatus = "pending"
    var sharing = true
    var sequence = 0
    var replacementRequired = false
    var audience: [String] = []
    var eligible: [Wire.Object] = []
    var ownerViewer: String?
    var members: [Wire.Object] = []
    var findCommand: Wire.Object?
    var trips: [Wire.Object] = []
    var tripDetails: [String: Wire.Object] = [:]
    var alerts: [Wire.Object] = []
    var profileRecord: String?

    /// Records the server accepted, as sent.
    var records: [Wire.Object] = []

    /// Decrypted record state shown in /api/view, keyed by kind and entity ID, in order.
    var view: [(String, Wire.Object)] = []

    /// Every request as "METHOD /path?query", and the last body and headers per "METHOD /path".
    var log: [String] = []
    var bodies: [String: Wire.Object] = [:]
    var headers: [String: [String: String]] = [:]

    /// One-off failures keyed by "METHOD /path": the status and detail of the next reply.
    var failures: [String: [(Int, String)]] = [:]
    private let lock = NSLock()

    /// The server answering requests, set by start().
    static var active: FakeHouseholdServer?

    /// The owner's roster entry.
    var ownerIdentity: Wire.Object {
        [
            "id": ownerId, "account_id": ownerAccount, "signing_key": ownerSigning.pub,
            "box_key": ownerBox.pub,
        ]
    }

    /// The phone's roster entry, from its registration.
    var phoneIdentity: Wire.Object {
        let r = registration ?? [:]
        return [
            "id": r["id"] ?? "", "account_id": r["account_id"] ?? "",
            "signing_key": r["signing_key"] ?? "", "box_key": r["box_key"] ?? "",
        ]
    }

    /// The hash the owner signs to approve this exact phone registration.
    var pairingHash: String { Wire.hash((try? Wire.canonical(registration ?? [:])) ?? "") }

    /// The devices in the latest roster.
    var currentDevices: [Wire.Object] {
        guard let last = changes.last, let body = last["body"] as? Wire.Object else { return [] }
        return (body["devices"] as? [Wire.Object]) ?? []
    }

    /// Starts answering requests and returns a session configuration that sends them here.
    func start() -> URLSessionConfiguration {
        Self.active = self
        let configuration = NaraHemAPI.configuration()
        configuration.protocolClasses = [FakeServerProtocol.self]
        return configuration
    }

    /// Makes the next request to `route` fail with `status` and `detail`.
    func failNext(_ route: String, _ status: Int, _ detail: String = "Failed") {
        failures[route, default: []].append((status, detail))
    }

    /// Returns how many requests were made to "METHOD /path" (ignoring the query).
    func count(_ route: String) -> Int {
        log.filter { $0.components(separatedBy: "?")[0] == route }.count
    }

    /// Builds a signed roster change after the current one.
    func signedChange(
        _ devices: [Wire.Object], signer: String? = nil, signWith: String? = nil,
        edit: (inout Wire.Object) -> Void = { _ in }
    ) -> Wire.Object {
        var body: Wire.Object = [
            "domain": "narahem.roster.v1", "household": household,
            "revision": changes.count + 1,
            "previous": (changes.last?["hash"] as? String) ?? "",
            "signer": signer ?? ownerId,
            "devices": devices.sorted { ($0["id"] as! String) < ($1["id"] as! String) },
            "issued_at": Wire.timestamp(),
        ]
        edit(&body)
        let signature = try! HouseholdCipher.sign(body, key: signWith ?? ownerSigning.secret)
        let hash = Wire.hash(try! Wire.canonical(["body": body, "signature": signature]))
        return ["body": body, "signature": signature, "hash": hash]
    }

    /// Starts the household with the owner device as its only member and root.
    func startWithOwner() {
        changes.append(signedChange([ownerIdentity]))
        anchor = ownerSigning.pub
    }

    /// The owner signs a roster that adds the registered phone, as approving it would.
    func approvePhone() {
        let phoneId = phoneIdentity["id"] as! String
        let others = currentDevices.filter { ($0["id"] as? String) != phoneId }
        changes.append(
            signedChange(others + [phoneIdentity]) { body in
                body["pairing_target"] = phoneId
                body["pairing_hash"] = self.pairingHash
            })
        deviceStatus = "approved"
    }

    /// The owner signs a roster that adds another member's device. Returns its box keys.
    @discardableResult
    func addMember(_ accountId: String) -> HouseholdCipher.KeyPair {
        let box = try! HouseholdCipher.boxKeys()
        let device: Wire.Object = [
            "id": Wire.freshId(), "account_id": accountId,
            "signing_key": try! HouseholdCipher.signingKeys().pub, "box_key": box.pub,
        ]
        changes.append(signedChange(currentDevices + [device]))
        return box
    }

    /// A Find My Phone command for the phone, signed by the owner device.
    func ringCommand(_ action: String = "ring", signWith: String? = nil) -> Wire.Object {
        let now = Wire.timestamp()
        let body: Wire.Object = [
            "domain": "narahem.find-phone.v1", "household": household,
            "target": phoneIdentity["id"] ?? "", "issuer": ownerId, "id": Wire.freshId(),
            "action": action, "issued_at": now, "expires_at": now + 60,
        ]
        return [
            "body": body,
            "signature": try! HouseholdCipher.sign(body, key: signWith ?? ownerSigning.secret),
        ]
    }

    /// Decrypts a record's server copy with the server key.
    func serverCopy(_ record: Wire.Object) throws -> Wire.Object {
        let body = try Wire.dict(record, "body")
        return try HouseholdCipher.open(
            try Wire.string(body, "server_box"), publicKey: serverBox.pub, secret: serverBox.secret)
    }

    /// Answers one request with a status and JSON body.
    func answer(_ request: URLRequest) -> (Int, Data) {
        lock.lock()
        defer { lock.unlock() }
        let url = request.url!
        let method = request.httpMethod ?? "GET"
        let route = method + " " + url.path
        log.append(route + (url.query.map { "?" + $0 } ?? ""))
        let payload = Self.body(of: request)
        bodies[route] = payload
        headers[route] = request.allHTTPHeaderFields ?? [:]
        let bearer = (request.value(forHTTPHeaderField: "Authorization") ?? "")
            .replacingOccurrences(of: "Bearer ", with: "")
        if var queued = failures[route], !queued.isEmpty {
            let (status, detail) = queued.removeFirst()
            failures[route] = queued
            return Self.reply(["detail": detail], status: status)
        }
        do {
            return try respond(route, url: url, payload: payload, bearer: bearer)
        } catch {
            return Self.reply(["detail": "\(error)"], status: 400)
        }
    }

    /// Routes a request. Account routes need the access token, device routes the credential.
    private func respond(
        _ route: String, url: URL, payload: Wire.Object, bearer: String
    ) throws -> (Int, Data) {
        let account = { () -> (Int, Data)? in
            bearer == self.accessToken ? nil : Self.reply(["detail": "Sign in"], status: 401)
        }
        let device = { () -> (Int, Data)? in
            bearer == self.credential ? nil : Self.reply(["detail": "Unknown device"], status: 401)
        }
        switch route {
        case "POST /api/login":
            return Self.reply(["access_token": accessToken, "refresh_token": refreshToken])
        case "POST /api/native/session/refresh":
            guard (payload["refresh_token"] as? String) == refreshToken else {
                return Self.reply(["detail": "Expired"], status: 401)
            }
            accessToken = "access-" + Wire.freshId()
            refreshToken = "refresh-" + Wire.freshId()
            return Self.reply(["access_token": accessToken, "refresh_token": refreshToken])
        case "POST /api/native/session/revoke", "POST /api/logout":
            return Self.reply(["signed_out": true])
        case "GET /api/session":
            if let denied = account() { return denied }
            return Self.reply([
                "id": phoneAccount, "username": "sam", "role": role, "verified": verified,
            ])
        case "GET /api/household":
            if let denied = account() { return denied }
            return Self.reply(["id": household, "revision": changes.count])
        case "GET /api/household/members":
            if let denied = account() { return denied }
            return Self.reply(["members": members])
        case "PUT /api/account/username":
            if let denied = account() { return denied }
            return Self.reply(["username": payload["username"] ?? ""])
        case "POST /api/enrollment/request":
            return Self.reply(["message": "Check your email."])
        case "POST /api/enrollment/verify":
            return Self.reply(["verified": true])
        case "POST /api/invitation-requests":
            return Self.reply(["message": "Request sent."])
        case "POST /api/devices/register":
            if let denied = account() { return denied }
            let reg: Wire.Object = [
                "domain": "narahem.device.v1", "household": household,
                "id": try Wire.string(payload, "id"), "account_id": phoneAccount,
                "signing_key": try Wire.string(payload, "signing_key"),
                "box_key": try Wire.string(payload, "box_key"), "platform": "ios",
            ]
            guard
                HouseholdCipher.verify(
                    reg, signature: try Wire.string(payload, "signature"),
                    key: try Wire.string(payload, "signing_key"))
            else { return Self.reply(["detail": "Bad signature"], status: 400) }
            registration = reg
            return Self.reply(["credential": credential], status: 201)
        case "POST /api/phones/code", "POST /api/device-bootstrap/email/request":
            if let denied = account() { return denied }
            return Self.reply(["sent": true])
        case "POST /api/phones/verify":
            if let denied = account() { return denied }
            guard (payload["code"] as? String) == "654321" else {
                return Self.reply(["detail": "Code rejected. Try again."], status: 403)
            }
            approvePhone()
            return Self.reply(["approved": true])
        case "DELETE /api/phones/pending":
            if let denied = account() { return denied }
            return Self.reply(["discarded": true])
        default:
            break
        }
        if let denied = device() { return denied }
        if deviceStatus == "revoked" && route != "GET /api/device" {
            return Self.reply(["detail": "Revoked"], status: 403)
        }
        switch route {
        case "GET /api/device":
            return Self.reply([
                "status": deviceStatus, "sequence": sequence, "sharing": sharing,
                "trip_processing_key": serverBox.pub, "replacement_required": replacementRequired,
            ])
        case "GET /api/roster":
            let after =
                Int(
                    URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?
                        .first { $0.name == "after" }?.value ?? "0") ?? 0
            return Self.reply([
                "anchor": anchor, "household": household, "revision": changes.count,
                "changes": Array(changes.dropFirst(after).prefix(2)),
            ])
        case "POST /api/roster":
            guard (payload["bootstrap_email_code"] as? String) == "123456" else {
                return Self.reply(["detail": "Wrong code"], status: 400)
            }
            let body = try Wire.dict(payload, "body")
            let signature = try Wire.string(payload, "signature")
            changes.append([
                "body": body, "signature": signature,
                "hash": Wire.hash(try Wire.canonical(["body": body, "signature": signature])),
            ])
            anchor = try Wire.string(try Wire.array(body, "devices")[0], "signing_key")
            deviceStatus = "approved"
            return Self.reply([:])
        case "GET /api/sharing/audience":
            return Self.reply([
                "account_ids": audience, "eligible_members": eligible,
                "owner_viewer": ownerViewer.map { ["id": $0] as Any } ?? NSNull(),
            ])
        case "PUT /api/sharing/audience":
            audience = (payload["account_ids"] as? [String]) ?? []
            return Self.reply([:])
        case "PUT /api/sharing":
            sharing = (payload["enabled"] as? Bool) ?? sharing
            return Self.reply([:])
        case "POST /api/phones/self-revoke":
            deviceStatus = "revoked"
            return Self.reply(["revoked": true])
        case "GET /api/view":
            return Self.reply(["revision": changes.count, "records": view.map(\.1)])
        case "GET /api/places/manifest":
            let places = view.filter { ($0.1["kind"] as? String) == "place" }.map {
                ["id": $0.1["entity_id"] ?? "", "record_id": $0.1["id"] ?? ""] as Wire.Object
            }
            return Self.reply(["token": "places-token", "places": places])
        case "GET /api/profile/current":
            return Self.reply(["replaces": profileRecord.map { $0 as Any } ?? NSNull()])
        case "POST /api/records":
            try accept(payload)
            return Self.reply([:], status: 201)
        case "POST /api/records/batch":
            for record in try Wire.array(payload, "records") { try accept(record) }
            return Self.reply(["accepted": true])
        case "GET /api/trips":
            return Self.reply(["trips": trips, "processing": true, "road_matching_enabled": false])
        case "GET /api/alerts":
            return Self.reply(["alerts": alerts])
        case "GET /api/find-phone/command":
            return Self.reply(["command": findCommand.map { $0 as Any } ?? NSNull()])
        case "PUT /api/device/permissions", "PUT /api/find-phone/capability",
            "POST /api/find-phone/report", "PUT /api/push/subscription",
            "DELETE /api/push/subscription":
            return Self.reply(["ok": true])
        default:
            if route.hasPrefix("GET /api/trips/"),
                let detail = tripDetails[String(route.dropFirst("GET /api/trips/".count))]
            {
                return Self.reply(detail)
            }
            return Self.reply(["detail": "Not found"], status: 404)
        }
    }

    /// Checks a record's signature and applies it to the view, as the real server would.
    private func accept(_ envelope: Wire.Object) throws {
        let body = try Wire.dict(envelope, "body")
        let sender = currentDevices.first { ($0["id"] as? String) == (body["sender"] as? String) }
        guard let sender,
            HouseholdCipher.verify(
                body, signature: try Wire.string(envelope, "signature"),
                key: try Wire.string(sender, "signing_key"))
        else { throw NaraHemProtocolError.rejected("Bad record signature") }
        records.append(envelope)
        sequence = max(sequence, try Wire.integer(body, "sequence"))
        let key = (try Wire.string(body, "kind")) + ":" + (try Wire.string(body, "entity_id"))
        view.removeAll { $0.0 == key }
        if (body["operation"] as? String) != "delete" {
            let data = try Wire.dict(try serverCopy(envelope), "data")
            view.append(
                (
                    key,
                    [
                        "id": body["id"] ?? "", "kind": body["kind"] ?? "", "operation": "upsert",
                        "entity_id": body["entity_id"] ?? "",
                        "captured_at": body["captured_at"] ?? 0, "data": data,
                    ]
                ))
        }
    }

    /// Reads a request body, which URLSession hands to protocols as a stream.
    private static func body(of request: URLRequest) -> Wire.Object {
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let read = stream.read(&buffer, maxLength: buffer.count)
                if read <= 0 { break }
                data.append(buffer, count: read)
            }
        }
        return (try? Wire.decode(data)) ?? [:]
    }

    /// Encodes a JSON reply.
    private static func reply(_ json: Wire.Object, status: Int = 200) -> (Int, Data) {
        (status, (try? Wire.encode(json)) ?? Data())
    }
}

/// Hands every request from a test session to the active FakeHouseholdServer.
final class FakeServerProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() {}

    override func startLoading() {
        guard let server = FakeHouseholdServer.active, let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost))
            return
        }
        let (status, body) = server.answer(request)
        let response = HTTPURLResponse(
            url: url, statusCode: status, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }
}
