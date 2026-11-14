import CoreLocation
import MapKit

/// Opens driving directions in Apple Maps. The household server never receives the destination.
@MainActor
enum ExternalDirections {
    /// Opens Apple Maps with driving directions to the coordinates.
    static func open(lat: Double, lon: Double) {
        MKMapItem(
            placemark: MKPlacemark(
                coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lon))
        )
        .openInMaps(launchOptions: [
            MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDriving
        ])
    }
}
