import Foundation

/// Reading and publishing the household's encrypted records.
extension TrustedHousehold {
    /// Fetches every member's latest location and the saved places.
    func snapshot() async throws -> HouseholdSnapshot {
        guard let v = identity else { throw NaraHemProtocolError.rejected("Enroll iPhone first") }
        _ = try await syncRoster()
        let accountRows = try Wire.array(
            try await api.accountRequest("/api/household/members"), "members")
        let view = try await device("/api/view")
        guard try Wire.integer(view, "revision") == identity?.revision else {
            throw NaraHemProtocolError.rejected("Roster changed during sync; retry")
        }
        let opened = try Wire.array(view, "records")
        var currentProfiles: [String: Wire.Object] = [:]
        var currentLocations: [String: Wire.Object] = [:]
        var saved: [SavedPlace] = []
        for item in opened where (item["operation"] as? String) == "upsert" {
            let kind = try Wire.string(item, "kind")
            let entityId = try Wire.string(item, "entity_id")
            let data = try Wire.dict(item, "data")
            switch kind {
            case "profile": currentProfiles[entityId] = data
            case "location":
                if ((try? Wire.integer(item, "captured_at")) ?? 0)
                    >= ((try? Wire.integer(currentLocations[entityId] ?? [:], "captured_at")) ?? 0)
                {
                    currentLocations[entityId] = item
                }
            case "place":
                let lat = try Wire.number(data, "lat"), lon = try Wire.number(data, "lon")
                let radius = try Wire.number(data, "radius")
                guard (-90...90).contains(lat), (-180...180).contains(lon),
                    (1...10000).contains(radius)
                else {
                    throw NaraHemProtocolError.rejected("Invalid encrypted place geometry")
                }
                saved.append(
                    SavedPlace(
                        id: entityId, name: try Wire.string(data, "name"),
                        lat: lat, lon: lon, radius: radius,
                        recordId: try Wire.string(item, "id"),
                        alerts: (data["alerts"] as? Wire.Object) ?? [:], data: data))
            default: break
            }
        }
        let rosterMembers = accountRows.compactMap { raw -> HouseholdMember? in
            guard let id = raw["id"] as? String else { return nil }
            let data = currentLocations[id]?["data"] as? Wire.Object
            let profile = currentProfiles[id] ?? [:]
            return HouseholdMember(
                id: id,
                // The server's username is current; a profile keeps the name from when its
                // photo was set.
                name: (raw["username"] as? String) ?? (profile["name"] as? String) ?? "Member",
                lat: (data?["lat"] as? NSNumber)?.doubleValue,
                lon: (data?["lon"] as? NSNumber)?.doubleValue,
                accuracy: (data?["accuracy"] as? NSNumber)?.doubleValue,
                capturedAt: (currentLocations[id]?["captured_at"] as? NSNumber)?.intValue ?? 0,
                photo: profile["photo"] as? String,
                speed: (data?["speed_mps"] as? NSNumber)?.doubleValue,
                battery: (data?["battery_pct"] as? NSNumber)?.intValue,
                charging: data?["charging"] as? Bool,
                tripId: data?["trip_id"] as? String,
                stillSince: (currentLocations[id]?["still_since"] as? NSNumber)?.intValue,
                lastContact: (currentLocations[id]?["last_contact"] as? NSNumber)?.intValue)
        }
        members = rosterMembers
        places = saved
        _ = v
        return HouseholdSnapshot(members: rosterMembers, places: saved)
    }

    /// Returns who this phone's location records are encrypted for: the server's audience, never
    /// widened past the list saved on this phone, plus the admin browser, which always sees a
    /// phone that shares its location.
    private func allowedViewers(_ v: TrustedIdentity) async throws -> Set<String> {
        let reply = try await device("/api/sharing/audience")
        let serverAudience = Set(reply["account_ids"] as? [String] ?? [])
        let owner = (reply["owner_viewer"] as? Wire.Object)?["id"] as? String
        guard let pinned = v.pinnedAudience else { return serverAudience }
        return serverAudience.intersection(Set(pinned).union(owner.map { [$0] } ?? []))
    }

    /// Reloads this phone's sharing audience and the eligible members, and returns the names of
    /// members who joined since the last look.
    @discardableResult func refreshAudience() async throws -> [String] {
        let response = try await device("/api/sharing/audience")
        let ids = (response["account_ids"] as? [String]) ?? []
        audience = Set(ids).intersection(identity?.pinnedAudience.map(Set.init) ?? Set(ids))
        choices = try Wire.array(response, "eligible_members")
            .filter { ($0["role"] as? String) != "admin" }
            .compactMap { item in
                guard let id = item["id"] as? String else { return nil }
                return AudienceChoice(id: id, name: (item["name"] as? String) ?? "Member")
            }
        ownerViewerId = (response["owner_viewer"] as? Wire.Object)?["id"] as? String
        return try await includeNewMembers()
    }

    /// Shares with members this phone hasn't seen before and returns their names. The first look
    /// only records who is already here.
    private func includeNewMembers() async throws -> [String] {
        guard var v = identity else { return [] }
        let eligible = Set(choices.map(\.id))
        guard let known = v.knownMembers else {
            v.knownMembers = eligible.sorted()
            identity = v
            try save()
            return []
        }
        let newcomers = eligible.subtracting(known)
        guard !newcomers.isEmpty else { return [] }
        // Without a pinned list the server already shares with everyone.
        if let pinned = v.pinnedAudience {
            let viewers = eligible.union(ownerViewerId.map { [$0] } ?? [])
            try await setAudience(Set(pinned).intersection(viewers).union(newcomers))
        }
        guard var updated = identity else { return [] }
        updated.knownMembers = Set(known).union(eligible).sorted()
        identity = updated
        try save()
        return choices.filter { newcomers.contains($0.id) }.map(\.name)
    }

    /// Sets which accounts can see this phone's location.
    func setAudience(_ selected: Set<String>) async throws {
        guard var v = identity else { throw NaraHemProtocolError.rejected("Device not enrolled") }
        let available = Set(choices.map(\.id)).union(ownerViewerId.map { [$0] } ?? [])
        guard selected.isSubset(of: available) else {
            throw NaraHemProtocolError.rejected("Refresh and select only current approved viewers")
        }
        _ = try await device(
            "/api/sharing/audience",
            payload: ["account_ids": selected.sorted()], method: "PUT")
        v.pinnedAudience = selected.sorted()
        identity = v
        try save()
        audience = selected
    }

    /// Enables or disables sharing on the server.
    func setSharing(_ enabled: Bool) async throws {
        if !enabled { sharing = false }
        _ = try await device("/api/sharing", payload: ["enabled": enabled], method: "PUT")
        sharing = enabled
    }

    /// Encrypts a record for every allowed recipient and the server, signs it and uploads it.
    func publish(
        kind: String, entityId: String, data: Wire.Object,
        replaces: String? = nil, operation: String = "upsert",
        capturedAt: Int? = nil, notify: Bool = false
    ) async throws {
        var recipients: [Wire.Object] = []
        guard var v = identity else { throw NaraHemProtocolError.rejected("Enroll iPhone first") }
        let roster = try await syncRoster()
        let current = try await device("/api/device")
        guard (current["status"] as? String) == "approved" else {
            throw NaraHemProtocolError.rejected("iPhone approval required before sharing")
        }
        if kind == "location" || kind == "event" {
            guard (current["sharing"] as? Bool) == true && sharing else {
                throw NaraHemProtocolError.rejected("Location sharing is paused")
            }
        }
        var pointer: Any = replaces ?? (NSNull() as Any)
        var headers: [String: String] = [:]
        if kind == "place" {
            let manifest = try await device("/api/places/manifest")
            let old = places.first { $0.id == entityId }
            let sameGeometry =
                operation == "upsert" && old != nil && (data["lat"] as? Double) == old?.lat
                && (data["lon"] as? Double) == old?.lon
                && (data["radius"] as? Double) == old?.radius
            if operation == "upsert" && !sameGeometry {
                let lat = try Wire.number(data, "lat")
                let lon = try Wire.number(data, "lon")
                let radius = try Wire.number(data, "radius")
                if let colliding = places.first(where: {
                    $0.id != entityId && Self.meters(lat, lon, $0.lat, $0.lon) < radius + $0.radius
                }) {
                    throw NaraHemProtocolError.rejected("Place overlaps \(colliding.name)")
                }
            }
            let row = try Wire.array(manifest, "places").first { ($0["id"] as? String) == entityId }
            if let old = old, let replaces, old.recordId != replaces {
                throw NaraHemProtocolError.rejected("Place changed; refresh before editing")
            }
            pointer = (row?["record_id"] as? String) ?? (NSNull() as Any)
            headers["X-Places-State"] = try Wire.string(manifest, "token")
        }
        if kind == "profile" {
            pointer =
                (try await device("/api/profile/current"))["replaces"] as? String
                ?? (NSNull() as Any)
        }
        let serverSequence = try Wire.integer(current, "sequence")
        let nextSequence = max(v.sequence, serverSequence) + 1
        let rosterDevices = try Wire.array(roster, "devices")
        let audienceIds: Set<String>?
        if kind == "location" || kind == "event" {
            audienceIds = try await allowedViewers(v)
        } else {
            audienceIds = nil
        }
        let bodyContext: Wire.Object = [
            "household": v.household, "revision": v.revision, "id": Wire.freshId(), "sender": v.id,
            "sequence": nextSequence, "kind": kind, "entity_id": entityId, "operation": operation,
            "replaces": pointer,
            "captured_at": capturedAt ?? Int(Date().timeIntervalSince1970 * 1000),
        ]
        var payload: Wire.Object = bodyContext
        payload["domain"] = "narahem.payload.v1"
        payload["data"] = data
        for recipient in rosterDevices {
            let accountId = try Wire.string(recipient, "account_id")
            if let allowed = audienceIds, accountId != v.accountId && !allowed.contains(accountId) {
                continue
            }
            recipients.append([
                "device_id": try Wire.string(recipient, "id"),
                "box": try HouseholdCipher.seal(
                    payload, recipient: Wire.string(recipient, "box_key")),
            ])
        }
        var body: Wire.Object = bodyContext
        body["domain"] = "narahem.record.v1"
        body["recipients"] = recipients
        if operation == "upsert" || kind == "place" {
            guard let key = current["trip_processing_key"] as? String, !key.isEmpty else {
                throw NaraHemProtocolError.rejected("Server key unavailable")
            }
            body["server_box"] = try HouseholdCipher.seal(payload, recipient: key)
        }
        var envelope: Wire.Object = [
            "body": body,
            "signature": try HouseholdCipher.sign(body, key: v.signing.secret),
        ]
        if notify { envelope["notify"] = true }
        _ = try await device("/api/records", payload: envelope, method: "POST", headers: headers)
        v.sequence = nextSequence
        identity = v
        try save()
    }

    /// Publishes one location.
    func publishLocation(_ fix: LocalLocation) async throws {
        guard let identity else { throw NaraHemProtocolError.rejected("Device not enrolled") }
        var data: Wire.Object = [
            "lat": fix.latitude, "lon": fix.longitude, "accuracy": fix.accuracy,
        ]
        if let speed = fix.speedMps { data["speed_mps"] = speed }
        if let battery = fix.batteryPct { data["battery_pct"] = battery }
        if let charging = fix.charging { data["charging"] = charging }
        if let tripId = fix.tripId { data["trip_id"] = tripId }
        try await publish(
            kind: "location", entityId: identity.accountId, data: data,
            capturedAt: Int(fix.capturedAt.timeIntervalSince1970 * 1000))
    }

    /// Encrypts and signs each fix separately and uploads them in one request. The server checks
    /// each record as if it were sent alone.
    func publishLocations(_ fixes: [LocalLocation]) async throws {
        guard !fixes.isEmpty && fixes.count <= 12,
            var v = identity
        else {
            throw NaraHemProtocolError.rejected("A GPS batch needs an enrolled iPhone")
        }
        let roster = try await syncRoster()
        let current = try await device("/api/device")
        guard (current["status"] as? String) == "approved",
            (current["sharing"] as? Bool) == true && sharing
        else {
            throw NaraHemProtocolError.rejected("Location sharing is paused")
        }
        let devices = try Wire.array(roster, "devices")
        let allowed = try await allowedViewers(v)
        var sequence = max(v.sequence, try Wire.integer(current, "sequence"))
        var envelopes: [Wire.Object] = []

        for fix in fixes {
            sequence += 1
            let capturedAt = Int(fix.capturedAt.timeIntervalSince1970 * 1000)
            let context: Wire.Object = [
                "household": v.household, "revision": v.revision,
                "id": Wire.freshId(), "sender": v.id, "sequence": sequence,
                "kind": "location", "entity_id": v.accountId,
                "operation": "upsert", "replaces": NSNull(), "captured_at": capturedAt,
            ]
            var data: Wire.Object = [
                "lat": fix.latitude, "lon": fix.longitude, "accuracy": fix.accuracy,
            ]
            if let speed = fix.speedMps { data["speed_mps"] = speed }
            if let battery = fix.batteryPct { data["battery_pct"] = battery }
            if let charging = fix.charging { data["charging"] = charging }
            if let tripId = fix.tripId { data["trip_id"] = tripId }
            var payload = context
            payload["domain"] = "narahem.payload.v1"
            payload["data"] = data
            var recipients: [Wire.Object] = []
            for recipient in devices {
                let accountId = try Wire.string(recipient, "account_id")
                if accountId != v.accountId && !allowed.contains(accountId) { continue }
                recipients.append([
                    "device_id": try Wire.string(recipient, "id"),
                    "box": try HouseholdCipher.seal(
                        payload, recipient: Wire.string(recipient, "box_key")),
                ])
            }
            var signedBody = context
            signedBody["domain"] = "narahem.record.v1"
            signedBody["recipients"] = recipients
            guard let key = current["trip_processing_key"] as? String, !key.isEmpty else {
                throw NaraHemProtocolError.rejected("Server key unavailable")
            }
            signedBody["server_box"] = try HouseholdCipher.seal(payload, recipient: key)
            envelopes.append([
                "body": signedBody,
                "signature": try HouseholdCipher.sign(signedBody, key: v.signing.secret),
            ])
        }
        _ = try await device("/api/records/batch", payload: ["records": envelopes], method: "POST")
        v.sequence = sequence
        identity = v
        try save()
    }

    /// Publishes a completed trip summary.
    func publishTrip(_ trip: HouseholdTrip) async throws {
        guard let v = identity else { throw NaraHemProtocolError.rejected("Device not enrolled") }
        var data: Wire.Object = [
            "type": "trip_summary", "account_id": v.accountId,
            "started_at": trip.startedAt, "ended_at": trip.endedAt,
            "distance_m": trip.distance, "max_speed_mps": trip.maxSpeed, "samples": trip.samples,
        ]
        if let tripId = trip.tripId { data["trip_id"] = tripId }
        if let origin = trip.originName, !origin.isEmpty { data["origin_name"] = origin }
        if let start = trip.start, start.count == 2 { data["start"] = start }
        if let end = trip.end, end.count == 2 { data["end"] = end }
        if let preview = trip.preview, preview.count >= 2, preview.count <= 128 {
            data["preview"] = preview
        }
        try await publish(
            kind: "event", entityId: Wire.freshId(),
            data: data, capturedAt: trip.endedAt)
    }

    /// Creates or updates a saved place.
    func savePlace(
        name: String, lat: Double, lon: Double, radius: Double,
        existing: SavedPlace?, alerts: Wire.Object = [:]
    ) async throws {
        guard !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            name.count <= 80, (-90...90).contains(lat), (-180...180).contains(lon),
            (1...10000).contains(radius)
        else {
            throw NaraHemProtocolError.rejected(
                "Enter a place name, coordinates and radius (1–10,000 m)")
        }
        var data = existing?.data ?? [:]
        data["name"] = name.trimmingCharacters(in: .whitespacesAndNewlines)
        data["lat"] = lat; data["lon"] = lon; data["radius"] = radius; data["alerts"] = alerts
        try await publish(
            kind: "place", entityId: existing?.id ?? Wire.freshId(),
            data: data, replaces: existing?.recordId)
        _ = try await snapshot()
    }

    /// Deletes a saved place for the whole household.
    func deletePlace(_ place: SavedPlace) async throws {
        try await publish(
            kind: "place", entityId: place.id, data: [:],
            replaces: place.recordId, operation: "delete")
        _ = try await snapshot()
    }

    /// Publishes this member's display name and profile photo.
    func savePhoto(jpeg: Data, name: String) async throws {
        let dataURI = "data:image/jpeg;base64," + jpeg.base64EncodedString()
        guard dataURI.count <= 14500 else {
            throw NaraHemProtocolError.rejected("Crop or reduce photo size before sharing")
        }
        guard let v = identity else { throw NaraHemProtocolError.rejected("Device not enrolled") }
        try await publish(
            kind: "profile", entityId: v.accountId,
            data: ["name": name, "photo": dataURI])
    }

    /// Fetches alerts about other members since `since` (milliseconds). The server decides and
    /// words them.
    func recentAlerts(since: Int) async throws -> [ReceivedAlert] {
        let response = try await device("/api/alerts?since=\(max(0, since))")
        return try Wire.array(response, "alerts").compactMap { item in
            guard let id = item["id"] as? String, let account = item["account_id"] as? String,
                let captured = (item["captured_at"] as? NSNumber).map({ Int($0.int64Value) }),
                let text = item["text"] as? String, !text.isEmpty
            else { return nil }
            return ReceivedAlert(
                id: id, accountId: account, capturedAt: captured, text: String(text.prefix(300)))
        }
    }

    /// Fetches a member's trip summaries. Full routes are only loaded when a trip is opened.
    func trips(
        accountId: String, days: Int = 1
    ) async throws -> ([HouseholdTrip], [HouseholdTripPoint], Bool?, Bool?) {
        _ = try await syncRoster()
        let now = Int(Date().timeIntervalSince1970 * 1000)
        let earliest = now - min(max(days, 1), 14) * 86_400_000
        var summaries: [HouseholdTrip] = []
        var processingEnabled: Bool?
        var roadsEnabled: Bool?
        let indexed = try await device(
            "/api/trips?account_id=\(accountId)&start=\(earliest)&end=\(now + 300000)")
        if let rows = indexed["trips"] as? [Wire.Object] {
            processingEnabled = indexed["processing"] as? Bool
            roadsEnabled = indexed["road_matching_enabled"] as? Bool
            for row in rows {
                guard let eventId = row["id"] as? String,
                    let deviceId = row["device_id"] as? String,
                    let start = (row["started_at"] as? NSNumber)?.intValue,
                    let end = (row["ended_at"] as? NSNumber)?.intValue,
                    let distance = (row["distance_m"] as? NSNumber)?.doubleValue,
                    let speed = (row["max_speed_mps"] as? NSNumber)?.doubleValue,
                    let samples = (row["samples"] as? NSNumber)?.intValue
                else { continue }
                var trip = HouseholdTrip(
                    id: eventId, accountId: accountId,
                    deviceId: deviceId, startedAt: start, endedAt: end,
                    distance: distance, maxSpeed: speed, samples: samples,
                    tripId: row["trip_id"] as? String)
                trip.normalized = true
                trip.matched = row["matched"] as? Bool ?? false
                trip.processing = row["processing"] as? Bool ?? false
                trip.partial = row["partial"] as? Bool ?? false
                trip.start = row["start"] as? [Double]
                trip.end = row["end"] as? [Double]
                trip.preview = row["preview"] as? [[Double]]
                trip.originName = row["origin_name"] as? String
                trip.startLabel = (row["start_label"] as? String).flatMap {
                    $0.isEmpty ? nil : String($0.prefix(200))
                }
                trip.endLabel = (row["end_label"] as? String).flatMap {
                    $0.isEmpty ? nil : String($0.prefix(200))
                }
                summaries.append(trip)
            }
        }
        return (
            summaries.sorted { $0.startedAt > $1.startedAt }, [], processingEnabled, roadsEnabled
        )
    }

    /// Fetches the full route of one trip.
    func tripRoute(_ trip: HouseholdTrip) async throws -> [HouseholdTripPoint] {
        let indexed = try await device("/api/trips/\(trip.id)")
        if let route = indexed["route"] as? [[Double]] {
            let times = (indexed["times"] as? [NSNumber]).flatMap {
                $0.count == route.count ? $0 : nil
            }
            return route.enumerated().compactMap { index, coordinate in
                guard coordinate.count == 2 else { return nil }
                let fraction = route.count > 1 ? Double(index) / Double(route.count - 1) : 0
                return HouseholdTripPoint(
                    id: "\(trip.id):\(index)",
                    lat: coordinate[0], lon: coordinate[1],
                    capturedAt: times.map { Int($0[index].int64Value) } ?? trip.startedAt
                        + Int(Double(trip.endedAt - trip.startedAt) * fraction),
                    tripId: trip.tripId)
            }
        }
        return []
    }

    /// Reports this phone's permission settings. These are what iOS reports, not proof that alerts
    /// get through Focus.
    func reportDevicePermissions(
        foreground: Bool, background: Bool, alarm: Bool,
        notifications: Bool, sharing: Bool
    ) async throws {
        _ = try await device(
            "/api/device/permissions",
            payload: [
                "foreground_location": foreground,
                "background_location": background,
                "remote_alarm": alarm,
                "dnd_access": false,  // Android-specific permission; never claim it on iOS.
                "notifications": notifications,
                "sharing": sharing,
            ], method: "PUT")
    }

    /// Enables or disables Find My Phone on the server.
    func setFindPhone(_ enabled: Bool) async throws {
        _ = try await device(
            "/api/find-phone/capability",
            payload: ["enabled": enabled, "platform": "ios"], method: "PUT")
        findPhoneEnabled = enabled
        UserDefaults.standard.set(enabled, forKey: "narahem.find.enabled")
    }

    /// Fetches the next Find My Phone command, verifies the admin's signature, and marks it used so
    /// it can't run twice.
    func findCommand() async throws -> (String, String, Int)? {
        guard findPhoneEnabled, let v = identity else { return nil }
        let response = try await device("/api/find-phone/command")
        guard let envelope = response["command"] as? Wire.Object else { return nil }
        let body = try Wire.dict(envelope, "body")
        let commandId = try Wire.string(body, "id")
        let action = try Wire.string(body, "action")
        let now = Wire.timestamp()
        let issued = try Wire.integer(body, "issued_at")
        let expires = try Wire.integer(body, "expires_at")
        guard (body["domain"] as? String) == "narahem.find-phone.v1",
            (body["household"] as? String) == v.household,
            (body["target"] as? String) == v.id,
            commandId.count == 32, commandId.allSatisfy(\.isHexDigit),
            ["ring", "stop"].contains(action), issued <= now + 30,
            issued >= now - 120, expires > now, (1...120).contains(expires - issued)
        else {
            throw NaraHemProtocolError.rejected("Invalid find-phone command")
        }
        _ = try await syncRoster()
        guard let genesis = rosters[1],
            let ownerDevice = try Wire.array(genesis, "devices").first(where: {
                ($0["signing_key"] as? String) == v.anchor
            }),
            let ownerId = ownerDevice["account_id"] as? String,
            let active = currentRoster,
            let signer = try Wire.array(active, "devices").first(where: {
                ($0["id"] as? String) == (body["issuer"] as? String)
                    && ($0["account_id"] as? String) == ownerId
            }),
            HouseholdCipher.verify(
                body, signature: try Wire.string(envelope, "signature"),
                key: try Wire.string(signer, "signing_key"))
        else {
            throw NaraHemProtocolError.rejected(
                "Find-phone command is not signed by the approved household owner")
        }
        let key = "ios.find.replay." + v.id
        let old = (SecureVault.get(key).flatMap { try? Wire.decode($0) }) ?? [:]
        var recent: Wire.Object = [:]
        for (id, expiry) in old {
            if let seconds = (expiry as? NSNumber)?.intValue, seconds > now { recent[id] = seconds }
        }
        if recent[commandId] != nil { return nil }
        guard recent.count < 128 else {
            throw NaraHemProtocolError.rejected("Find-phone replay limit")
        }
        recent[commandId] = expires
        guard SecureVault.put(try Wire.encode(recent), key: key) else {
            throw NaraHemProtocolError.rejected("Unable to save Find My Phone replay protection")
        }
        return (commandId, action, expires)
    }

    /// Reports a Find My Phone command's status.
    func reportFind(_ id: String, state: String, reason: String = "") async {
        _ = try? await device(
            "/api/find-phone/report",
            payload: ["command_id": id, "status": state, "reason": reason], method: "POST")
    }

    /// Returns the distance between two points in metres.
    private static func meters(
        _ aLat: Double, _ aLon: Double, _ bLat: Double, _ bLon: Double
    ) -> Double {
        let radius = 6_371_000.0
        let deltaLat = (bLat - aLat) * .pi / 180
        let deltaLon = (bLon - aLon) * .pi / 180
        let h =
            pow(sin(deltaLat / 2), 2) + cos(aLat * .pi / 180) * cos(bLat * .pi / 180)
            * pow(sin(deltaLon / 2), 2)
        return 2 * radius * atan2(sqrt(h), sqrt(max(0, 1 - h)))
    }
}
