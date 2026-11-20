import Foundation

/// A household member as shown on the map: latest shared location, photo and battery.
struct HouseholdMember: Identifiable {
    var id: String
    var name: String
    var lat: Double? = nil
    var lon: Double? = nil
    var accuracy: Double? = nil
    var capturedAt: Int = 0
    var photo: String? = nil
    var speed: Double? = nil
    var battery: Int? = nil
    var charging: Bool? = nil
    var tripId: String? = nil

    /// When the member stopped moving, and when any of their devices last contacted the server, in
    /// milliseconds.
    var stillSince: Int? = nil
    var lastContact: Int? = nil

    /// The time zone the member's phone reported with this location, if it sent one.
    var timeZone: String? = nil
}
