import CoreLocation
import MapKit
import PhotosUI
import SwiftUI
import UIKit

/// Trip card in the list. The route outline loads when the card scrolls into view and is cached on
/// the device. Tapping opens the full route.
struct TripHistoryRow: View {
    let trip: HouseholdTrip
    let viewerId: String
    let places: [SavedPlace]
    let loadDetails: (HouseholdTrip) async -> HouseholdTrip
    let open: (HouseholdTrip) -> Void
    @State private var enriched: HouseholdTrip?

    private var shown: HouseholdTrip {
        guard let enriched, enriched.id == trip.id else { return trip }
        var latest = trip
        if latest.start == nil { latest.start = enriched.start }
        if latest.end == nil { latest.end = enriched.end }
        if latest.preview == nil { latest.preview = enriched.preview }
        if latest.originName == nil { latest.originName = enriched.originName }
        return latest
    }

    var body: some View {
        Button {
            open(shown)
        } label: {
            VStack(alignment: .leading, spacing: 12) {
                Text(
                    Date(timeIntervalSince1970: Double(shown.startedAt) / 1000)
                        .formatted(date: .abbreviated, time: .omitted)
                )
                .font(.headline)
                TripPreviewImage(trip: shown, viewerId: viewerId)
                TripEndpointsLabel(trip: shown, points: [], places: places)
                HStack(spacing: 14) {
                    Text(String(format: "%.2f mi", shown.distance / 1609.344))
                    Text("\(Int(shown.maxSpeed * 2.23694)) mph peak")
                }.font(.caption).foregroundStyle(subdued)
                if shown.partial == true {
                    Text("Partial GPS observations").font(.caption).foregroundStyle(warn)
                }
                Label("Tap preview to open interactive map", systemImage: "map")
                    .foregroundStyle(accent).font(.footnote.weight(.semibold))
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .cardStyle()
        }
        .buttonStyle(.plain)
        .task(id: "\(viewerId):\(trip.id):\(trip.preview?.count ?? 0)") {
            enriched = await loadDetails(trip)
        }
    }
}
