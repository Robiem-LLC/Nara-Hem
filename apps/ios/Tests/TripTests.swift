import CoreLocation
import XCTest

@testable import NaraHem

final class TripTests: XCTestCase {
    @MainActor
    func testTripSummariesCacheAndServerRemovalReconciliation() {
        let viewer = String(repeating: "a", count: 32)
        let member = String(repeating: "b", count: 32)
        TripSummaryCache.clear(viewer: viewer)
        defer { TripSummaryCache.clear(viewer: viewer) }
        let now = Int(Date().timeIntervalSince1970 * 1000)
        var trip = HouseholdTrip(
            id: String(repeating: "c", count: 32),
            accountId: member, deviceId: viewer,
            startedAt: now - 60_000, endedAt: now - 30_000,
            distance: 500, maxSpeed: 3, samples: 12)
        trip.originName = "Home"
        trip.preview = [[40.0, -74.0], [40.01, -74.01]]
        TripSummaryCache.save([trip], viewer: viewer, member: member, days: 1)
        let loaded = TripSummaryCache.load(viewer: viewer, member: member, days: 1)
        XCTAssertEqual(loaded.count, 1)
        XCTAssertEqual(loaded.first?.originName, "Home")
        XCTAssertEqual(loaded.first?.preview?.count, 2)
        TripSummaryCache.save([], viewer: viewer, member: member, days: 1)
        XCTAssertTrue(TripSummaryCache.load(viewer: viewer, member: member, days: 1).isEmpty)
    }

    @MainActor
    func testStoppedTripFinalizesAndCanEnterPowerSavingWithoutForegroundTimer() {
        let recorder = TripRecorder()
        recorder.discard()
        defer { recorder.discard() }

        let now = Date()
        let accountId = String(repeating: "a", count: 32)
        let deviceId = String(repeating: "b", count: 32)
        let home = SavedPlace(
            id: String(repeating: "c", count: 32),
            name: "Home", lat: 40.0, lon: -74.0,
            radius: 30, recordId: "", alerts: [:], data: [:])

        func fix(
            _ seconds: TimeInterval, _ lat: Double,
            speed: CLLocationSpeed, accuracy: CLLocationAccuracy = 6
        ) -> CLLocation {
            CLLocation(
                coordinate: CLLocationCoordinate2D(latitude: lat, longitude: -74.0),
                altitude: 0, horizontalAccuracy: accuracy, verticalAccuracy: 6,
                course: speed >= 0 ? 90 : -1, speed: speed,
                timestamp: now.addingTimeInterval(seconds))
        }

        recorder.observe(
            fix(-95, 40.00005, speed: 12),
            accountId: accountId, deviceId: deviceId, places: [home])
        recorder.observe(
            fix(-75, 40.00060, speed: 12),
            accountId: accountId, deviceId: deviceId, places: [home])
        recorder.observe(
            fix(-55, 40.00100, speed: 12),
            accountId: accountId, deviceId: deviceId, places: [home])
        XCTAssertNotNil(recorder.currentId)
        recorder.observe(
            fix(-45, 40.00100, speed: 0),
            accountId: accountId, deviceId: deviceId, places: [home])
        XCTAssertNotNil(recorder.currentId)

        // Simulate a suspended iPhone receiving no further callback during
        // the 150-second stationary timeout.
        recorder.completeIfStationaryLongEnough(
            now: now.addingTimeInterval(180),
            accountId: accountId, deviceId: deviceId)
        XCTAssertNil(recorder.currentId)
        XCTAssertEqual(recorder.pending.count, 1)
        XCTAssertEqual(recorder.pending.first?.originName, "Home")
        XCTAssertTrue(recorder.eligibleForLowPower(at: now.addingTimeInterval(200)))

        // Low-accuracy fixes with unknown speed must be able to wake precise
        // tracking after a credible departure, without declaring a trip.
        XCTAssertFalse(
            recorder.shouldWakeForDisplacement(
                fix(0, 40.00100, speed: -1, accuracy: 75)))
        XCTAssertTrue(recorder.shouldWakeForDisplacement(fix(0, 40.00400, speed: -1, accuracy: 75)))
        XCTAssertNil(recorder.currentId)
    }

    @MainActor
    func testTripStartsWhereThePhoneWasLastStill() {
        let recorder = TripRecorder()
        recorder.discard()
        defer { recorder.discard() }

        let now = Date()
        let accountId = String(repeating: "a", count: 32)
        let deviceId = String(repeating: "b", count: 32)
        func fix(_ seconds: TimeInterval, _ lat: Double, speed: CLLocationSpeed) -> CLLocation {
            CLLocation(
                coordinate: CLLocationCoordinate2D(latitude: lat, longitude: -74.0),
                altitude: 0, horizontalAccuracy: 6, verticalAccuracy: 6,
                course: 90, speed: speed, timestamp: now.addingTimeInterval(seconds))
        }

        // Parked, then GPS only confirms the drive ~55 m down the road.
        for (seconds, lat, speed) in [
            (-170.0, 40.0, 0.0), (-150.0, 40.0, 0.0),
            (-100.0, 40.0005, 12.0), (-80.0, 40.0010, 12.0),
            (-60.0, 40.0015, 12.0), (-50.0, 40.0015, 0.0),
        ] {
            recorder.observe(
                fix(seconds, lat, speed: speed),
                accountId: accountId, deviceId: deviceId)
        }
        XCTAssertNotNil(recorder.currentId)
        recorder.completeIfStationaryLongEnough(
            now: now.addingTimeInterval(120), accountId: accountId, deviceId: deviceId)
        let trip = recorder.pending.first
        XCTAssertEqual(trip?.start, [40.0, -74.0])
        XCTAssertEqual(trip?.preview?.first, [40.0, -74.0])
        XCTAssertGreaterThan(trip?.distance ?? 0, 160)
    }

    @MainActor
    func testFullTripOutlineDropsTheFlattestPointAndKeepsCornersAndEnds() {
        // A straight stretch, then a right-angle turn.
        var outline: [[Double]] = [
            [40.0, -74.0], [40.001, -74.0], [40.002, -74.0], [40.002, -73.999],
        ]
        TripRecorder.dropFlattestPoint(&outline)
        XCTAssertEqual(outline, [[40.0, -74.0], [40.002, -74.0], [40.002, -73.999]])
    }

    func testStationaryCheckInsAcceptFixesWithoutMovement() {
        XCTAssertEqual(StationaryCheckInPolicy.distanceFilter(enabled: true), kCLDistanceFilterNone)
        XCTAssertEqual(StationaryCheckInPolicy.distanceFilter(enabled: false), 35)
        XCTAssertEqual(
            StationaryCheckInPolicy.minimumSampleInterval(
                activeTrip: false, stationaryCheckIns: true, speed: 0.1), 900)
        // Speed bands mirror Android: 5–24 mph every 9 s, faster than 24 mph every 4 s.
        XCTAssertEqual(
            StationaryCheckInPolicy.minimumSampleInterval(
                activeTrip: false, stationaryCheckIns: true, speed: 3.0), 9)
        XCTAssertEqual(
            StationaryCheckInPolicy.minimumSampleInterval(
                activeTrip: false, stationaryCheckIns: true, speed: 12.0), 4)
        XCTAssertEqual(
            StationaryCheckInPolicy.minimumSampleInterval(
                activeTrip: true, stationaryCheckIns: true, speed: 0), 15)
        XCTAssertEqual(
            StationaryCheckInPolicy.minimumSampleInterval(
                activeTrip: false, stationaryCheckIns: false, speed: 0), 90)
    }

    func testOldCachedLocationCannotMasqueradeAsFreshCheckIn() {
        let now = Date()
        func fix(secondsAgo: TimeInterval, accuracy: CLLocationAccuracy) -> CLLocation {
            CLLocation(
                coordinate: CLLocationCoordinate2D(latitude: 40.124, longitude: -74.245),
                altitude: 0, horizontalAccuracy: accuracy, verticalAccuracy: 12,
                timestamp: now.addingTimeInterval(-secondsAgo))
        }
        XCTAssertTrue(StationaryCheckInPolicy.isUsable(fix(secondsAgo: 30, accuracy: 12), now: now))
        XCTAssertFalse(
            StationaryCheckInPolicy.isUsable(fix(secondsAgo: 720, accuracy: 12), now: now))
        XCTAssertFalse(
            StationaryCheckInPolicy.isUsable(fix(secondsAgo: 30, accuracy: -1), now: now))
    }

    func testLocationSampleContainsCoordinatesButNoServerTarget() {
        let sample = CLLocation(
            coordinate: CLLocationCoordinate2D(latitude: 40.124, longitude: -74.245),
            altitude: 0, horizontalAccuracy: 12, verticalAccuracy: 12,
            timestamp: Date())
        let location = LocalLocation(sample)
        XCTAssertEqual(location.latitude, 40.124, accuracy: 0.00001)
        XCTAssertEqual(location.longitude, -74.245, accuracy: 0.00001)
        XCTAssertEqual(location.accuracy, 12)
        XCTAssertTrue(location.capturedAt <= Date())
    }

    func testTheMarkerOnlyMovesBeyondTheMarginOfError() {
        let shown = LocalLocation(
            CLLocation(
                coordinate: CLLocationCoordinate2D(latitude: 40.124, longitude: -74.245),
                altitude: 0, horizontalAccuracy: 20, verticalAccuracy: 10,
                timestamp: Date(timeIntervalSinceNow: -30)))
        // About 15 m away, inside a 20 m margin: drift, so the marker stays.
        let drift = CLLocation(
            coordinate: CLLocationCoordinate2D(latitude: 40.12413, longitude: -74.245),
            altitude: 0, horizontalAccuracy: 25, verticalAccuracy: 10, timestamp: Date())
        XCTAssertFalse(LocalLocation.moved(from: shown, to: drift))
        let refreshed = shown.refreshed(at: drift.timestamp)
        XCTAssertEqual(refreshed.latitude, shown.latitude)
        XCTAssertEqual(refreshed.capturedAt, drift.timestamp)
        // About 110 m away: real movement.
        let walked = CLLocation(
            coordinate: CLLocationCoordinate2D(latitude: 40.125, longitude: -74.245),
            altitude: 0, horizontalAccuracy: 10, verticalAccuracy: 10, timestamp: Date())
        XCTAssertTrue(LocalLocation.moved(from: shown, to: walked))
    }
}
