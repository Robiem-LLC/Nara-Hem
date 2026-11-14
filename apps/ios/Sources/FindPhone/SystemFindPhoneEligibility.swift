import AlarmKit
import Foundation
import SwiftUI

// PARKED: kept for a possible future version. Nothing in the app calls it; iPhones only get
// the Find My Phone push notification sound.

/// Decides whether the AlarmKit alarm may be used. Not used (see the PARKED note above).
enum SystemFindPhoneEligibility {
    static let preferenceKey = "narahem.find.system-alarm-enabled"

    /// Returns true if a verified command allows scheduling a system alarm on this device.
    static func canSchedule(
        optedIn: Bool, authorized: Bool,
        commandExpires: Int, now: Int
    ) -> Bool {
        optedIn && authorized && commandExpires - now >= 4
    }
}
