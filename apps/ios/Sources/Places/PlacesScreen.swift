import CoreLocation
import SwiftUI

/// Places tab: the saved places list. Tapping a place opens the editor.
struct PlacesScreen: View {
    let model: PlacesViewModel
    @State private var editingPlace: SavedPlace?
    @State private var showingPlace = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text("Places").font(.largeTitle.weight(.regular))
                    Spacer()
                    Button("Add a Place") {
                        editingPlace = nil
                        showingPlace = true
                    }
                    .buttonStyle(NaraHemPrimaryButton(compact: true))
                    .disabled(model.session.busy)
                }
                Text("Their boundaries define arrivals and departures.")
                    .font(.subheadline).foregroundStyle(subdued)
                if model.session.places.isEmpty {
                    Text(
                        "No saved places yet. Add Home, School, Work, or anywhere you visit often."
                    )
                    .foregroundStyle(subdued)
                }
                ForEach(model.session.places) { place in
                    let overlaps = model.overlaps(of: place)
                    HStack(spacing: 12) {
                        Image(systemName: "house").font(.title2)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(place.name).font(.headline)
                            if !overlaps.isEmpty {
                                Text(
                                    """
                                    Overlaps \(overlaps.map(\.name).joined(separator: ", ")). \
                                    Edit the boundary or delete a duplicate.
                                    """
                                )
                                .font(.caption).foregroundStyle(dangerText)
                            }
                            Text(
                                """
                                \(Int(place.radius)) m radius · \
                                \(String(format: "%.5f, %.5f", place.lat, place.lon))
                                """
                            )
                            .font(.caption).foregroundStyle(subdued)
                        }
                        Spacer(minLength: 8)
                        Button {
                            ExternalDirections.open(lat: place.lat, lon: place.lon)
                        } label: {
                            Label("Directions", systemImage: "arrow.triangle.turn.up.right.diamond")
                                .lineLimit(1).fixedSize()
                        }
                        .buttonStyle(NaraHemOutlineButton())
                        .layoutPriority(1)
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .cardStyle()
                    .contentShape(RoundedRectangle(cornerRadius: 14))
                    .onTapGesture {
                        editingPlace = place
                        showingPlace = true
                    }
                    .disabled(model.session.busy)
                }
                NoticeView(session: model.session)
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(AppBackground())
        .toolbar(.hidden, for: .navigationBar)
        .sheet(isPresented: $showingPlace) {
            PlaceEditor(
                existing: editingPlace, members: model.session.members,
                initialCoordinate: model.newPlaceCoordinate,
                onDelete: editingPlace.map { place in
                    {
                        model.deletePlace(place)
                        showingPlace = false
                    }
                }
            ) { name, lat, lon, radius, alerts in
                model.savePlace(
                    name: name, lat: lat, lon: lon, radius: radius,
                    existing: editingPlace, alerts: alerts)
                showingPlace = false
            }
        }
    }
}

#if DEBUG
    #Preview {
        PlacesScreen(model: AppViewModel.preview().places)
    }
#endif
