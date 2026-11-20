import Foundation

/// Times for someone who may be in another time zone. Phones send their zone with each location;
/// when it gives a different clock from this iPhone's at that moment, both are shown, this
/// iPhone's first: "8:00 PM EST / 10:00 PM PST". Without a zone, or in the same one, it's the plain
/// local time. Same rule as Android and the web.
enum ZoneTimes {
    /// Formats a time in milliseconds as a time of day, or with its date when `withDate` is set.
    static func format(
        _ ms: Int, zone: String?, withDate: Bool = false,
        viewer: TimeZone = .current, locale: Locale = .current
    ) -> String {
        let date = Date(timeIntervalSince1970: Double(ms) / 1000)
        let local = text(date, viewer, withDate, locale, named: false)
        guard let theirs = known(zone),
            text(date, theirs, true, locale, named: false)
                != text(date, viewer, true, locale, named: false)
        else { return local }
        return text(date, viewer, withDate, locale, named: true) + " / "
            + text(date, theirs, withDate, locale, named: true)
    }

    /// Returns the zone if this iPhone knows it, otherwise nil.
    static func known(_ zone: String?) -> TimeZone? {
        guard let zone, !zone.isEmpty, zone.count <= 64 else { return nil }
        return TimeZone(identifier: zone)
    }

    /// Formats the date in a zone, with the zone's short name ("EST") when `named` is set.
    private static func text(
        _ date: Date, _ zone: TimeZone, _ withDate: Bool, _ locale: Locale, named: Bool
    ) -> String {
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.timeZone = zone
        formatter.dateStyle = withDate ? .short : .none
        formatter.timeStyle = .short
        let shown = formatter.string(from: date)
        guard named else { return shown }
        return shown + " " + (zone.abbreviation(for: date) ?? zone.identifier)
    }
}
