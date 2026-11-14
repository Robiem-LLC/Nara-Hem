import GoogleMaps
import SwiftUI
import UIKit
import UserNotifications

/// The app entry point.
@main
struct NaraHemApp: App {
    /// App delegate, needed for push registration callbacks.
    @UIApplicationDelegateAdaptor(NaraHemAppDelegate.self) private var delegate

    /// The app's view models, created once. Creating them starts session restore.
    @State private var app = AppViewModel()

    var body: some Scene {
        WindowGroup {
            RootView(app: app)
                .preferredColorScheme(.dark)
                .tint(accent)
        }
    }
}

/// Notifications posted by the app delegate after push registration.
extension Notification.Name {
    static let narahemPushRegistered = Notification.Name("narahem.push.registered")
    static let narahemPushFailed = Notification.Name("narahem.push.failed")
}
