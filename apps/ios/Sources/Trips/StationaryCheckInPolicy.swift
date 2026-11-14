import CoreLocation
import Foundation

/// Sampling rules for parked phones. Check-ins always use a new Core Location fix, never a cached
/// position with a new timestamp.
enum StationaryCheckInPolicy {
    /// Distance filter while parked, so Core Location only reports after real movement.
    static let parkedDistanceFilter: CLLocationDistance = 25

    /// Interval between check-in fixes while parked.
    static let parkedCheckInSeconds: TimeInterval = 900

    /// Returns the distance filter for the tracking state.
    static func distanceFilter(enabled: Bool) -> CLLocationDistance {
        enabled ? kCLDistanceFilterNone : 35
    }

    /// Returns the minimum time between queued fixes for the current state.
    static func minimumSampleInterval(
        activeTrip: Bool, stationaryCheckIns: Bool,
        speed: CLLocationSpeed
    ) -> TimeInterval {
        if speed >= 10.73 { return 4 }  // > 24 mph
        if speed >= 2.24 { return 9 }  // 5–24 mph
        if activeTrip || speed >= 0.8 { return 15 }
        if stationaryCheckIns && speed >= 0 && speed < 0.8 { return parkedCheckInSeconds }
        return 90
    }

    /// Returns true if a fix is recent and accurate enough for a parked check-in.
    static func isUsable(_ fix: CLLocation, now: Date = Date()) -> Bool {
        fix.horizontalAccuracy >= 0 && fix.horizontalAccuracy <= 2_000
            && abs(fix.timestamp.timeIntervalSince(now)) <= 300
    }
}
