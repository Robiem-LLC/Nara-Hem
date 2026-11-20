import CoreLocation
import MapKit
import PhotosUI
import SwiftUI
import UIKit

/// Shows "From → To" for a trip using the server's labels, saved places or street addresses.
struct TripEndpointsLabel: View {
    let trip: HouseholdTrip
    let points: [HouseholdTripPoint]
    let places: [SavedPlace]
    @State private var origin = "Location unavailable"
    @State private var destination = "Location unavailable"

    /// Changes when the trip's endpoints or labels change, so the names are looked up again.
    private var refreshKey: String {
        [
            trip.id, trip.start?.description ?? "", trip.end?.description ?? "",
            trip.originName ?? "", trip.startLabel ?? "", trip.endLabel ?? "",
        ].joined(separator: ":")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "circle.fill").font(.caption2).foregroundStyle(accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(
                        origin == "Location unavailable"
                            ? "Departure location unavailable" : "Left from \(origin)"
                    )
                    .font(.subheadline.weight(.semibold))
                    Text(ZoneTimes.format(trip.startedAt, zone: trip.timeZone))
                    .font(.caption).foregroundStyle(.secondary)
                }
            }
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "mappin.circle.fill").foregroundStyle(accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(
                        destination == "Location unavailable"
                            ? "Arrival location unavailable" : "Arrived at \(destination)"
                    )
                    .font(.subheadline.weight(.semibold))
                    Text(ZoneTimes.format(trip.endedAt, zone: trip.timeZone))
                    .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .task(id: refreshKey) {
            origin = "Location unavailable"
            destination = "Location unavailable"
            let beginning =
                sample(trip.start, time: trip.startedAt)
                ?? points.min(by: { $0.capturedAt < $1.capturedAt })
            let ending =
                sample(trip.end, time: trip.endedAt)
                ?? points.max(by: { $0.capturedAt < $1.capturedAt })
            if let start = trip.startLabel {
                origin = start
            } else if let known = trip.originName, !known.isEmpty {
                origin = known
            } else if let beginning {
                origin = await label(beginning)
            }
            if let end = trip.endLabel {
                destination = end
            } else if let ending {
                destination = await label(ending)
            }
        }
    }

    /// Converts a [lat, lon] pair to a route point.
    private func sample(_ pair: [Double]?, time: Int) -> HouseholdTripPoint? {
        guard let pair, pair.count == 2 else { return nil }
        return HouseholdTripPoint(
            id: "", lat: pair[0], lon: pair[1],
            capturedAt: time, tripId: trip.tripId)
    }

    /// Returns a name for a point: saved place, street address or coordinates.
    private func label(_ point: HouseholdTripPoint) async -> String {
        let location = CLLocation(latitude: point.lat, longitude: point.lon)
        if let saved = places.first(where: {
            location.distance(from: CLLocation(latitude: $0.lat, longitude: $0.lon))
                <= $0.radius + 35
        }) {
            return saved.name
        }
        if let marks = try? await CLGeocoder().reverseGeocodeLocation(location),
            let mark = marks.first
        {
            if let street = mark.thoroughfare {
                let number = mark.subThoroughfare.map { $0 + " " } ?? ""
                return number + street
            }
            if let name = mark.name { return name }
            if let locality = mark.locality { return locality }
        }
        return "Location unavailable"
    }
}
