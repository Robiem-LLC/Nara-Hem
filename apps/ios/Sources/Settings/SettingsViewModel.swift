import CoreLocation
import Foundation
import Observation
import UIKit

/// View model for the Settings tab.
@MainActor
@Observable
final class SettingsViewModel {
    var editableUsername = ""
    let session: HouseholdSession
    let tracker: LocationTracker
    private let accounts: AccountService
    private let household: HouseholdService

    /// This account's member entry, used for the profile photo.
    var me: HouseholdMember? { session.members.first(where: { $0.id == session.account?.id }) }

    var locationDescription: String {
        switch tracker.locationPermission {
        case .authorizedAlways: "Always"
        case .authorizedWhenInUse: "When in use"
        case .denied: "Denied"
        case .restricted: "Restricted"
        case .notDetermined: "Not requested"
        @unknown default: "Unknown"
        }
    }

    /// Creates the view model on the shared session.
    init(
        session: HouseholdSession, tracker: LocationTracker, accounts: AccountService,
        household: HouseholdService
    ) {
        self.session = session
        self.tracker = tracker
        self.accounts = accounts
        self.household = household
    }

    /// Signs out.
    func signOut() { session.signOut() }

    /// Opens this app's page in the Settings app.
    func openSettings() { session.openSettings() }

    /// Opens Nära Hem's notification settings.
    func openNotificationSettings() { session.openNotificationSettings() }

    /// Requests notification permission.
    func requestNotifications() { session.requestNotifications() }

    /// Re-reads the notification permission.
    func refreshNotificationSettings() { session.refreshNotificationSettings() }

    /// Prefills the username field when the screen opens.
    func opened() {
        editableUsername = session.account?.name ?? ""
        session.refreshNotificationSettings()
    }

    /// Validates and saves a new display name.
    func changeUsername() {
        session.work {
            let updated = try await self.accounts.updateUsername(self.editableUsername)
            if let previous = self.session.account {
                self.session.account = NaraHemAccount(
                    id: previous.id, name: updated,
                    household: previous.household, role: previous.role,
                    verified: previous.verified)
            }
            self.session.message = "Username updated to \(updated)."
            await self.session.refreshNow()
        }
    }

    /// Crops and compresses a photo to a small JPEG and publishes it.
    func saveProfileImage(_ image: UIImage) {
        let scale = min(1, 96 / max(image.size.width, image.size.height))
        let size = CGSize(
            width: max(1, image.size.width * scale),
            height: max(1, image.size.height * scale))
        let renderer = UIGraphicsImageRenderer(size: size)
        let resized = renderer.image { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
        if let jpeg = resized.jpegData(compressionQuality: 0.50) {
            saveProfile(jpeg: jpeg)
        }
    }

    /// Publishes a JPEG as the profile photo.
    func saveProfile(jpeg: Data) {
        session.work {
            guard let account = self.session.account else {
                throw NaraHemProtocolError.rejected("Sign in first")
            }
            try await self.household.savePhoto(jpeg: jpeg, name: account.name)
            await self.session.refreshNow()
        }
    }

    /// Enables or disables location sharing.
    func setSharing(_ enabled: Bool) {
        session.work {
            if !enabled { self.tracker.pauseSharing() }
            try await self.household.setSharing(enabled)
            self.session.sharing = enabled
            self.tracker.updateMonitoring()
            if enabled {
                await self.tracker.drainPending()
            }
            self.session.message =
                enabled ? "Location sharing enabled." : "Location sharing paused."
        }
    }

    /// Sets which accounts can see this phone's location.
    func setAudience(_ newIds: Set<String>) {
        session.work {
            guard !self.session.syncProblem else {
                throw NaraHemProtocolError.rejected(
                    "Refresh the household before editing recipients")
            }
            try await self.household.setAudience(newIds)
            self.session.audience = newIds
            self.session.message = "Location sharing choices saved."
        }
    }

    /// Adds or removes one account from the audience.
    func setViewer(_ id: String, included: Bool) {
        var next = session.audience
        if included { next.insert(id) } else { next.remove(id) }
        setAudience(next)
    }

    /// Enables or disables Find My Phone.
    func setFindPhone(_ enabled: Bool) {
        session.work {
            try await self.household.setFindPhone(enabled)
            self.session.findPhoneChanged(enabled)
            self.session.message = ""
        }
    }

    /// Enables or disables background GPS collection.
    func setTracking(_ enabled: Bool) {
        if !tracker.setTracking(enabled) {
            session.message = "Allow Always Location in iPhone Settings before background sharing."
        }
    }

    /// Deletes locations queued on this phone.
    func clearLocalLocations() {
        tracker.clearLocalLocations()
        session.message = "Offline locations and pending trips cleared."
    }

    /// Permanently revokes this phone and signs out.
    func revokeThisPhone() {
        session.work {
            try await self.household.revokeThisPhone()
            self.session.signOut()
        }
    }
}
