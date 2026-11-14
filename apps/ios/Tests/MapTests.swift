import CoreLocation
import XCTest

@testable import NaraHem

final class MapTests: XCTestCase {
    func testMarkerInterpolationDoesNotExtrapolatePastObservedGpsFix() {
        let first = CLLocationCoordinate2D(latitude: 40.0, longitude: -74.0)
        let second = CLLocationCoordinate2D(latitude: 40.002, longitude: -73.998)
        let halfway = MarkerMotionInterpolation.position(from: first, to: second, progress: 0.5)
        XCTAssertEqual(halfway.latitude, 40.001, accuracy: 0.0000001)
        XCTAssertEqual(halfway.longitude, -73.999, accuracy: 0.0000001)
        XCTAssertEqual(
            MarkerMotionInterpolation.position(from: first, to: second, progress: -1).latitude,
            first.latitude)
        XCTAssertEqual(
            MarkerMotionInterpolation.position(from: first, to: second, progress: 10).latitude,
            second.latitude)
        XCTAssertEqual(MarkerMotionInterpolation.duration(secondsBetweenFixes: 15), 12)
        XCTAssertEqual(MarkerMotionInterpolation.duration(secondsBetweenFixes: 0.1), 0.5)
        XCTAssertEqual(MarkerMotionInterpolation.duration(secondsBetweenFixes: 200), 12)
    }

    // MARK: Avatar fan (same rules as the web map and Android's AvatarFanTest)

    private func fanMember(_ id: String, _ lat: Double) -> HouseholdMember {
        HouseholdMember(id: id, name: id, lat: lat, lon: -74.0, accuracy: 10)
    }

    func testNearbyMembersSitSideBySideAndFarOnesStay() {
        let fan = AvatarFan.layout(
            [fanMember("b", 40.0001), fanMember("a", 40.0), fanMember("c", 40.01)],
            places: [], size: 92)
        XCTAssertEqual(fan["a"], AvatarFan.Offset(dx: -42, dy: 0, groupSize: 2))
        XCTAssertEqual(fan["b"], AvatarFan.Offset(dx: 42, dy: 0, groupSize: 2))
        XCTAssertNil(fan["c"])
    }

    func testSameSavedPlaceGroupsWiderAndBigGroupsGetASecondRow() {
        let home = SavedPlace(
            id: "h", name: "Home", lat: 40.0, lon: -74.0, radius: 150, recordId: "r", alerts: [:],
            data: [:])
        let apart = [fanMember("a", 40.0), fanMember("b", 40.0007)]
        XCTAssertEqual(AvatarFan.layout(apart, places: [home], size: 46)["a"]?.groupSize, 2)
        XCTAssertTrue(AvatarFan.layout(apart, places: [], size: 46).isEmpty)
        let five = (1...5).map { fanMember("m\($0)", 40.0 + Double($0) * 0.00001) }
        let rows = AvatarFan.layout(five, places: [], size: 46)
        XCTAssertEqual(rows.values.filter { $0.dy == 0 }.count, 4)
        XCTAssertEqual(rows["m5"], AvatarFan.Offset(dx: 0, dy: -36, groupSize: 5))
    }

    // MARK: Location freshness (same rules as Android's LocationFreshnessTest)

    func testParkedMembersReadSinceAndLowBatteryMayBeOff() {
        let now = 100_000_000
        func member(
            _ minutesAgo: Int, still: Int? = nil, battery: Int? = 80, contact: Int? = nil
        ) -> HouseholdMember {
            HouseholdMember(
                id: "a", name: "Sam", lat: 40, lon: -74, accuracy: 10,
                capturedAt: now - minutesAgo * 60_000,
                battery: battery, charging: false, stillSince: still, lastContact: contact)
        }
        XCTAssertFalse(LocationFreshness.of(member(5), now: now).alarming)
        let parked = LocationFreshness.of(member(40, still: now - 90 * 60_000), now: now)
        XCTAssertTrue(parked.text.hasPrefix("Here since "))
        XCTAssertFalse(parked.alarming)
        XCTAssertTrue(LocationFreshness.of(member(40), now: now).text.hasSuffix(" · stale"))
        let off = LocationFreshness.of(member(40, still: now - 90 * 60_000, battery: 4), now: now)
        XCTAssertTrue(off.alarming)
        XCTAssertTrue(off.text.hasPrefix("May be off · battery was 4%"))
        XCTAssertFalse(
            LocationFreshness.of(
                member(40, still: now - 90 * 60_000, battery: 4, contact: now - 60_000), now: now
            ).alarming)
    }
}
