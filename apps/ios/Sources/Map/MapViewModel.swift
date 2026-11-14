import CoreLocation
import Foundation
import Observation

/// View model for the map tab: member positions, including this phone's newer local fix.
@MainActor
@Observable
final class MapViewModel {
    let session: HouseholdSession
    let tracker: LocationTracker
    var members: [HouseholdMember] { session.members }
    var places: [SavedPlace] { session.places }
    var lastFix: LocalLocation? { tracker.lastFix }
    var ownId: String? { session.account?.id }

    /// Whether to show this phone's local marker, until its shared location appears.
    var showsLocalFix: Bool {
        lastFix != nil && !members.contains(where: { $0.id == ownId && $0.lat != nil })
    }

    /// Creates the view model on the shared session.
    init(session: HouseholdSession, tracker: LocationTracker) {
        self.session = session
        self.tracker = tracker
    }

    /// Records whether the map is visible.
    func setVisible(_ visible: Bool) { session.setMapVisible(visible) }

    /// Returns where to draw a member: this phone's newer local fix for its own marker, otherwise
    /// the last shared location.
    func coordinate(for member: HouseholdMember) -> CLLocationCoordinate2D? {
        if member.id == ownId, let fix = lastFix,
            fix.capturedAt.timeIntervalSinceNow >= -90,
            fix.accuracy >= 0 && fix.accuracy <= 75,
            Int64(fix.capturedAt.timeIntervalSince1970 * 1000) > Int64(member.capturedAt)
        {
            return fix.coordinate
        }
        guard let lat = member.lat, let lon = member.lon else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lon)
    }
}
