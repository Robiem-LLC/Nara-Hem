import CoreLocation
import Foundation

/// A trip in progress, saved so it survives the app being terminated.
private struct RecordingTrip: Codable {
    var id: String
    var start: Int
    var lastMoving: Int
    var lastSample: Int
    var lastLatitude: Double
    var lastLongitude: Double
    var distance: Double
    var maxSpeed: Double
    var samples: Int
    var startPlaceLat: Double? = nil
    var startPlaceLon: Double? = nil
    var startPlaceRadius: Double? = nil
    var leftStartingPlace: Bool? = nil
    var startPlaceName: String? = nil
    var lastAccuracy: Double? = nil
    var outline: [[Double]]? = nil
}

/// Detects trips from GPS fixes: start and end, distance, top speed and a route outline.
@MainActor
final class TripRecorder {
    private var active: RecordingTrip?
    private var completed: [HouseholdTrip] = []
    private var candidates: [Candidate] = []
    private var confirmedStartFixes: [CLLocation] = []
    private var stationaryAnchor: CLLocation?
    private var stationarySince = 0
    private var lastConfirmedPlace: SavedPlace?
    private var lastConfirmedPlaceAt = 0
    private var lastPersistAt = 0
    private let activeKey = "narahem.ios.trip-active"
    private let completedKey = "narahem.ios.trip-pending"
    var currentId: String? { active?.id }
    var pending: [HouseholdTrip] { completed }

    /// True after a sustained stay, when GPS can switch to low-power checks.
    var lowPowerEligible: Bool { eligibleForLowPower(at: Date()) }

    /// Restores a trip in progress and pending summaries from disk.
    init() {
        if let saved = SecureVault.get(activeKey) {
            active = try? JSONDecoder().decode(RecordingTrip.self, from: saved)
        }
        if let saved = SecureVault.get(completedKey) {
            completed = (try? JSONDecoder().decode([HouseholdTrip].self, from: saved)) ?? []
        }
    }

    /// Returns and clears the fixes recorded before the trip was confirmed, so the route starts
    /// where the trip really began.
    func takeConfirmedStartFixes() -> [CLLocation] {
        let samples = confirmedStartFixes
        confirmedStartFixes.removeAll()
        return samples
    }

    /// Returns true when the phone has been stationary for three minutes with no trip in progress.
    func eligibleForLowPower(at now: Date) -> Bool {
        active == nil && candidates.isEmpty && stationarySince > 0
            && Int(now.timeIntervalSince1970 * 1000) - stationarySince >= 180_000
    }

    /// Returns true if a fix is credibly far from the parked position, even without a speed
    /// reading. Only affects GPS power, never starts a trip.
    func shouldWakeForDisplacement(_ fix: CLLocation) -> Bool {
        guard active == nil, let anchor = stationaryAnchor,
            fix.horizontalAccuracy.isFinite, (0...150).contains(fix.horizontalAccuracy),
            abs(fix.timestamp.timeIntervalSinceNow) <= 180
        else { return false }
        return anchor.distance(from: fix)
            > max(60, fix.horizontalAccuracy + anchor.horizontalAccuracy + 30)
    }

    /// Adds a fix to the route outline, thinning it once it is full.
    private func appendOutline(_ fix: CLLocation, to trip: inout RecordingTrip) {
        var outline = trip.outline ?? []
        let round5 = { (value: Double) in (value * 100_000).rounded() / 100_000 }
        let coords = [round5(fix.coordinate.latitude), round5(fix.coordinate.longitude)]
        if let last = outline.last, last.count == 2,
            CLLocation(latitude: last[0], longitude: last[1]).distance(from: fix) < 8
        {
            outline[outline.count - 1] = coords
        } else {
            if outline.count >= 120 { Self.dropFlattestPoint(&outline) }
            outline.append(coords)
        }
        trip.outline = outline
    }

    /// Removes the interior point whose removal changes the line least (the smallest triangle with
    /// its neighbours). Endpoints are never removed.
    static func dropFlattestPoint(_ outline: inout [[Double]]) {
        guard outline.count >= 3 else { return }
        guard outline.allSatisfy({ $0.count == 2 }) else { outline.remove(at: 1); return }
        let scale = cos(outline[0][0] * .pi / 180)
        var best = 1
        var bestArea = Double.greatestFiniteMagnitude
        for i in 1..<(outline.count - 1) {
            let a = outline[i - 1], b = outline[i], c = outline[i + 1]
            let area = abs(
                (b[1] - a[1]) * scale * (c[0] - a[0]) - (c[1] - a[1]) * scale * (b[0] - a[0]))
            if area < bestArea { bestArea = area; best = i }
        }
        outline.remove(at: best)
    }

    /// Saves the trip in progress and pending summaries.
    private func persist() {
        if let active, let data = try? JSONEncoder().encode(active) {
            SecureVault.put(data, key: activeKey)
        } else {
            SecureVault.delete(activeKey)
        }
        if let data = try? JSONEncoder().encode(completed) {
            SecureVault.put(data, key: completedKey)
        }
    }

    /// Returns true if the fix has valid coordinates and accuracy of 50 m or better.
    private func reliable(_ fix: CLLocation) -> Bool {
        CLLocationCoordinate2DIsValid(fix.coordinate)
            && fix.horizontalAccuracy.isFinite && (0...35).contains(fix.horizontalAccuracy)
            && abs(fix.timestamp.timeIntervalSinceNow) <= 180
    }

    /// Returns true if the fix shows walking speed or faster.
    private func moving(_ fix: CLLocation) -> Bool {
        guard reliable(fix), fix.speed.isFinite, (0.8...65).contains(fix.speed) else {
            return false
        }
        return fix.speedAccuracy < 0
            || (fix.speedAccuracy.isFinite && fix.speedAccuracy <= max(3.0, fix.speed * 0.65))
    }

    /// Returns false if travelling between the two fixes would need an impossible speed.
    private func plausible(_ first: CLLocation, _ next: CLLocation) -> Bool {
        let dt = next.timestamp.timeIntervalSince(first.timestamp)
        guard dt > 0 && dt <= 120 else { return false }
        return first.distance(from: next) <= 65 * dt
            + first.horizontalAccuracy + next.horizontalAccuracy
    }

    /// Returns the saved place containing the fix.
    private func place(for fix: CLLocation, places: [SavedPlace]) -> SavedPlace? {
        places.first {
            CLLocation(latitude: $0.lat, longitude: $0.lon).distance(from: fix)
                <= $0.radius + max(15, min(35, fix.horizontalAccuracy))
        }
    }

    /// Tracks where the phone is stationary and which saved place it is at.
    private func updateStay(_ fix: CLLocation, time: Int, places: [SavedPlace]) {
        guard reliable(fix), fix.speed >= 0, fix.speed < 0.8 else { return }
        if let anchor = stationaryAnchor,
            anchor.distance(from: fix)
                <= max(25, anchor.horizontalAccuracy + fix.horizontalAccuracy)
        {
            if time - stationarySince >= 90_000, let saved = place(for: fix, places: places) {
                lastConfirmedPlace = saved
                lastConfirmedPlaceAt = time
            }
        } else {
            stationaryAnchor = fix
            stationarySince = time
        }
    }

    /// Returns where the trip should start: the last stationary position or the saved place being
    /// left, unless it is too far from the first moving fix.
    private func departureOrigin(startPlace: SavedPlace?, first: CLLocation) -> CLLocation? {
        let origin: CLLocation
        if let stationaryAnchor {
            origin = stationaryAnchor
        } else if let startPlace {
            origin = CLLocation(latitude: startPlace.lat, longitude: startPlace.lon)
        } else {
            return nil
        }
        return origin.distance(from: first) <= 3_000 ? origin : nil
    }

    /// Returns true if the fix is clearly outside the place, allowing for accuracy.
    private func outside(_ place: SavedPlace, fix: CLLocation) -> Bool {
        CLLocation(latitude: place.lat, longitude: place.lon).distance(from: fix)
            > place.radius + max(15, fix.horizontalAccuracy)
    }

    /// Processes a fix: starts, extends or completes a trip.
    func observe(
        _ sample: CLLocation, accountId: String, deviceId: String,
        places: [SavedPlace] = []
    ) {
        guard reliable(sample) else { return }
        let time = Int(sample.timestamp.timeIntervalSince1970 * 1000)
        let isMoving = moving(sample)
        if active == nil {
            updateStay(sample, time: time, places: places)
            guard isMoving else {
                candidates.removeAll()
                return
            }
            if let previous = candidates.last,
                (!plausible(previous.fix, sample) || time - candidates[0].time > 120_000)
            {
                candidates.removeAll()
            }
            candidates.append(Candidate(fix: sample, time: time))
            if candidates.count > 20 { candidates.removeFirst() }
            guard candidates.count >= 3, let first = candidates.first,
                time - first.time >= 12_000,
                first.fix.distance(from: sample)
                    >= max(25, first.fix.horizontalAccuracy + sample.horizontalAccuracy)
            else { return }

            let startPlace: SavedPlace? = {
                if let lastConfirmedPlace, time - lastConfirmedPlaceAt < 1_800_000,
                    CLLocation(latitude: lastConfirmedPlace.lat, longitude: lastConfirmedPlace.lon)
                        .distance(from: first.fix) <= lastConfirmedPlace.radius + 100
                {
                    return lastConfirmedPlace
                }
                return place(for: first.fix, places: places)
            }()
            // Leaving needs two credible readings outside the boundary, so GPS drift (or mowing the
            // lawn) doesn't start a trip.
            if let startPlace {
                guard candidates.suffix(2).allSatisfy({ outside(startPlace, fix: $0.fix) }) else {
                    return
                }
            } else if let anchor = stationaryAnchor,
                time - stationarySince >= 180_000
            {
                let radius = max(40, anchor.horizontalAccuracy * 2)
                guard
                    candidates.suffix(2).allSatisfy({
                        anchor.distance(from: $0.fix) > radius + max(15, $0.fix.horizontalAccuracy)
                    })
                else { return }
            }
            var trip = RecordingTrip(
                id: Wire.freshId(),
                start: first.time, lastMoving: time, lastSample: first.time,
                lastLatitude: first.fix.coordinate.latitude,
                lastLongitude: first.fix.coordinate.longitude,
                distance: 0, maxSpeed: 0, samples: 0,
                startPlaceLat: startPlace?.lat, startPlaceLon: startPlace?.lon,
                startPlaceRadius: startPlace?.radius, leftStartingPlace: true,
                startPlaceName: startPlace?.name,
                lastAccuracy: first.fix.horizontalAccuracy)
            if let origin = departureOrigin(startPlace: startPlace, first: first.fix) {
                appendOutline(origin, to: &trip)
                let gap = origin.distance(from: first.fix)
                if gap > max(5, (origin.horizontalAccuracy + first.fix.horizontalAccuracy) / 2) {
                    trip.distance += gap
                }
            }
            appendOutline(first.fix, to: &trip)
            for candidate in candidates.dropFirst() {
                appendOutline(candidate.fix, to: &trip)
                let previous = CLLocation(
                    latitude: trip.lastLatitude, longitude: trip.lastLongitude)
                let delta = previous.distance(from: candidate.fix)
                if plausible(
                    CLLocation(
                        coordinate: previous.coordinate, altitude: 0,
                        horizontalAccuracy: trip.lastAccuracy ?? 35,
                        verticalAccuracy: 0,
                        timestamp: Date(
                            timeIntervalSince1970:
                                Double(trip.lastSample) / 1000)), candidate.fix),
                    delta
                        > max(5, ((trip.lastAccuracy ?? 35) + candidate.fix.horizontalAccuracy) / 2)
                {
                    trip.distance += delta
                }
                trip.samples += 1
                trip.maxSpeed = max(trip.maxSpeed, candidate.fix.speed)
                trip.lastLatitude = candidate.fix.coordinate.latitude
                trip.lastLongitude = candidate.fix.coordinate.longitude
                trip.lastAccuracy = candidate.fix.horizontalAccuracy
                trip.lastSample = candidate.time
            }
            active = trip
            confirmedStartFixes = candidates.map(\.fix)
            stationaryAnchor = nil
            stationarySince = 0
            candidates.removeAll()
            persist()
            lastPersistAt = time
            return
        }

        guard var trip = active, time > trip.lastSample else { return }
        if time - trip.lastSample > 600_000 {
            complete(trip, accountId: accountId, deviceId: deviceId)
            active = nil
            persist()
            observe(sample, accountId: accountId, deviceId: deviceId, places: places)
            return
        }
        let previous = CLLocation(
            coordinate: CLLocationCoordinate2D(
                latitude: trip.lastLatitude, longitude: trip.lastLongitude),
            altitude: 0, horizontalAccuracy: trip.lastAccuracy ?? 35,
            verticalAccuracy: 0,
            timestamp: Date(timeIntervalSince1970: Double(trip.lastSample) / 1000))
        guard plausible(previous, sample) else { return }
        let delta = previous.distance(from: sample)
        if delta > max(5, ((trip.lastAccuracy ?? 35) + sample.horizontalAccuracy) / 2) {
            trip.distance += delta
        }
        if let lat = trip.startPlaceLat, let lon = trip.startPlaceLon,
            let radius = trip.startPlaceRadius,
            CLLocation(latitude: lat, longitude: lon).distance(from: sample)
                > radius + max(15, sample.horizontalAccuracy)
        {
            trip.leftStartingPlace = true
        }
        trip.lastLatitude = sample.coordinate.latitude
        trip.lastLongitude = sample.coordinate.longitude
        trip.lastAccuracy = sample.horizontalAccuracy
        trip.lastSample = time
        appendOutline(sample, to: &trip)
        trip.samples += 1
        if isMoving && delta >= max(5, sample.horizontalAccuracy) {
            trip.lastMoving = time
            trip.maxSpeed = max(trip.maxSpeed, sample.speed)
        }
        if time - trip.lastMoving >= 150_000 {
            complete(trip, accountId: accountId, deviceId: deviceId)
            active = nil
            stationaryAnchor = sample
            stationarySince = time
            persist()
        } else {
            active = trip
            // Saved at most this often; writing on every fix is expensive.
            if time - lastPersistAt >= 20_000 {
                persist()
                lastPersistAt = time
            }
        }
    }

    /// Completes a trip and adds its summary to the pending list.
    private func complete(_ trip: RecordingTrip, accountId: String, deviceId: String) {
        guard trip.lastMoving > trip.start, trip.samples >= 3,
            trip.distance >= 45, trip.leftStartingPlace != false
        else { return }
        var summary = HouseholdTrip(
            id: Wire.freshId(), accountId: accountId, deviceId: deviceId,
            startedAt: trip.start, endedAt: trip.lastMoving, distance: trip.distance,
            maxSpeed: trip.maxSpeed, samples: trip.samples, tripId: trip.id)
        summary.originName = trip.startPlaceName
        if let outline = trip.outline, outline.count >= 2 {
            summary.preview = outline
            summary.start = outline.first
            summary.end = outline.last
        }
        completed.append(summary)
        if completed.count > 100 { completed.removeFirst(completed.count - 100) }
    }

    /// Completes the current trip if the phone has been stationary long enough.
    func completeIfStationaryLongEnough(now: Date, accountId: String, deviceId: String) {
        guard let trip = active, trip.lastSample > trip.lastMoving,
            Int(now.timeIntervalSince1970 * 1000) - trip.lastMoving >= 150_000
        else { return }
        complete(trip, accountId: accountId, deviceId: deviceId)
        active = nil
        // Enter the stationary state here too, as observe(_:) does, or precise GPS stays on after
        // the trip.
        stationaryAnchor = CLLocation(
            coordinate: CLLocationCoordinate2D(
                latitude: trip.lastLatitude, longitude: trip.lastLongitude),
            altitude: 0, horizontalAccuracy: trip.lastAccuracy ?? 35,
            verticalAccuracy: 0,
            timestamp: Date(timeIntervalSince1970: Double(trip.lastSample) / 1000))
        stationarySince = trip.lastSample
        persist()
    }

    /// Removes a summary the server has accepted.
    func acknowledge(_ id: String) {
        completed.removeAll(where: { $0.id == id })
        persist()
    }

    /// Deletes the trip in progress and pending summaries.
    func discard() {
        active = nil
        completed.removeAll()
        candidates.removeAll()
        confirmedStartFixes.removeAll()
        stationaryAnchor = nil
        stationarySince = 0
        persist()
    }

    /// A possible trip start that isn't confirmed yet.
    private struct Candidate {
        var fix: CLLocation
        var time: Int
    }
}
