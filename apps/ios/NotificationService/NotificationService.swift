import Foundation
import UserNotifications

/// Notification service extension for household alert pushes. The push only says "Household alert";
/// this fetches the newest alert from the household server using the device credential shared
/// through the App Group keychain, and replaces the text before iOS shows it. Apple never sees the
/// alert text. If the fetch fails, the placeholder is shown.
final class NotificationService: UNNotificationServiceExtension {
    private var handler: ((UNNotificationContent) -> Void)?
    private var content: UNMutableNotificationContent?
    private var work: Task<Void, Never>?

    /// Replaces the notification body with the newest unseen alert, or delivers the placeholder if
    /// there is none.
    override func didReceive(
        _ request: UNNotificationRequest,
        withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void
    ) {
        handler = contentHandler
        let content =
            (request.content.mutableCopy() as? UNMutableNotificationContent)
            ?? UNMutableNotificationContent()
        self.content = content
        work = Task { @MainActor [weak self] in
            if let text = await AlertReader.newestText() {
                content.title = ""
                content.body = text
            }
            self?.finish()
        }
    }

    /// Delivers the notification as it is when iOS's time limit runs out.
    override func serviceExtensionTimeWillExpire() {
        work?.cancel()
        finish()
    }

    /// Delivers the notification to iOS. Safe to call more than once.
    private func finish() {
        DispatchQueue.main.async { [weak self] in
            guard let self, let handler = self.handler else { return }
            self.handler = nil
            handler(self.content ?? UNMutableNotificationContent())
        }
    }
}

/// Fetches household alerts with the app's shared device credential.
@MainActor
private enum AlertReader {
    /// Defaults key for the IDs of alerts already shown, so the next push shows the next alert.
    private static let shownKey = "household-alerts.shown"

    /// Returns the text of the newest alert not shown yet, or nil.
    static func newestText() async -> String? {
        let api = NaraHemAPI()
        let household = TrustedHousehold(api: api)
        guard household.restoreDevice(), let identity = household.identity,
            (try? api.setServer(identity.server)) != nil
        else { return nil }
        let now = Int(Date().timeIntervalSince1970 * 1000)
        guard let alerts = try? await household.recentAlerts(since: now - HouseholdAlerts.staleMs)
        else { return nil }
        // Skip alerts about this phone's own account.
        let fresh = alerts.filter {
            $0.accountId != identity.accountId && now - $0.capturedAt <= HouseholdAlerts.staleMs
        }
        .sorted { $0.capturedAt < $1.capturedAt }
        guard let newest = fresh.last else { return nil }
        let store = UserDefaults(suiteName: HouseholdAlerts.appGroup) ?? .standard
        let shown = store.stringArray(forKey: shownKey) ?? []
        let unseen = fresh.filter { !shown.contains($0.id) }
        let chosen = unseen.isEmpty ? [newest] : unseen
        let lines = chosen.map(\.text)
        store.set(Array((shown + chosen.map(\.id)).suffix(200)), forKey: shownKey)
        return lines.isEmpty ? nil : lines.joined(separator: "\n")
    }
}
