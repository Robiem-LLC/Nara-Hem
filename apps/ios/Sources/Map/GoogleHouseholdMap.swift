import CoreLocation
import GoogleMaps
import SwiftUI
import UIKit

/// Google map showing member avatars and saved place circles.
struct GoogleHouseholdMap: UIViewRepresentable {
    /// This phone's position and capture time in milliseconds.
    private typealias LocalPin = (position: CLLocationCoordinate2D, captured: Int64)
    let members: [HouseholdMember]
    let places: [SavedPlace]
    let localFix: LocalLocation?
    let ownPersonId: String?
    let selectedMemberId: String?
    let focusRevision: Int
    let occludedBottom: CGFloat
    let onMemberTapped: (String) -> Void
    let onFollowPaused: () -> Void

    /// This phone's own fix if it is accurate to 75 m and less than 90 seconds old.
    private var freshLocalFix: LocalPin? {
        guard let localFix, localFix.accuracy >= 0, localFix.accuracy <= 75,
            localFix.capturedAt.timeIntervalSinceNow >= -90
        else { return nil }
        return (localFix.coordinate, Int64(localFix.capturedAt.timeIntervalSince1970 * 1000))
    }

    /// Creates the coordinator that keeps markers and animations between updates.
    func makeCoordinator() -> Coordinator { Coordinator() }

    /// Creates and configures the map view.
    func makeUIView(context: Context) -> GMSMapView {
        let map = GMSMapView(frame: .zero)
        map.overrideUserInterfaceStyle = .light
        map.delegate = context.coordinator
        context.coordinator.mapView = map
        map.settings.compassButton = false
        map.settings.myLocationButton = false
        map.settings.rotateGestures = false
        map.settings.tiltGestures = false
        return map
    }

    /// Stops the map zooming out so far that the world repeats side by side.
    static func limitToOneWorld(_ map: GMSMapView) {
        let width = Double(map.bounds.width)
        guard width > 256 else { return }
        let zoom = Float(ceil(log2(width / 256)))
        if map.minZoom != zoom { map.setMinZoom(zoom, maxZoom: map.maxZoom) }
    }

    /// Stops marker animations when the map is removed.
    static func dismantleUIView(_ uiView: GMSMapView, coordinator: Coordinator) {
        coordinator.shutDown()
        uiView.delegate = nil
    }

    /// Updates padding, markers, place circles and the camera from the current data.
    func updateUIView(_ map: GMSMapView, context: Context) {
        Self.limitToOneWorld(map)
        let coordinator = context.coordinator
        let padding = UIEdgeInsets(top: 8, left: 8, bottom: max(0, occludedBottom), right: 8)
        let local = freshLocalFix
        coordinator.onSelect = onMemberTapped
        coordinator.onPauseFollow = onFollowPaused
        if map.padding != padding { map.padding = padding }
        updateMembers(map, coordinator, local: local)
        updatePlaces(map, coordinator)
        updateCamera(map, coordinator, local: local)
    }

    /// Adds, moves and removes member markers, using this phone's newer local fix for its own
    /// marker.
    private func updateMembers(_ map: GMSMapView, _ coordinator: Coordinator, local: LocalPin?) {
        var visibleMembers = Set<String>()
        let fan = AvatarFan.layout(members, places: places, size: 56)
        let localId = "__local_iphone__"
        for member in members {
            guard let lat = member.lat, let lon = member.lon else { continue }
            let id = member.id
            visibleMembers.insert(id)
            var coordinate = CLLocationCoordinate2D(latitude: lat, longitude: lon)
            var timestamp = Int64(member.capturedAt)
            if id == ownPersonId, let local, local.captured > timestamp {
                coordinate = local.position
                timestamp = local.captured
            }
            let marker: GMSMarker
            if let old = coordinator.markers[id] {
                marker = old
            } else {
                marker = GMSMarker(position: coordinate)
                marker.userData = id
                marker.map = map
                coordinator.markers[id] = marker
            }
            marker.title = member.name
            let photoKey = member.name + "|" + (member.photo ?? "")
            if coordinator.shownPhotos[id] != photoKey {
                marker.icon = avatar(member.photo, name: member.name)
                coordinator.shownPhotos[id] = photoKey
            }
            let offset = fan[id] ?? AvatarFan.Offset()
            marker.groundAnchor = CGPoint(x: 0.5 - offset.dx / 56, y: 1 - offset.dy / 56)
            coordinator.move(id, marker: marker, to: coordinate, at: timestamp)
        }

        if !visibleMembers.contains(ownPersonId ?? ""), let local {
            let marker: GMSMarker
            if let old = coordinator.markers[localId] {
                marker = old
            } else {
                marker = GMSMarker(position: local.position)
                marker.title = "This iPhone"
                marker.map = map
                coordinator.markers[localId] = marker
            }
            coordinator.move(localId, marker: marker, to: local.position, at: local.captured)
            visibleMembers.insert(localId)
        }
        for id in Array(coordinator.markers.keys) where !visibleMembers.contains(id) {
            coordinator.flights.removeValue(forKey: id)
            coordinator.markers.removeValue(forKey: id)?.map = nil
            coordinator.shownAt.removeValue(forKey: id)
            coordinator.shownPhotos.removeValue(forKey: id)
        }
    }

    /// Adds, updates and removes saved place circles.
    private func updatePlaces(_ map: GMSMapView, _ coordinator: Coordinator) {
        let placeIds = Set(places.map(\.id))
        for place in places {
            let center = CLLocationCoordinate2D(latitude: place.lat, longitude: place.lon)
            let circle: GMSCircle
            if let existing = coordinator.circles[place.id] {
                circle = existing
            } else {
                circle = GMSCircle(position: center, radius: place.radius)
                circle.fillColor = placeUIColor.withAlphaComponent(0.12)
                circle.strokeColor = placeUIColor.withAlphaComponent(0.95)
                circle.strokeWidth = 2
                circle.map = map
                coordinator.circles[place.id] = circle
            }
            if circle.position.latitude != center.latitude
                || circle.position.longitude != center.longitude
            {
                circle.position = center
            }
            if circle.radius != place.radius { circle.radius = place.radius }
        }
        for id in Array(coordinator.circles.keys) where !placeIds.contains(id) {
            coordinator.circles.removeValue(forKey: id)?.map = nil
        }
    }

    /// Moves to the selected member, or frames the whole household on first display.
    private func updateCamera(_ map: GMSMapView, _ coordinator: Coordinator, local: LocalPin?) {
        if focusRevision != coordinator.lastFocus,
            let member = members.first(where: { $0.id == selectedMemberId }),
            let lat = member.lat, let lon = member.lon
        {
            coordinator.lastFocus = focusRevision
            coordinator.followId = member.id
            coordinator.followPaused = false
            coordinator.initiallyFramed = true
            map.animate(
                with: GMSCameraUpdate.setTarget(
                    CLLocationCoordinate2D(latitude: lat, longitude: lon), zoom: 16))
        } else if !coordinator.initiallyFramed {
            let coords = members.compactMap { member -> CLLocationCoordinate2D? in
                guard let lat = member.lat, let lon = member.lon else { return nil }
                return CLLocationCoordinate2D(latitude: lat, longitude: lon)
            }
            if let first = coords.first {
                coordinator.initiallyFramed = true
                if coords.count == 1 {
                    map.moveCamera(GMSCameraUpdate.setTarget(first, zoom: 15))
                } else {
                    var bounds = GMSCoordinateBounds(coordinate: first, coordinate: first)
                    for coordinate in coords.dropFirst() {
                        bounds = bounds.includingCoordinate(coordinate)
                    }
                    map.moveCamera(GMSCameraUpdate.fit(bounds, withPadding: 42))
                    if map.camera.zoom > 15 { map.moveCamera(GMSCameraUpdate.zoom(to: 15)) }
                }
            } else if let local {
                coordinator.initiallyFramed = true
                map.moveCamera(GMSCameraUpdate.setTarget(local.position, zoom: 15))
            }
        }
    }

    /// Draws a round marker image from a photo, or from the name's initial.
    private func avatar(_ value: String?, name: String) -> UIImage {
        let size = CGSize(width: 56, height: 56)
        let image = ProfilePhoto.image(value)
        let renderer = UIGraphicsImageRenderer(size: size)
        return renderer.image { ctx in
            let rect = CGRect(x: 3, y: 3, width: 50, height: 50)
            let oval = UIBezierPath(ovalIn: rect)
            UIColor(panelRaised).setFill()
            oval.fill()
            ctx.cgContext.saveGState()
            oval.addClip()
            if let image {
                let scale = max(rect.width / image.size.width, rect.height / image.size.height)
                let w = image.size.width * scale, h = image.size.height * scale
                image.draw(
                    in: CGRect(x: rect.midX - w / 2, y: rect.midY - h / 2, width: w, height: h))
            } else {
                let initials = String(name.prefix(1)).uppercased()
                let font = UIFont.boldSystemFont(ofSize: 25)
                let attributes: [NSAttributedString.Key: Any] = [
                    .font: font, .foregroundColor: UIColor.white,
                ]
                let textSize = (initials as NSString).size(withAttributes: attributes)
                (initials as NSString).draw(
                    at: CGPoint(
                        x: rect.midX - textSize.width / 2,
                        y: rect.midY - textSize.height / 2), withAttributes: attributes)
            }
            ctx.cgContext.restoreGState()
            accentUIColor.setStroke()
            oval.lineWidth = 3
            oval.stroke()
        }
    }

    /// Keeps the map's markers and circles and animates markers between fixes.
    final class Coordinator: NSObject, GMSMapViewDelegate {
        var onSelect: (String) -> Void = { _ in }
        var onPauseFollow: () -> Void = {}
        weak var mapView: GMSMapView?
        var followId: String?
        var followPaused = false
        var lastCameraAt: CFTimeInterval = 0
        var markers: [String: GMSMarker] = [:]
        var circles: [String: GMSCircle] = [:]
        var shownPhotos: [String: String] = [:]
        var shownAt: [String: Int64] = [:]
        var flights: [String: Flight] = [:]
        var displayLink: CADisplayLink?
        var lastFocus = -1
        var initiallyFramed = false

        /// Animates a marker to a new fix, or jumps if the change is too large to be real movement.
        func move(
            _ id: String, marker: GMSMarker,
            to coordinate: CLLocationCoordinate2D, at captured: Int64
        ) {
            guard CLLocationCoordinate2DIsValid(coordinate) else { return }
            guard let previous = shownAt[id] else {
                marker.position = coordinate
                shownAt[id] = captured
                return
            }
            guard captured > previous else { return }
            shownAt[id] = captured
            let interval = Double(captured - previous) / 1000
            let displayed = marker.position
            let distance = CLLocation(latitude: displayed.latitude, longitude: displayed.longitude)
                .distance(
                    from: CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
                )
            guard distance >= 3, distance <= 2_000, interval <= 120 else {
                flights.removeValue(forKey: id)
                marker.position = coordinate
                return
            }
            flights[id] = Flight(
                start: displayed, end: coordinate,
                beganAt: CACurrentMediaTime(),
                duration: MarkerMotionInterpolation.duration(secondsBetweenFixes: interval))
            if displayLink == nil {
                let link = CADisplayLink(target: self, selector: #selector(advance))
                link.add(to: .main, forMode: .common)
                displayLink = link
            }
            displayLink?.isPaused = false
        }

        /// Advances marker animations by one frame.
        @objc private func advance(_ displayLink: CADisplayLink) {
            let now = CACurrentMediaTime()
            var finished: [String] = []
            for (id, flight) in flights {
                guard let marker = markers[id] else { finished.append(id); continue }
                let progress = (now - flight.beganAt) / flight.duration
                marker.position = MarkerMotionInterpolation.position(
                    from: flight.start, to: flight.end, progress: progress)
                if progress >= 1 { finished.append(id) }
            }
            for id in finished { flights.removeValue(forKey: id) }
            if !followPaused, let followId, let marker = markers[followId],
                let map = mapView, now - lastCameraAt >= 0.20
            {
                lastCameraAt = now
                let target = marker.position
                let difference = CLLocation(
                    latitude: map.camera.target.latitude,
                    longitude: map.camera.target.longitude
                )
                .distance(from: CLLocation(latitude: target.latitude, longitude: target.longitude))
                if difference > 5 {
                    map.moveCamera(GMSCameraUpdate.setTarget(target))
                }
            }
            displayLink.isPaused = flights.isEmpty
        }

        /// Stops the display link.
        func shutDown() {
            displayLink?.invalidate()
            displayLink = nil
            flights.removeAll()
            followId = nil
            mapView = nil
            markers.values.forEach { $0.map = nil }
            circles.values.forEach { $0.map = nil }
            markers.removeAll()
            circles.removeAll()
            shownPhotos.removeAll()
            shownAt.removeAll()
        }

        /// Stops following the selected member when the user drags the map.
        func mapView(_ mapView: GMSMapView, willMove gesture: Bool) {
            if gesture && followId != nil {
                followPaused = true
                onPauseFollow()
            }
        }

        /// Selects the member whose marker was tapped.
        func mapView(_ mapView: GMSMapView, didTap marker: GMSMarker) -> Bool {
            guard let id = marker.userData as? String else { return false }
            onSelect(id)
            return true
        }

        /// An in-progress marker animation.
        struct Flight {
            let start: CLLocationCoordinate2D
            let end: CLLocationCoordinate2D
            let beganAt: CFTimeInterval
            let duration: Double
        }
    }
}
