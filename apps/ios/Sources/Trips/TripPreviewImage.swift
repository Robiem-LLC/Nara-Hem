import CoreLocation
import MapKit
import SwiftUI
import UIKit

/// Static map snapshot of a trip's route for the trip card. Rendered and cached on the device.
struct TripPreviewImage: View {
    let trip: HouseholdTrip
    let viewerId: String
    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                ZStack {
                    panel
                    VStack(spacing: 8) {
                        Image(systemName: "point.topleft.down.curvedto.point.bottomright.up")
                            .font(.title)
                        Text("Route preview unavailable")
                            .font(.caption)
                    }
                    .foregroundStyle(cream.opacity(0.6))
                }
            }
        }
        .frame(height: 135)
        .frame(maxWidth: .infinity)
        .clipped()
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .task(id: "\(viewerId):\(trip.id):\(trip.matched == true):\(trip.preview?.count ?? 0)") {
            image = await TripPreviewRenderer.make(trip, viewerId: viewerId)
        }
    }
}

/// Renders route snapshots.
@MainActor
private enum TripPreviewRenderer {
    /// Returns the cached snapshot for a trip, or renders the route over a MapKit snapshot and
    /// caches it.
    static func make(_ trip: HouseholdTrip, viewerId: String) async -> UIImage? {
        var segments: [[CLLocationCoordinate2D]] = []
        var segment: [CLLocationCoordinate2D] = []
        guard viewerId.count == 32,
            viewerId.utf8.allSatisfy({
                ($0 >= 48 && $0 <= 57) || ($0 >= 97 && $0 <= 102)
            }), trip.id.count == 32,
            trip.id.utf8.allSatisfy({
                ($0 >= 48 && $0 <= 57) || ($0 >= 97 && $0 <= 102)
            })
        else { return nil }
        let directory = TripSummaryCache.directory.appendingPathComponent(
            "Previews", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let path = directory.appendingPathComponent(
            "\(viewerId)-\(trip.id)-\(trip.matched == true ? "matched" : "raw")-v2.jpg")
        if let bytes = try? Data(contentsOf: path), let image = UIImage(data: bytes) {
            return image
        }
        guard let coordinates = trip.preview, coordinates.count >= 2 else { return nil }
        for item in coordinates {
            // Empty entries mark gaps in the recording; don't draw a line across them.
            guard item.count == 2, item[0].isFinite, item[1].isFinite,
                (-90...90).contains(item[0]), (-180...180).contains(item[1])
            else {
                if !segment.isEmpty { segments.append(segment); segment = [] }
                continue
            }
            segment.append(CLLocationCoordinate2D(latitude: item[0], longitude: item[1]))
        }
        if !segment.isEmpty { segments.append(segment) }
        let points = segments.flatMap { $0 }
        guard points.count >= 2 else { return nil }
        let lat = points.map(\.latitude), lon = points.map(\.longitude)
        guard let minLat = lat.min(), let maxLat = lat.max(),
            let minLon = lon.min(), let maxLon = lon.max()
        else { return nil }

        let options = MKMapSnapshotter.Options()
        options.size = CGSize(width: 700, height: 270)
        options.traitCollection = UITraitCollection(userInterfaceStyle: .dark)
        options.mapType = .standard
        options.region = MKCoordinateRegion(
            center: CLLocationCoordinate2D(
                latitude: (minLat + maxLat) / 2,
                longitude: (minLon + maxLon) / 2),
            span: MKCoordinateSpan(
                latitudeDelta: max(0.0025, (maxLat - minLat) * 1.3),
                longitudeDelta: max(0.0025, (maxLon - minLon) * 1.3)))
        do {
            let snapshot = try await MKMapSnapshotter(options: options).start()
            let renderer = UIGraphicsImageRenderer(size: options.size)
            let result = renderer.image { graphics in
                snapshot.image.draw(at: .zero)
                let context = graphics.cgContext
                for segment in segments where segment.count > 1 {
                    let path = UIBezierPath()
                    for (index, coordinate) in segment.enumerated() {
                        let point = snapshot.point(for: coordinate)
                        if index == 0 { path.move(to: point) } else { path.addLine(to: point) }
                    }
                    path.lineWidth = 6
                    path.lineJoinStyle = .round
                    routeUIColor.setStroke()
                    path.stroke()
                }
                for (coordinate, color) in [
                    (points[0], UIColor(tripStart)), (points[points.count - 1], UIColor(tripEnd)),
                ] {
                    let point = snapshot.point(for: coordinate)
                    context.setFillColor(UIColor.white.cgColor)
                    context.fillEllipse(
                        in: CGRect(x: point.x - 10, y: point.y - 10, width: 20, height: 20))
                    context.setFillColor(color.cgColor)
                    context.fillEllipse(
                        in: CGRect(x: point.x - 7, y: point.y - 7, width: 14, height: 14))
                }
            }
            if let data = result.jpegData(compressionQuality: 0.65) {
                try? data.write(to: path, options: .atomic)
                try? FileManager.default.setAttributes(
                    [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                    ofItemAtPath: path.path)
            }
            return result
        } catch { return nil }
    }
}
