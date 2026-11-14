import CoreLocation
import MapKit
import SwiftUI

/// Map tab: the household map and the member drawer.
struct HouseholdMapScreen: View {
    let model: MapViewModel

    /// Opens the Trips tab for a member.
    let onViewTrips: (String) -> Void
    @State private var camera: MapCameraPosition = .automatic
    @State private var drawerHeight: CGFloat = 250
    @State private var dragStartHeight: CGFloat?
    @State private var mapHeight: CGFloat = 550
    @State private var focusRevision = 0
    @State private var followPaused = false
    @State private var selectedMember: String?

    var body: some View {
        GeometryReader { geometry in
            let available = max(240, geometry.size.height)
            let occupied = min(max(112, drawerHeight), max(112, available - 115))
            ZStack(alignment: .bottom) {
                mapContent(bottomInset: occupied, height: available)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                householdDrawer(maximum: available - 115)
                    .frame(height: occupied)
                    .frame(maxWidth: .infinity)
                    .background(
                        midnight,
                        in: UnevenRoundedRectangle(topLeadingRadius: 20, topTrailingRadius: 20)
                    )
                    .shadow(color: .black.opacity(0.35), radius: 9, y: -3)
            }
            .onAppear {
                mapHeight = available
                if selectedMember == nil { centerOnHousehold() }
            }
            .onChange(of: geometry.size.height) { _, new in mapHeight = max(new, 240) }
        }
        .toolbar(.hidden, for: .navigationBar)
        .onAppear { model.setVisible(true) }
        .onDisappear { model.setVisible(false) }
        .onChange(of: model.members.map(\.id)) { _, _ in
            if selectedMember == nil { centerOnHousehold() }
        }
    }

    @MapContentBuilder
    private var forEachPlaceBoundaries: some MapContent {
        ForEach(model.places) { place in
            MapCircle(
                center: CLLocationCoordinate2D(latitude: place.lat, longitude: place.lon),
                radius: place.radius
            )
            .foregroundStyle(placeColor.opacity(0.12))
            .stroke(placeColor.opacity(0.85), lineWidth: 2)
        }
    }

    /// The map: Google Maps when available, otherwise MapKit.
    @ViewBuilder
    private func mapContent(bottomInset: CGFloat, height: CGFloat) -> some View {
        if GoogleMapsConfiguration.enabled {
            GoogleHouseholdMap(
                members: model.members, places: model.places,
                localFix: model.lastFix, ownPersonId: model.ownId,
                selectedMemberId: selectedMember, focusRevision: focusRevision,
                occludedBottom: bottomInset,
                onMemberTapped: { id in
                    chooseMember(id)
                }, onFollowPaused: { followPaused = true }
            )
            .ignoresSafeArea(edges: .bottom)
            .overlay(alignment: .topTrailing) {
                if let selectedMember, followPaused {
                    Button {
                        chooseMember(selectedMember)
                    } label: {
                        Label("Resume follow", systemImage: "location.north.line.fill")
                            .font(.callout.weight(.semibold))
                            .padding(10)
                            .background(panel, in: Capsule())
                    }.padding(12)
                }
            }
        } else {
            let fan = AvatarFan.layout(model.members, places: model.places, size: 42)
            Map(position: $camera) {
                ForEach(model.members) { member in
                    if let coordinate = model.coordinate(for: member) {
                        let offset = fan[member.id] ?? AvatarFan.Offset()
                        Annotation(member.name, coordinate: coordinate) {
                            Button {
                                chooseMember(member.id)
                            } label: {
                                ProfileAvatar(member: member)
                                    .frame(width: 42, height: 42)
                                    .background(accent.opacity(0.28), in: Circle())
                                    .overlay(Circle().stroke(accent, lineWidth: 2))
                            }
                            .offset(x: offset.dx, y: offset.dy)
                        }
                        .annotationTitles(offset.groupSize > 1 ? .hidden : .automatic)
                    }
                }
                forEachPlaceBoundaries
                if let fix = model.lastFix,
                    !model.members.contains(where: { $0.id == model.ownId && $0.lat != nil })
                {
                    Marker(
                        "This iPhone (local)", systemImage: "location.circle.fill",
                        coordinate: fix.coordinate
                    )
                    .tint(myLocation)
                }
            }
            .mapControls {
                MapCompass(); MapScaleView()
            }
            .onChange(of: bottomInset) { _, _ in
                if !followPaused,
                    let member = model.members.first(where: { $0.id == selectedMember })
                {
                    focusOn(member)
                }
            }
            .onChange(of: model.members.first(where: { $0.id == selectedMember })?.capturedAt) {
                _, _ in
                if !followPaused,
                    let member = model.members.first(where: { $0.id == selectedMember })
                {
                    withAnimation(.easeInOut(duration: 0.8)) { focusOn(member) }
                }
            }
        }
    }

    /// Pull-up drawer with the member list.
    private func householdDrawer(maximum: CGFloat) -> some View {
        VStack(spacing: 0) {
            VStack(spacing: 8) {
                Capsule().fill(.secondary).frame(width: 42, height: 5).padding(.top, 9)
                HStack {
                    if selectedMember != nil {
                        Button {
                            selectedMember = nil
                        } label: {
                            Label("Household", systemImage: "chevron.left")
                        }
                    } else {
                        Text("Household").font(.headline)
                    }
                    Spacer()
                    Text("\(model.members.count) members").font(.footnote).foregroundStyle(
                        .secondary)
                    Image(systemName: "line.3.horizontal.decrease").foregroundStyle(.secondary)
                }
                .padding(.horizontal, 18)
            }
            .frame(maxWidth: .infinity)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 3)
                    .onChanged { value in
                        if dragStartHeight == nil { dragStartHeight = drawerHeight }
                        drawerHeight = min(
                            max(112, (dragStartHeight ?? drawerHeight) - value.translation.height),
                            max(112, maximum))
                    }
                    .onEnded { _ in dragStartHeight = nil })
            Divider().padding(.top, 8)
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let selectedMember,
                        let member = model.members.first(where: { $0.id == selectedMember })
                    {
                        memberDrawerDetails(member)
                    } else {
                        ForEach(model.members) { member in
                            Button {
                                chooseMember(member.id)
                            } label: {
                                HStack(spacing: 12) {
                                    ProfileAvatar(member: member).frame(width: 44, height: 44)
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(member.name).font(.headline)
                                        Text(
                                            member.lat == nil
                                                ? "Waiting for shared location"
                                                : (member.capturedAt == 0
                                                    ? "Location available"
                                                    : LocationFreshness.of(member).text)
                                        )
                                        .font(.caption).foregroundStyle(.secondary)
                                        if let battery = member.battery {
                                            Text("Battery \(battery)%").font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    Spacer()
                                    Image(systemName: "chevron.right").foregroundStyle(.secondary)
                                }
                                .contentShape(Rectangle())
                            }.buttonStyle(.plain)
                            Divider()
                        }
                    }
                    if model.session.syncProblem {
                        Label(
                            "Showing last verified data — reconnect to refresh",
                            systemImage: "wifi.exclamationmark"
                        )
                        .font(.caption).foregroundStyle(warn)
                    }
                    NoticeView(session: model.session)
                }.padding(16)
            }.scrollIndicators(.hidden)
        }
        .accessibilityIdentifier("household-draggable-drawer")
    }

    /// Details for one member in the drawer.
    private func memberDrawerDetails(_ member: HouseholdMember) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                ProfileAvatar(member: member).frame(width: 60, height: 60)
                VStack(alignment: .leading, spacing: 5) {
                    Text(member.name).font(.title3.bold())
                    Text(
                        member.capturedAt == 0
                            ? "No shared GPS yet" : LocationFreshness.of(member).text
                    )
                    .font(.caption).foregroundStyle(.secondary)
                }
            }
            if let accuracy = member.accuracy {
                LabeledContent("Accuracy", value: "\(Int(accuracy)) m")
            }
            if let speed = member.speed {
                LabeledContent("Speed", value: "\(Int(speed * 2.23694)) mph")
            }
            if let battery = member.battery { LabeledContent("Battery", value: "\(battery)%") }
            HStack {
                Button("View trips") { onViewTrips(member.id) }
                    .buttonStyle(.borderedProminent)
                if let lat = member.lat, let lon = member.lon {
                    Button("Directions") { ExternalDirections.open(lat: lat, lon: lon) }
                        .buttonStyle(.bordered)
                }
            }
            if member.lat == nil { Text("Waiting for location.").foregroundStyle(.secondary) }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Selects a member and moves the map to them.
    private func chooseMember(_ id: String) {
        selectedMember = id
        followPaused = false
        drawerHeight = max(drawerHeight, 360)
        focusRevision += 1
        if let member = model.members.first(where: { $0.id == id }) { focusOn(member) }
    }

    /// Fits every member on screen.
    private func centerOnHousehold() {
        let coords = model.members.compactMap { person -> CLLocationCoordinate2D? in
            guard let lat = person.lat, let lon = person.lon else { return nil }
            return CLLocationCoordinate2D(latitude: lat, longitude: lon)
        }
        let points = coords.isEmpty ? model.lastFix.map { [$0.coordinate] } ?? [] : coords
        guard !points.isEmpty else { return }
        let minLat = points.map(\.latitude).min()!, maxLat = points.map(\.latitude).max()!
        let minLon = points.map(\.longitude).min()!, maxLon = points.map(\.longitude).max()!
        camera = .region(
            MKCoordinateRegion(
                center: CLLocationCoordinate2D(
                    latitude: (minLat + maxLat) / 2, longitude: (minLon + maxLon) / 2),
                span: MKCoordinateSpan(
                    latitudeDelta: max(0.012, (maxLat - minLat) * 1.5),
                    longitudeDelta: max(0.012, (maxLon - minLon) * 1.5))))
    }

    /// Moves the map to one member.
    private func focusOn(_ member: HouseholdMember) {
        let delta = 0.012
        guard let lat = member.lat, let lon = member.lon else { return }
        let coveredFraction = min(0.85, drawerHeight / max(240, mapHeight))
        let visibleCenter = lat - (coveredFraction * delta / 2)
        camera = .region(
            MKCoordinateRegion(
                center: CLLocationCoordinate2D(latitude: visibleCenter, longitude: lon),
                span: MKCoordinateSpan(latitudeDelta: delta, longitudeDelta: delta)))
    }
}

#if DEBUG
    #Preview {
        HouseholdMapScreen(model: AppViewModel.preview().map, onViewTrips: { _ in })
    }
#endif
