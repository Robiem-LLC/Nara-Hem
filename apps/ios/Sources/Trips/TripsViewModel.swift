import CoreLocation
import Foundation
import Observation

/// View model for the Trips tab: the trip list, card previews and full routes.
@MainActor
@Observable
final class TripsViewModel {
    var trips: [HouseholdTrip] = []
    var tripPoints: [HouseholdTripPoint] = []
    var isLoadingTripRoute = false
    var tripRouteError = ""
    var selectedMemberId: String?
    var tripDays = 1
    var tripHistoryPartial = false
    var roadMatchingEnabled: Bool?
    var indexedProcessingEnabled: Bool?
    let session: HouseholdSession
    private let household: HouseholdService
    @ObservationIgnored private var tripListRevision = 0
    @ObservationIgnored private var requestedTripRouteId: String?

    var visibleTrips: [HouseholdTrip] {
        trips.filter { !($0.distance < 30 && $0.endedAt - $0.startedAt < 120_000) }
    }

    /// Creates the view model on the shared session.
    init(session: HouseholdSession, household: HouseholdService) {
        self.session = session
        self.household = household
        session.onSignOut { [weak self] in
            self?.selectedMemberId = nil
            self?.trips = []
            self?.tripPoints = []
            self?.roadMatchingEnabled = nil
            self?.indexedProcessingEnabled = nil
        }
    }

    /// Selects the first member if none is selected.
    func openTrips() {
        if selectedMemberId == nil, let first = session.members.first {
            loadTrips(memberId: first.id, days: tripDays)
        }
    }

    /// Reloads the selected member's trips every 25 seconds until the task is cancelled.
    func refreshWhileOpen() async {
        while !Task.isCancelled {
            do { try await Task.sleep(for: .seconds(25)) } catch { break }
            if let id = selectedMemberId ?? session.members.first?.id {
                loadTrips(memberId: id, days: tripDays)
            }
        }
    }

    /// Shows cached trips immediately, then loads fresh ones from the server.
    func loadTrips(memberId: String, days: Int = 1) {
        let changed = selectedMemberId != memberId || tripDays != days
        selectedMemberId = memberId
        tripDays = days
        let viewer = session.viewerCacheId
        if changed || trips.isEmpty {
            trips = withZone(
                TripSummaryCache.load(viewer: viewer, member: memberId, days: days), memberId)
            tripPoints = []
        }
        tripListRevision += 1
        let revision = tripListRevision
        Task {
            do {
                let (fresh, _, processing, matching) = try await household.trips(
                    accountId: memberId, days: days)
                TripSummaryCache.save(fresh, viewer: viewer, member: memberId, days: days)
                if revision == tripListRevision && selectedMemberId == memberId && tripDays == days
                {
                    trips = withZone(fresh, memberId)
                    indexedProcessingEnabled = processing
                    roadMatchingEnabled = matching
                    session.message = ""
                }
            } catch {
                if revision == tripListRevision && trips.isEmpty {
                    session.message = "Trip refresh unavailable: \(error.localizedDescription)"
                }
            }
        }
    }

    /// Gives trips without their own time zone the member's latest one, so their times can show
    /// the member's own clock too.
    private func withZone(_ list: [HouseholdTrip], _ memberId: String) -> [HouseholdTrip] {
        let zone = session.members.first { $0.id == memberId }?.timeZone
        return list.map { trip in
            var trip = trip
            if trip.timeZone == nil { trip.timeZone = zone }
            return trip
        }
    }

    /// Returns the trip with its outline and endpoints, loading them for older trips that lack
    /// them. Results are cached on the device.
    func cardPreview(for trip: HouseholdTrip) async -> HouseholdTrip {
        var summary = trip
        let viewer = session.viewerCacheId
        if summary.preview == nil || summary.start == nil || summary.end == nil {
            if let cached = TripSummaryCache.cachedDetails(for: trip, viewer: viewer) {
                if summary.preview == nil { summary.preview = cached.preview }
                if summary.start == nil { summary.start = cached.start }
                if summary.end == nil { summary.end = cached.end }
                if summary.originName == nil { summary.originName = cached.originName }
            }
        }
        if let preview = summary.preview, preview.count >= 2,
            summary.start != nil && summary.end != nil
        {
            return summary
        }
        guard session.signedIn, session.deviceStatus == "ready", !session.viewerCacheId.isEmpty
        else { return summary }
        do {
            let fixes = try await household.tripRoute(summary).sorted {
                $0.capturedAt < $1.capturedAt
            }
            guard !Task.isCancelled else { return summary }
            let valid = fixes.filter {
                $0.lat.isFinite && $0.lon.isFinite && (-90...90).contains($0.lat)
                    && (-180...180).contains($0.lon)
            }
            guard valid.count >= 2 else { return summary }
            var outline: [[Double]] = []
            let step = max(1, (valid.count + 99) / 100)
            var previous: HouseholdTripPoint?
            for index in valid.indices where index % step == 0 || index == valid.count - 1 {
                let fix = valid[index]
                if let previous {
                    let seconds = Double(fix.capturedAt - previous.capturedAt) / 1000
                    if seconds > 120 || seconds <= 0 {
                        if !outline.isEmpty && !outline.last!.isEmpty { outline.append([]) }
                    } else {
                        let before = CLLocation(latitude: previous.lat, longitude: previous.lon)
                        let after = CLLocation(latitude: fix.lat, longitude: fix.lon)
                        if before.distance(from: after) > max(150, 65 * seconds) {
                            if !outline.isEmpty && !outline.last!.isEmpty { outline.append([]) }
                        }
                    }
                }
                outline.append([fix.lat, fix.lon])
                previous = fix
            }
            summary.preview = outline
            summary.start = [valid[0].lat, valid[0].lon]
            summary.end = [valid[valid.count - 1].lat, valid[valid.count - 1].lon]
            if !Task.isCancelled {
                TripSummaryCache.storeDetails(summary, viewer: session.viewerCacheId)
            }
        } catch {
        }
        return summary
    }

    /// Loads a trip's full route.
    func loadTripRoute(_ trip: HouseholdTrip) {
        if requestedTripRouteId == trip.id && !tripPoints.isEmpty { return }
        requestedTripRouteId = trip.id
        tripPoints = []
        isLoadingTripRoute = true
        tripRouteError = ""
        Task {
            do {
                let points = try await household.tripRoute(trip)
                guard requestedTripRouteId == trip.id else { return }
                tripPoints = points
            } catch {
                if requestedTripRouteId == trip.id { tripRouteError = error.localizedDescription }
            }
            if requestedTripRouteId == trip.id { isLoadingTripRoute = false }
        }
    }
}
