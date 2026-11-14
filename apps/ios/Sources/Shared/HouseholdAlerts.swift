import Foundation

/// Constants for household alerts. The server decides and words alerts; the app and the
/// notification extension only fetch and show them.
enum HouseholdAlerts {
    static let staleMs = 15 * 60_000  // an alert this old is old news

    /// App Group shared with the notification service extension.
    static let appGroup = "group.com.robiem.narahem.notifications"
}
