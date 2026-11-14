import CoreLocation
import Foundation
import MapKit
import Observation
import SwiftUI
import UIKit
import UserNotifications

/// State and actions shared by every screen: the account, this device's setup state, members and
/// places, sharing, the running action and its message, push registration and Find My Phone.
@MainActor
@Observable
final class HouseholdSession {
    var server = ""
    var signedIn = false
    var restoring = true
    var busy = false
    var message = ""

    /// "Kim has joined the household…", shown briefly over the tabs.
    var joinNotice = ""
    var account: NaraHemAccount?
    var deviceStatus = "register"
    var pairingCode = ""
    var members: [HouseholdMember] = []
    var places: [SavedPlace] = []
    var audience: Set<String> = []
    var audienceChoices: [AudienceChoice] = []
    var ownerViewerId: String?
    var viewerCacheId: String { trusted.identity?.id ?? "" }
    var sharing = false
    var findPhoneEnabled = false
    var pushPermission = false
    var notificationPermissionDenied = false
    var timeSensitiveAllowed = false
    var notificationSoundsAllowed = false
    var criticalAlertsAllowed = false
    var apnsTokenReceived = SecureVault.get("apns-device-token") != nil
    var pushSubscribed = false
    var syncProblem = false

    /// GPS collection and upload for this phone.
    let tracker: LocationTracker
    private let settings: AppSettings
    private let api: AccountService
    private var signOutActions: [@MainActor () -> Void] = []
    private let trusted: HouseholdService
    private var refreshing = false
    private var lastFindPoll: Date = .distantPast
    private var reportedFindCapability = false
    private var foregroundRefresh: Task<Void, Never>?
    private var mapVisible = false
    private var successfulPushRegistration: String?
    private var pushRegistrationInFlight = false
    private var lastAPNsTokenRefresh: Date = .distantPast
    private var lastPermissionReport = Date.distantPast

    /// Creates a session with the production container.
    convenience init() {
        self.init(container: AppContainer())
    }

    /// Creates a session from the given container.
    init(container: AppContainer) {
        api = container.accounts
        trusted = container.household
        tracker = container.tracker
        settings = container.settings
        server = settings.server
        findPhoneEnabled = settings.findPhoneEnabled
        tracker.canShare = { [weak self] in
            guard let self else { return false }
            return self.signedIn && self.deviceStatus == "ready" && self.sharing
        }
        tracker.accountId = { [weak self] in self?.account?.id }
        tracker.places = { [weak self] in self?.places ?? [] }
        tracker.onSyncProblem = { [weak self] in self?.syncProblem = true }
        tracker.onMessage = { [weak self] text in self?.message = text }
        tracker.afterDelivery = { [weak self] in await self?.pollFind() }
        tracker.onPermissionsChanged = { [weak self] in
            Task { await self?.reportPermissionsIfNeeded(force: true) }
        }
        NotificationCenter.default.addObserver(
            forName: .narahemPushRegistered, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.apnsTokenReceived = true
                await self.registerPushIfPossible()
            }
        }
        NotificationCenter.default.addObserver(
            forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.tracker.appBecameActive()
                self?.refreshHousehold()
                self?.startForegroundRefresh()
                self?.tracker.updateMonitoring()
                self?.refreshNotificationSettings()
                await self?.reportPermissionsIfNeeded(force: true)
            }
        }
        NotificationCenter.default.addObserver(
            forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in self?.foregroundRefresh?.cancel() }
        }
        Task { await restoreSession() }
    }

    /// Records whether the map is visible; it refreshes more often while it is.
    func setMapVisible(_ visible: Bool) { mapVisible = visible }

    /// Starts a refresh without waiting for it.
    func refreshHousehold() { Task { await refreshNow() } }

    /// Returns the account's email address and phone number, and whether the server can text.
    func contactDetails() async throws -> ContactDetails { try await api.contactDetails() }

    /// Runs a user action if none is running. Sets the busy flag and shows any error as a message.
    func work(_ operation: @escaping @MainActor () async throws -> Void) {
        guard !busy else { return }
        busy = true
        message = ""
        Task {
            defer { busy = false }
            do { try await operation() } catch { message = error.localizedDescription }
        }
    }

    /// Restores the stored session at launch.
    func restoreSession() async {
        defer { restoring = false }
        guard !server.isEmpty else { return }
        do {
            if let restored = try await api.restore(server: server) {
                account = restored
                signedIn = true
                _ = trusted.restore(account: restored, server: server)
                await refreshNow()
                startForegroundRefresh()
            }
        } catch {
            message = "Remembered sign-in could not reconnect. Check your network or sign in again."
        }
    }

    /// Sends a code to a new email address or phone number. Returns where it went.
    func requestContactChange(
        _ value: String, password: String, phone: Bool
    ) async throws -> String {
        try await api.requestContactChange(value, password: password, phone: phone)
    }

    /// Uses the new email address or phone number once its code is entered.
    func confirmContactChange(code: String) async throws {
        try await api.confirmContactChange(code: code)
        message = "Your sign-in details were updated."
    }

    /// Signs out: stops sharing, removes the push token, runs onSignOut actions and resets the
    /// state.
    func signOut() {
        tracker.signOut()
        foregroundRefresh?.cancel()
        reportedFindCapability = false
        TripSummaryCache.clear(viewer: viewerCacheId)
        members = []
        places = []
        signOutActions.forEach { $0() }
        signedIn = false
        account = nil
        deviceStatus = "register"
        successfulPushRegistration = nil
        Task {
            try? await trusted.unsubscribePush()
            await api.signOut()
        }
        message = "Signed out. Unsent local GPS data cleared."
    }

    /// Re-checks the device's setup state and, once ready, reloads members and places.
    func refreshNow() async {
        guard !refreshing, let account else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            deviceStatus = try await trusted.status(account: account)
            if deviceStatus == "pending" || deviceStatus == "pairing" {
                pairingCode = (try? await trusted.ownCode()) ?? ""
            } else {
                pairingCode = ""
            }
            if deviceStatus == "ready" {
                let result = try await trusted.snapshot()
                members = result.members
                places = result.places
                let joined = try await trusted.refreshAudience()
                if !joined.isEmpty {
                    joinNotice = joinedMessage(joined)
                    tracker.checkInSoon()
                }
                audience = trusted.audience
                audienceChoices = trusted.choices
                ownerViewerId = trusted.ownerViewerId
                sharing = trusted.sharing
                tracker.updateMonitoring()
                findPhoneEnabled = settings.findPhoneEnabled
                trusted.findPhoneEnabled = findPhoneEnabled
                syncProblem = false
                if findPhoneEnabled && !reportedFindCapability {
                    do { try await trusted.setFindPhone(true); reportedFindCapability = true } catch
                    { /* Try again on next refresh. */  }
                }
                await tracker.drainPending()
                await pollFind(force: true)
                await reportPermissionsIfNeeded()
                await registerPushIfPossible()
            } else {
                members =
                    (try? Wire.array(
                        try await api.accountRequest(
                            "/api/household/members", payload: nil, method: "GET"), "members"))?
                    .compactMap { row in
                        guard let id = row["id"] as? String else { return nil }
                        return HouseholdMember(
                            id: id, name: (row["username"] as? String) ?? "Member")
                    } ?? []
            }
        } catch {
            syncProblem = true
            message = error.localizedDescription
        }
    }

    /// Reports this phone's permission state to the server, at most once a minute unless forced.
    func reportPermissionsIfNeeded(force: Bool = false) async {
        guard signedIn, deviceStatus == "ready",
            force || Date().timeIntervalSince(lastPermissionReport) >= 60
        else { return }
        let notificationsEnabled = await notificationsAllowed()
        do {
            try await trusted.reportDevicePermissions(
                foreground: tracker.locationPermission == .authorizedAlways
                    || tracker.locationPermission == .authorizedWhenInUse,
                background: tracker.locationPermission == .authorizedAlways
                    && tracker.trackingEnabled,
                alarm: findPhoneEnabled, notifications: notificationsEnabled, sharing: sharing)
            lastPermissionReport = Date()
        } catch {
        }
    }

    /// Starts refreshing periodically while the app is in the foreground.
    func startForegroundRefresh() {
        foregroundRefresh?.cancel()
        foregroundRefresh = Task { [weak self] in
            while !Task.isCancelled {
                let interval = self?.mapVisible == true ? 15 : 30
                try? await Task.sleep(for: .seconds(interval))
                guard !Task.isCancelled, let self, self.signedIn else { return }
                self.tracker.finalizeStationaryTripIfNeeded()
                self.tracker.flushDelivery()
                await self.refreshNow()
            }
        }
    }

    /// Checks for a Find My Phone command and reports it as received. The push notification sound
    /// does the ringing.
    func pollFind(force: Bool = false) async {
        guard deviceStatus == "ready", findPhoneEnabled,
            force || Date().timeIntervalSince(lastFindPoll) >= 30
        else { return }
        lastFindPoll = Date()
        do {
            guard let (id, action, expires) = try await trusted.findCommand() else { return }
            await trusted.reportFind(id, state: "received", reason: "")
            if action == "stop" {
                await trusted.reportFind(id, state: "stopped", reason: "remote_stop"); return
            }
            // The push already played the alarm sound, so never ring again here. The status stays
            // "received": APNs accepting a push doesn't prove the phone rang.
            _ = expires
        } catch { /* Network interruptions never allow unsigned commands to ring the phone. */  }
    }

    /// Updates the Find My Phone state after the server reports a change.
    func findPhoneChanged(_ enabled: Bool) {
        findPhoneEnabled = enabled
        reportedFindCapability = enabled
    }

    /// Uploads the push token once notifications are allowed and the device is ready.
    private func registerPushIfPossible() async {
        guard signedIn, deviceStatus == "ready", !pushRegistrationInFlight else { return }
        let notificationAllowed = await notificationsAllowed()
        pushPermission = notificationAllowed
        guard notificationAllowed else { pushSubscribed = false; return }
        if Date().timeIntervalSince(lastAPNsTokenRefresh) >= 1800 {
            lastAPNsTokenRefresh = Date()
            UIApplication.shared.registerForRemoteNotifications()
        }
        guard !pushRegistrationInFlight,
            let device = trusted.identity,
            let data = SecureVault.get("apns-device-token"),
            let token = String(data: data, encoding: .utf8), !token.isEmpty
        else { return }
        // Debug builds use the APNs sandbox; signed release builds use production.
        #if DEBUG
            let environment = "sandbox"
        #else
            let environment = "production"
        #endif
        let registration = "\(device.id):\(environment):\(token)"
        guard successfulPushRegistration != registration else { pushSubscribed = true; return }
        pushRegistrationInFlight = true
        defer { pushRegistrationInFlight = false }
        do {
            try await trusted.subscribePush(token: token, environment: environment)
            successfulPushRegistration = registration
            pushSubscribed = true
        } catch {
            pushSubscribed = false
        }
    }

    /// Re-reads the notification permission.
    func refreshNotificationSettings() {
        Task {
            let settings = await UNUserNotificationCenter.current().notificationSettings()
            pushPermission = [.authorized, .provisional].contains(settings.authorizationStatus)
            notificationPermissionDenied = settings.authorizationStatus == .denied
            timeSensitiveAllowed = settings.timeSensitiveSetting == .enabled
            notificationSoundsAllowed = settings.soundSetting == .enabled
            criticalAlertsAllowed = settings.criticalAlertSetting == .enabled
        }
    }

    /// Returns true if notifications are authorized or provisional.
    private func notificationsAllowed() async -> Bool {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        return [.authorized, .provisional].contains(settings.authorizationStatus)
    }

    /// Requests notification permission and registers for push.
    func requestNotifications() {
        UNUserNotificationCenter.current().requestAuthorization(options: [
            .alert, .badge, .sound, .timeSensitive,
        ]) { approved, _ in
            Task { @MainActor in
                self.pushPermission = approved
                if approved {
                    UIApplication.shared.registerForRemoteNotifications()
                } else {
                    self.pushSubscribed = false
                }
                self.refreshNotificationSettings()
                await self.reportPermissionsIfNeeded(force: true)
            }
        }
    }

    /// Opens this app's page in the Settings app.
    func openSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }

    /// Opens Nära Hem's page in Settings → Notifications, where Time Sensitive is switched on.
    func openNotificationSettings() {
        guard let url = URL(string: UIApplication.openNotificationSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }

    /// Registers an action to run at sign-out, to clear data a screen holds for the account.
    func onSignOut(_ action: @escaping @MainActor () -> Void) {
        signOutActions.append(action)
    }
}
