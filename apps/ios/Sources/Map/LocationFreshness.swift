import Foundation

/// Describes how current a member's location is. Parked phones report about every 15 minutes, so a
/// location that stayed the same reads "since 10:34" rather than stale. Same rules as Android and
/// the web.
enum LocationFreshness {
    static let staleMs = 20 * 60_000
    private static let offMs = 30 * 60_000

    /// Returns the freshness text and warning state for a member's location.
    static func of(
        _ member: HouseholdMember, now: Int = Int(Date().timeIntervalSince1970 * 1000)
    ) -> Status {
        let updated = "Updated " + time(member.capturedAt, now)
        if now - member.capturedAt <= staleMs { return Status(text: updated, alarming: false) }
        let heard = max(member.capturedAt, member.lastContact ?? 0)
        if let battery = member.battery, battery <= 10, member.charging != true, now - heard > offMs
        {
            return Status(
                text: "May be off · battery was \(battery)% at \(time(member.capturedAt, now))",
                alarming: true)
        }
        guard let since = member.stillSince else {
            return Status(text: updated + " · stale", alarming: true)
        }
        var text = "Here since " + time(since, now)
        if let contact = member.lastContact, contact > member.capturedAt + 60_000 {
            text += " · heard from " + time(contact, now)
        }
        return Status(text: text, alarming: false)
    }

    /// Formats a time, adding the date if it isn't today.
    private static func time(_ ms: Int, _ now: Int) -> String {
        let date = Date(timeIntervalSince1970: Double(ms) / 1000)
        let today = Calendar.current.isDate(
            date, inSameDayAs: Date(timeIntervalSince1970: Double(now) / 1000))
        return date.formatted(date: today ? .omitted : .abbreviated, time: .shortened)
    }

    /// Freshness text and whether it should be shown as a warning.
    struct Status: Equatable {
        /// Replaces "Updated 10:34 AM" once the location is old.
        var text: String

        /// The location may be wrong (old and not known to be parked, or the phone may be off).
        var alarming: Bool
    }
}
