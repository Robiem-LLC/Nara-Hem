import CoreLocation
import Foundation
import Observation

/// View model for the Places tab: adding, editing and deleting saved places.
@MainActor
@Observable
final class PlacesViewModel {
    let session: HouseholdSession
    private let household: HouseholdService
    private let tracker: LocationTracker

    /// Starting position for a new place: this phone's fix, otherwise this member's shared
    /// location.
    var newPlaceCoordinate: CLLocationCoordinate2D? {
        if let fix = tracker.lastFix { return fix.coordinate }
        guard let member = session.members.first(where: { $0.id == session.account?.id }),
            let lat = member.lat, let lon = member.lon
        else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lon)
    }

    /// Creates the view model on the shared session.
    init(session: HouseholdSession, household: HouseholdService, tracker: LocationTracker) {
        self.session = session
        self.household = household
        self.tracker = tracker
    }

    /// Returns the other places whose circles overlap this one.
    func overlaps(of place: SavedPlace) -> [SavedPlace] {
        session.places.filter { other in
            other.id != place.id
                && CLLocation(latitude: place.lat, longitude: place.lon)
                    .distance(from: CLLocation(latitude: other.lat, longitude: other.lon))
                    < place.radius + other.radius
        }
    }

    /// Saves a new or edited place and refreshes.
    func savePlace(
        name: String, lat: Double, lon: Double, radius: Double, existing: SavedPlace?,
        alerts: Wire.Object = [:]
    ) {
        session.work {
            try await self.household.savePlace(
                name: name, lat: lat, lon: lon, radius: radius,
                existing: existing, alerts: alerts)
            self.session.places = self.household.places
            self.session.message = "Place saved for your household."
        }
    }

    /// Deletes a place for the whole household.
    func deletePlace(_ place: SavedPlace) {
        session.work {
            try await self.household.deletePlace(place)
            self.session.places = self.household.places
            self.session.message = "Place deleted."
        }
    }
}
