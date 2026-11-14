import CoreLocation
import GoogleMaps
import SwiftUI
import UIKit

/// Whether Google Maps is available. It is used when the build includes an iOS-restricted API key;
/// otherwise the app uses MapKit.
enum GoogleMapsConfiguration {
    static var enabled: Bool {
        guard
            let key = Bundle.main.object(forInfoDictionaryKey: "NARAHEM_GOOGLE_MAPS_IOS_API_KEY")
                as? String
        else { return false }
        return key.hasPrefix("AIza") && key.count > 20
    }
}
