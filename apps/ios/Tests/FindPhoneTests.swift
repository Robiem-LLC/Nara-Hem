import XCTest

@testable import NaraHem

final class FindPhoneTests: XCTestCase {
    func testFindPhoneSirenIsLoudBoundedAndRepeats() {
        let samples = (0..<Int(FindPhoneTone.cycle * 44_100)).map {
            FindPhoneTone.sample(at: Double($0) / 44_100)
        }
        let peak = samples.map(abs).max() ?? 0
        XCTAssertGreaterThan(peak, 0.9, "Siren plays near full scale")
        XCTAssertLessThanOrEqual(peak, 1)
        let rms = (samples.reduce(0) { $0 + $1 * $1 } / Double(samples.count)).squareRoot()
        XCTAssertGreaterThan(rms, 0.6, "Much louder than the old 0.3 chime")
        XCTAssertEqual(FindPhoneTone.sample(at: 1.25), 0, "Each cycle ends in a short pause")
        XCTAssertEqual(
            FindPhoneTone.sample(at: 0.0371),
            FindPhoneTone.sample(at: 0.0371 + FindPhoneTone.cycle), accuracy: 0.05)
    }

    func testSystemAlarmNeedsOptInAuthorizationAndUnexpiredSignedCommand() {
        XCTAssertFalse(
            SystemFindPhoneEligibility.canSchedule(
                optedIn: false, authorized: true, commandExpires: 200, now: 100))
        XCTAssertFalse(
            SystemFindPhoneEligibility.canSchedule(
                optedIn: true, authorized: false, commandExpires: 200, now: 100))
        XCTAssertFalse(
            SystemFindPhoneEligibility.canSchedule(
                optedIn: true, authorized: true, commandExpires: 103, now: 100))
        XCTAssertTrue(
            SystemFindPhoneEligibility.canSchedule(
                optedIn: true, authorized: true, commandExpires: 120, now: 100))
    }
}
