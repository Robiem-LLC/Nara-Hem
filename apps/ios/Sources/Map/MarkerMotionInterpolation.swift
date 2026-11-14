import CoreLocation
import GoogleMaps
import SwiftUI
import UIKit

/// Animates markers between fixes. Only interpolates between real fixes, never past the latest one.
enum MarkerMotionInterpolation {
    /// Returns the animation duration for the time between two fixes.
    static func duration(secondsBetweenFixes: Double) -> Double {
        guard secondsBetweenFixes.isFinite && secondsBetweenFixes > 0 else { return 0 }
        return min(12, max(0.5, secondsBetweenFixes * 0.8))
    }

    /// Returns the interpolated position at a point in the animation.
    static func position(
        from: CLLocationCoordinate2D, to: CLLocationCoordinate2D,
        progress: Double
    ) -> CLLocationCoordinate2D {
        let fraction = min(1, max(0, progress))
        return CLLocationCoordinate2D(
            latitude: from.latitude + (to.latitude - from.latitude) * fraction,
            longitude: from.longitude + (to.longitude - from.longitude) * fraction)
    }
}
