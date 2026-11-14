import CoreLocation
import CryptoKit
import Foundation
import Security

/// A location reading from this iPhone, with battery state and the trip it belongs to.
struct LocalLocation: Codable, Identifiable {
    let id: UUID
    let latitude: Double
    let longitude: Double
    let accuracy: Double
    let capturedAt: Date
    let speedMps: Double?
    let batteryPct: Int?
    let charging: Bool?
    let tripId: String?

    var coordinate: CLLocationCoordinate2D {
        CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }

    /// Creates a reading from a Core Location fix.
    init(_ sample: CLLocation, tripId: String? = nil, batteryPct: Int? = nil, charging: Bool? = nil)
    {
        id = UUID()
        latitude = sample.coordinate.latitude
        longitude = sample.coordinate.longitude
        accuracy = sample.horizontalAccuracy
        capturedAt = sample.timestamp
        speedMps = sample.speed >= 0 && sample.speed.isFinite ? sample.speed : nil
        self.batteryPct = batteryPct
        self.charging = charging
        self.tripId = tripId
    }
}
