import Foundation

/// A point on a trip's route.
struct HouseholdTripPoint: Identifiable {
    var id: String
    var lat: Double
    var lon: Double
    var capturedAt: Int
    var tripId: String?
}
