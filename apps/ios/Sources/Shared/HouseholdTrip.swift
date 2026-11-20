import Foundation

/// A completed trip: times, distance, top speed and route outline.
struct HouseholdTrip: Codable, Identifiable {
    var id: String
    var accountId: String
    var deviceId: String
    var startedAt: Int
    var endedAt: Int
    var distance: Double
    var maxSpeed: Double
    var samples: Int
    var tripId: String?
    var normalized: Bool? = nil
    var matched: Bool? = nil
    var processing: Bool? = nil
    var partial: Bool? = nil
    var start: [Double]? = nil
    var end: [Double]? = nil
    var preview: [[Double]]? = nil
    var originName: String? = nil
    var startLabel: String? = nil
    var endLabel: String? = nil

    /// The time zone the member's phone reported with the trip (or, for older trips, their latest
    /// one), if known.
    var timeZone: String? = nil
}
