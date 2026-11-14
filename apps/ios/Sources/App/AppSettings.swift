import Foundation

/// Non-secret settings and timestamps stored in UserDefaults, using the keys from earlier versions.
@MainActor
final class AppSettings {
    private let defaults: UserDefaults

    /// Server used for the last sign-in.
    var server: String {
        get { defaults.string(forKey: "narahem.server") ?? "" }
        set { defaults.set(newValue, forKey: "narahem.server") }
    }

    /// Whether background GPS collection is enabled. Requires Always location permission.
    var trackingEnabled: Bool {
        get { defaults.bool(forKey: "narahem.tracking") }
        set { defaults.set(newValue, forKey: "narahem.tracking") }
    }

    /// Whether Find My Phone is enabled. Written when the setting is published.
    var findPhoneEnabled: Bool { defaults.bool(forKey: "narahem.find.enabled") }

    var lastGPSReceivedAt: Date? {
        get { date("narahem.gps.last-received") }
        set { setDate(newValue, "narahem.gps.last-received") }
    }

    var lastGPSUploadedAt: Date? {
        get { date("narahem.gps.last-uploaded") }
        set { setDate(newValue, "narahem.gps.last-uploaded") }
    }

    /// Whether the first-launch location prompt has been shown.
    var askedForLocation: Bool {
        get { defaults.bool(forKey: "narahem.location.initialPrompt") }
        set { defaults.set(newValue, forKey: "narahem.location.initialPrompt") }
    }

    /// Whether the Always location prompt after sign-in has been shown.
    var askedForAlwaysLocation: Bool {
        get { defaults.bool(forKey: "narahem.location.alwaysPrompt") }
        set { defaults.set(newValue, forKey: "narahem.location.alwaysPrompt") }
    }

    /// Creates settings backed by the given UserDefaults.
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    /// Returns a stored date, or nil.
    private func date(_ key: String) -> Date? {
        let seconds = defaults.double(forKey: key)
        return seconds > 0 ? Date(timeIntervalSince1970: seconds) : nil
    }

    /// Stores a date, or removes it when nil.
    private func setDate(_ date: Date?, _ key: String) {
        defaults.set(date?.timeIntervalSince1970 ?? 0, forKey: key)
    }
}
