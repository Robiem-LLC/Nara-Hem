import AlarmKit
import Foundation
import SwiftUI

// PARKED: kept for a possible future version. Nothing in the app calls it; iPhones only get
// the Find My Phone push notification sound.

/// AlarmKit alarm for Find My Phone (iOS 26+). Not used (see the PARKED note above).
@available(iOS 26.0, *)
@MainActor
final class SystemFindPhoneAlarm {
    private(set) var scheduledID: UUID?
    private var cancellation: Task<Void, Never>?

    var authorized: Bool {
        AlarmManager.shared.authorizationState == .authorized
    }

    /// Requests AlarmKit authorization.
    func requestAuthorization() async -> Bool {
        do {
            return try await AlarmManager.shared.requestAuthorization() == .authorized
        } catch {
            return false
        }
    }

    /// Schedules a system alarm to fire immediately.
    func ring(expires: Int) async throws {
        guard authorized else {
            throw NaraHemProtocolError.rejected("Allow Nära Hem alarms in iOS Settings")
        }
        let remaining = max(0, expires - Wire.timestamp())
        guard remaining >= 4 else {
            throw NaraHemProtocolError.rejected("Find My Phone request expired")
        }

        stop()
        let id = UUID()
        let alert: AlarmPresentation.Alert
        if #available(iOS 26.1, *) {
            alert = AlarmPresentation.Alert(title: "Find My Phone")
        } else {
            alert = AlarmPresentation.Alert(
                title: "Find My Phone",
                stopButton: AlarmButton(
                    text: "Stop", textColor: .white,
                    systemImageName: "stop.circle"))
        }
        let presentation = AlarmPresentation(alert: alert)
        let attributes = AlarmAttributes<EmptyMetadata>(
            presentation: presentation, metadata: nil, tintColor: .green)
        let configuration = AlarmManager.AlarmConfiguration.alarm(
            schedule: .fixed(Date().addingTimeInterval(2)),
            attributes: attributes, sound: .default)

        _ = try await AlarmManager.shared.schedule(id: id, configuration: configuration)
        scheduledID = id
        cancellation = Task { [weak self] in
            try? await Task.sleep(for: .seconds(remaining))
            guard !Task.isCancelled else { return }
            self?.stop()
        }
    }

    /// Cancels the scheduled alarm.
    func stop() {
        cancellation?.cancel()
        cancellation = nil
        if let id = scheduledID {
            try? AlarmManager.shared.cancel(id: id)
            scheduledID = nil
        }
    }

    /// Empty metadata, which AlarmKit requires.
    private struct EmptyMetadata: AlarmMetadata {}
}
