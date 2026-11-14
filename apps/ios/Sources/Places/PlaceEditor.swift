import CoreLocation
import MapKit
import PhotosUI
import SwiftUI
import UIKit

/// Place editor in two steps: the boundary on a map, then the name and alerts.
struct PlaceEditor: View {
    @Environment(\.dismiss) private var dismiss
    let existing: SavedPlace?
    let members: [HouseholdMember]
    let initialCoordinate: CLLocationCoordinate2D?
    var onDelete: (() -> Void)? = nil
    let onSave: (String, Double, Double, Double, Wire.Object) -> Void
    @State private var step = 0
    @State private var confirmDelete = false
    @State private var name = ""
    @State private var query = ""
    @State private var searchStatus = ""
    @State private var searchRunning = false
    @State private var latitude = ""
    @State private var longitude = ""
    @State private var radius = "100"
    @State private var camera: MapCameraPosition = .automatic
    @State private var center = CLLocationCoordinate2D(latitude: 0, longitude: 0)
    @State private var showCoordinates = false
    private var radiusValue: Double { Double(radius) ?? 0 }

    private var validPosition: Bool {
        guard let lat = Double(latitude), let lon = Double(longitude) else { return false }
        return (-90...90).contains(lat) && (-180...180).contains(lon)
    }

    private var validRadius: Bool {
        radiusValue.isFinite && (1...10000).contains(radiusValue)
    }

    /// The radius as a slider value, kept in step with the exact field.
    private var radiusSlider: Binding<Double> {
        Binding(get: { min(2000, max(1, radiusValue)) }, set: { radius = String(Int($0)) })
    }

    /// First step: position and size the circle by searching or moving the map.
    @ViewBuilder private var boundaryStep: some View {
        FormSection(title: existing == nil ? "New place · 1 of 2" : "Edit boundary · 1 of 2") {
            Text("Search for an address or business, or drag the map to position the center.")
                .font(.footnote).foregroundStyle(subdued)
            HStack {
                TextField("Search address or business", text: $query)
                    .submitLabel(.search)
                    .onSubmit { Task { await searchPlace() } }
                Button("Find") { Task { await searchPlace() } }
                    .buttonStyle(NaraHemOutlineButton())
                    .disabled(
                        query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || searchRunning)
            }
            if searchRunning { ProgressView("Searching") }
            if !searchStatus.isEmpty {
                Text(searchStatus).font(.footnote).foregroundStyle(subdued)
            }
        }
        Map(position: $camera) {
            MapCircle(center: center, radius: max(1, min(10000, radiusValue)))
                .foregroundStyle(placeColor.opacity(0.20))
                .stroke(placeColor, lineWidth: 2)
        }
        .mapStyle(.standard)
        .frame(height: 310)
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .onMapCameraChange(frequency: .onEnd) { context in
            updateCenter(context.region.center)
        }
        FormSection(title: "Boundary") {
            HStack {
                Text("Boundary radius: \(Int(radiusValue)) metres")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                TextField("1–10,000", text: $radius)
                    .keyboardType(.numberPad).frame(width: 110)
            }
            Slider(value: radiusSlider, in: 1...2000, step: 1).tint(accent)
            if radiusValue < 20 {
                Text(
                    """
                    Small radii are supported, but phone GPS may be less accurate \
                    than the selected boundary. Arrival and departure detection \
                    can be unreliable.
                    """
                )
                .font(.footnote).foregroundStyle(warn)
            }
            DisclosureGroup("Advanced: exact coordinates", isExpanded: $showCoordinates) {
                VStack(alignment: .leading, spacing: 10) {
                    TextField("Latitude", text: $latitude).keyboardType(.numbersAndPunctuation)
                    TextField("Longitude", text: $longitude)
                        .keyboardType(.numbersAndPunctuation)
                    Button("Use entered coordinates") {
                        if let lat = Double(latitude), let lon = Double(longitude),
                            (-90...90).contains(lat), (-180...180).contains(lon)
                        {
                            let position = CLLocationCoordinate2D(latitude: lat, longitude: lon)
                            center = position
                            focus(position)
                        }
                    }
                    .buttonStyle(NaraHemOutlineButton())
                    .disabled(!validPosition)
                }
                .padding(.top, 8)
            }
            .tint(accent)
            Text("Address searches use Apple's map service.")
                .font(.footnote).foregroundStyle(subdued)
        }
    }

    /// Second step: name the place.
    @ViewBuilder private var detailsStep: some View {
        FormSection(title: "Place details · 2 of 2") {
            TextField("Name this place", text: $name)
            Text("Location: \(latitude), \(longitude)")
                .font(.footnote).foregroundStyle(subdued)
            Text("Boundary radius: \(Int(radiusValue)) metres")
            Button("Edit boundary") { step = 0 }.buttonStyle(NaraHemOutlineButton())
        }
        if onDelete != nil {
            FormSection(title: "Remove") {
                Button("Delete place", role: .destructive) { confirmDelete = true }
                    .foregroundStyle(dangerText)
            }
        }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if step == 0 { boundaryStep } else { detailsStep }
                }
                .textFieldStyle(NaraHemFieldStyle())
                .padding(18)
            }
            .background(AppBackground())
            .foregroundStyle(cream)
            .navigationTitle(existing == nil ? "Add place" : "Edit place")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(midnight, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .alert("Delete saved place?", isPresented: $confirmDelete) {
                Button("Delete", role: .destructive) { onDelete?() }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This removes the saved place for the household.")
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if step == 0 {
                        Button("Next") { step = 1 }.disabled(!validPosition || !validRadius)
                    } else {
                        Button("Save") { save() }
                            .disabled(
                                name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                    || !validPosition || !validRadius)
                    }
                }
            }
            .onAppear { start() }
        }
        .preferredColorScheme(.dark)
        .tint(accent)
    }

    /// Fills the form from the place being edited, or starts at this phone's location for a new
    /// one.
    private func start() {
        if let existing {
            name = existing.name
            radius = String(Int(existing.radius))
            center = CLLocationCoordinate2D(latitude: existing.lat, longitude: existing.lon)
            updateCenter(center)
            focus(center)
        } else {
            if let initialCoordinate {
                center = initialCoordinate
                updateCenter(center)
                focus(center)
            }
            camera = .userLocation(followsHeading: false, fallback: camera)
        }
    }

    /// Validates the form and saves the place. Everyone sharing their location gets its arrival
    /// and departure alerts, so it has no per-person rules.
    private func save() {
        guard let lat = Double(latitude), let lon = Double(longitude),
            validPosition, validRadius
        else { return }
        onSave(name, lat, lon, radiusValue, [:])
    }

    /// Zooms the map to a position.
    private func focus(_ position: CLLocationCoordinate2D) {
        camera = .region(
            MKCoordinateRegion(
                center: position,
                span: MKCoordinateSpan(latitudeDelta: 0.004, longitudeDelta: 0.004)))
    }

    /// Sets the circle's centre and the coordinate fields.
    private func updateCenter(_ position: CLLocationCoordinate2D) {
        guard position.latitude.isFinite, position.longitude.isFinite,
            (-90...90).contains(position.latitude),
            (-180...180).contains(position.longitude)
        else { return }
        center = position
        latitude = String(format: "%.7f", position.latitude)
        longitude = String(format: "%.7f", position.longitude)
    }

    /// Searches Apple Maps for the entered text and moves the circle to the first result.
    @MainActor
    private func searchPlace() async {
        let phrase = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !phrase.isEmpty else { return }
        searchRunning = true
        defer { searchRunning = false }
        do {
            let request = MKLocalSearch.Request()
            request.naturalLanguageQuery = phrase
            let results = try await MKLocalSearch(request: request).start()
            guard let match = results.mapItems.first else {
                searchStatus = "No matching address found. Move the map or try another search."
                return
            }
            updateCenter(match.placemark.coordinate)
            focus(match.placemark.coordinate)
            searchStatus =
                match.name.map { "Selected \($0). Verify the center and radius." }
                ?? "Location found. Verify the center and radius."
        } catch {
            searchStatus = "Search unavailable. You can still move the map or enter coordinates."
        }
    }
}
