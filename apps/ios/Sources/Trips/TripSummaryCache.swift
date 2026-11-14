import Foundation

/// On-device cache of trip summaries and route outlines, per viewer and member. Protected by iOS
/// data protection and deleted at sign-out.
@MainActor
enum TripSummaryCache {
    static var directory: URL {
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[
            0]
        let url = root.appendingPathComponent("TripSummaries", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    /// Returns true for a 32-character hex ID, which is safe to use in a file name.
    private static func validId(_ id: String) -> Bool {
        id.count == 32
            && id.utf8.allSatisfy {
                ($0 >= 48 && $0 <= 57) || ($0 >= 97 && $0 <= 102)
            }
    }

    /// Returns the cache file for a viewer and member.
    private static func file(viewer: String, member: String) -> URL? {
        guard validId(viewer), validId(member) else { return nil }
        return directory.appendingPathComponent("\(viewer)-\(member).json")
    }

    /// Returns cached trips for a member within the range.
    static func load(viewer: String, member: String, days: Int) -> [HouseholdTrip] {
        guard let file = file(viewer: viewer, member: member),
            let bytes = try? Data(contentsOf: file),
            let snapshot = try? JSONDecoder().decode(Snapshot.self, from: bytes)
        else { return [] }
        let earliest =
            Int(Date().timeIntervalSince1970 * 1000)
            - min(max(days, 1), 14) * 86_400_000
        return snapshot.trips.filter { $0.endedAt >= earliest }
            .sorted { $0.startedAt > $1.startedAt }
    }

    /// Merges fresh trips into the cache.
    static func save(_ incoming: [HouseholdTrip], viewer: String, member: String, days: Int) {
        guard let url = file(viewer: viewer, member: member) else { return }
        let now = Int(Date().timeIntervalSince1970 * 1000)
        let refreshedStart = now - min(max(days, 1), 14) * 86_400_000
        // Replace the refreshed range so trips removed on the server don't come back from the
        // cache. Older entries are kept.
        let older = load(viewer: viewer, member: member, days: 14)
            .filter { $0.endedAt < refreshedStart }
        let previouslyCached = Dictionary(
            uniqueKeysWithValues:
                load(viewer: viewer, member: member, days: 14).map { ($0.id, $0) })
        var merged = Dictionary(uniqueKeysWithValues: older.map { ($0.id, $0) })
        for var trip in incoming {
            // Keep outlines and endpoints decoded on this device from older records.
            if let cached = previouslyCached[trip.id] {
                if trip.preview == nil { trip.preview = cached.preview }
                if trip.start == nil { trip.start = cached.start }
                if trip.end == nil { trip.end = cached.end }
                if trip.originName == nil { trip.originName = cached.originName }
            }
            merged[trip.id] = trip
        }
        let earliest = now - 14 * 86_400_000
        let sorted = merged.values.filter { $0.endedAt >= earliest }
            .sorted { $0.startedAt > $1.startedAt }
        guard let data = try? JSONEncoder().encode(Snapshot(trips: Array(sorted.prefix(200))))
        else { return }
        do {
            try data.write(to: url, options: .atomic)
            try FileManager.default.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: url.path)
        } catch { /* Cache failure must never block a trip request. */  }
    }

    /// Returns a trip's cached outline and endpoints.
    static func cachedDetails(for trip: HouseholdTrip, viewer: String) -> HouseholdTrip? {
        load(viewer: viewer, member: trip.accountId, days: 14)
            .first(where: { $0.id == trip.id && $0.deviceId == trip.deviceId })
    }

    /// Caches a trip's outline and endpoints.
    static func storeDetails(_ trip: HouseholdTrip, viewer: String) {
        var trips = load(viewer: viewer, member: trip.accountId, days: 14)
        guard let index = trips.firstIndex(where: { $0.id == trip.id }) else { return }
        trips[index] = trip
        save(trips, viewer: viewer, member: trip.accountId, days: 14)
    }

    /// Deletes a viewer's cache.
    static func clear(viewer: String) {
        guard validId(viewer),
            let files = try? FileManager.default.contentsOfDirectory(
                at: directory,
                includingPropertiesForKeys: nil)
        else { return }
        for file in files where file.lastPathComponent.hasPrefix(viewer + "-") {
            try? FileManager.default.removeItem(at: file)
        }
        let images = directory.appendingPathComponent("Previews", isDirectory: true)
        if let thumbnails = try? FileManager.default.contentsOfDirectory(
            at: images,
            includingPropertiesForKeys: nil)
        {
            for file in thumbnails where file.lastPathComponent.hasPrefix(viewer + "-") {
                try? FileManager.default.removeItem(at: file)
            }
        }
    }

    /// Contents of one cache file.
    private struct Snapshot: Codable {
        var trips: [HouseholdTrip]
    }
}
