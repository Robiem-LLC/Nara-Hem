import GoogleMaps
import SwiftUI
import UIKit
import UserNotifications

/// App delegate for launch setup and push registration. The push token is stored locally and only
/// uploaded once this device is a trusted household device.
final class NaraHemAppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    /// Installs the Find My Phone sound, provides the Google Maps key if present, and becomes the
    /// notification center delegate.
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        FindPhoneNotificationSound.installIfNeeded()
        // Builds without a key fall back to Apple Maps.
        if let key = Bundle.main.object(forInfoDictionaryKey: "NARAHEM_GOOGLE_MAPS_IOS_API_KEY")
            as? String,
            key.hasPrefix("AIza"), key.count > 20
        {
            GMSServices.provideAPIKey(key)
        }
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    /// Stores the APNs token in the keychain and notifies the session.
    func application(
        _ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken token: Data
    ) {
        let hex = token.map { String(format: "%02x", $0) }.joined()
        SecureVault.put(Data(hex.utf8), key: "apns-device-token")
        NotificationCenter.default.post(name: .narahemPushRegistered, object: nil)
    }

    /// Notifies the session that push registration failed.
    func application(
        _ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        NotificationCenter.default.post(name: .narahemPushFailed, object: nil)
    }

    /// Shows notifications while the app is in the foreground.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification,
        withCompletionHandler completionHandler:
            @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .badge])
    }
}
