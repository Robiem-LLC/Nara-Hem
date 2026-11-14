import SwiftUI

/// Trips tab: member picker and that member's trips and stops.
struct TripsScreen: View {
    let model: TripsViewModel

    /// Used to save a stop as a place.
    let places: PlacesViewModel
    @State private var selectedTrip: HouseholdTrip?

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 16) {
                Text("Trips and stops").font(.largeTitle.weight(.regular))
                Text("Choose a household member to view trip history.")
                    .font(.subheadline).foregroundStyle(subdued)
                ScrollView(.horizontal) {
                    HStack(spacing: 8) {
                        ForEach(model.session.members) { member in
                            Button(member.name) {
                                model.loadTrips(memberId: member.id, days: model.tripDays)
                            }
                            .buttonStyle(NaraHemChip(selected: model.selectedMemberId == member.id))
                        }
                    }
                }.scrollIndicators(.hidden)
                HStack(spacing: 8) {
                    ForEach([1, 7, 14], id: \.self) { days in
                        Button(days == 1 ? "Day" : "\(days) days") {
                            if let id = model.selectedMemberId ?? model.session.members.first?.id {
                                model.loadTrips(memberId: id, days: days)
                            }
                        }.buttonStyle(NaraHemChip(selected: model.tripDays == days))
                    }
                }
                if model.tripHistoryPartial {
                    Label(
                        "Some history is outside this range; gaps are not reconstructed.",
                        systemImage: "exclamationmark.triangle"
                    )
                    .font(.footnote).foregroundStyle(warn)
                }
                ForEach(model.visibleTrips) { trip in
                    TripHistoryRow(
                        trip: trip, viewerId: model.session.viewerCacheId,
                        places: model.session.places,
                        loadDetails: { await model.cardPreview(for: $0) },
                        open: { selectedTrip = $0 })
                }
                if model.visibleTrips.isEmpty {
                    Text("No trips")
                        .foregroundStyle(subdued)
                        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
                        .cardStyle()
                }
                Text(
                    """
                    Routes and stops show only recorded observations. Missing history cannot \
                    be reconstructed.
                    """
                )
                .font(.footnote).foregroundStyle(subdued)
                NoticeView(session: model.session)
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(AppBackground())
        .toolbar(.hidden, for: .navigationBar)
        .sheet(item: $selectedTrip) { trip in
            NavigationStack {
                TripDetailMap(
                    trip: trip, points: model.tripPoints,
                    places: model.session.places, members: model.session.members,
                    onSavePlace: { name, lat, lon, radius, alerts in
                        places.savePlace(
                            name: name, lat: lat, lon: lon,
                            radius: radius, existing: nil, alerts: alerts)
                    }
                )
                .navigationTitle("Trip route")
                .onAppear { model.loadTripRoute(trip) }
                .overlay {
                    if model.isLoadingTripRoute {
                        ProgressView("Loading route").padding()
                            .background(panel, in: RoundedRectangle(cornerRadius: 12))
                    }
                }
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { selectedTrip = nil }
                    }
                }
            }.presentationDetents([.large])
        }
        .onAppear { model.openTrips() }
        .task { await model.refreshWhileOpen() }
        .onChange(of: model.trips.map(\.distance)) { _, _ in
            if let id = selectedTrip?.id, let updated = model.trips.first(where: { $0.id == id }) {
                selectedTrip = updated
            }
        }
    }
}

#if DEBUG
    #Preview {
        let preview = AppViewModel.preview()
        TripsScreen(model: preview.trips, places: preview.places)
    }
#endif
