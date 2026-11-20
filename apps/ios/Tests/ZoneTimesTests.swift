import XCTest

@testable import NaraHem

/// Times shown with the member's own time beside them when they're in another time zone.
final class ZoneTimesTests: XCTestCase {
    private let newYork = TimeZone(identifier: "America/New_York")!
    private let locale = Locale(identifier: "en_US")

    /// 2026-11-20 01:00 UTC: 8:00 PM in New York.
    private let evening = 1_795_136_400_000

    private func format(_ zone: String?, withDate: Bool = false) -> String {
        ZoneTimes.format(evening, zone: zone, withDate: withDate, viewer: newYork, locale: locale)
            .replacingOccurrences(of: "\u{202F}", with: " ")
    }

    func testAnotherZoneShowsBothTimesTheViewersFirst() {
        XCTAssertEqual(format("America/Los_Angeles"), "8:00 PM EST / 5:00 PM PST")
    }

    func testTheSameClockOrNoZoneShowsOneTime() {
        for zone in ["America/New_York", "America/Toronto", nil, "Not/AZone"] {
            XCTAssertEqual(format(zone), "8:00 PM")
        }
    }

    func testDatesAreIncludedWhenAsked() {
        let both = format("America/Los_Angeles", withDate: true)
        XCTAssertTrue(both.hasPrefix("11/19/26, 8:00 PM EST / 11/19/26, 5:00 PM PST"), both)
    }
}
