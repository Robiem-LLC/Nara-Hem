import CoreLocation
import MapKit
import PhotosUI
import SwiftUI
import UIKit

/// Full-screen trip view with the route on an interactive map.
struct TripDetailMap: View {
    let trip: HouseholdTrip
    let points: [HouseholdTripPoint]
    let places: [SavedPlace]
    let members: [HouseholdMember]
    let onSavePlace: (String, Double, Double, Double, Wire.Object) -> Void
    @State private var saveDestination = false
    @State private var camera: MapCameraPosition = .automatic

    private var route: [CLLocationCoordinate2D] {
        points.filter { point in
            if let tripId = trip.tripId, point.tripId == tripId { return true }
            return point.capturedAt >= trip.startedAt && point.capturedAt <= trip.endedAt
        }.map { CLLocationCoordinate2D(latitude: $0.lat, longitude: $0.lon) }
    }

    var body: some View {
        VStack {
            Map(position: $camera) {
                if route.count > 1 {
                    MapPolyline(coordinates: route).stroke(routeColor, lineWidth: 5)
                }
                if let first = route.first { Marker("Start", coordinate: first).tint(tripStart) }
                if let last = route.last { Marker("End", coordinate: last).tint(tripEnd) }
            }
            .onAppear { frameRoute() }
            .onChange(of: route.count) { _, _ in frameRoute() }
            HStack {
                Text(String(format: "%.2f miles", trip.distance / 1609.344))
                Spacer()
                Text("Max \(Int(trip.maxSpeed * 2.23694)) mph")
            }.padding()
            if let destination = route.last,
                !places.contains(where: { place in
                    CLLocation(latitude: destination.latitude, longitude: destination.longitude)
                        .distance(from: CLLocation(latitude: place.lat, longitude: place.lon))
                        <= place.radius
                })
            {
                Button("Save Place at destination") { saveDestination = true }
                    .foregroundStyle(accent)
                    .padding(.horizontal)
            }
            if route.isEmpty {
                Text("No decryptable route samples for this trip.").foregroundStyle(.secondary)
            }
        }
        .sheet(isPresented: $saveDestination) {
            PlaceEditor(
                existing: nil, members: members,
                initialCoordinate: route.last
            ) { name, lat, lon, radius, alerts in
                onSavePlace(name, lat, lon, radius, alerts)
                saveDestination = false
            }
        }
    }

    /// Fits the whole route on screen.
    private func frameRoute() {
        guard !route.isEmpty else { return }
        let minLat = route.map(\.latitude).min()!, maxLat = route.map(\.latitude).max()!
        let minLon = route.map(\.longitude).min()!, maxLon = route.map(\.longitude).max()!
        camera = .region(
            MKCoordinateRegion(
                center: CLLocationCoordinate2D(
                    latitude: (minLat + maxLat) / 2, longitude: (minLon + maxLon) / 2),
                span: MKCoordinateSpan(
                    latitudeDelta: max(0.008, (maxLat - minLat) * 1.5),
                    longitudeDelta: max(0.008, (maxLon - minLon) * 1.5))))
    }
}
