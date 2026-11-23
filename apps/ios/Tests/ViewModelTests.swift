import CoreLocation
import XCTest

@testable import NaraHem

/// The screens' view models with an in-memory household: no server, Keychain or encryption.
@MainActor
final class ViewModelTests: XCTestCase {
    func testApprovalExplainsEachDeviceStatus() {
        let app = AppViewModel.preview(deviceStatus: "email-code")
        XCTAssertEqual(
            app.approval.explanation,
            "Confirm it's you with a code sent to your email or phone to register this iPhone.")
        app.session.deviceStatus = "revoked"
        XCTAssertTrue(app.approval.explanation.hasPrefix("This device was revoked"))
    }

    func testInitialsAreTheFirstLetterOfEachWord() {
        XCTAssertEqual(Initials.of("John Doe"), "JD")
        XCTAssertEqual(Initials.of("kim"), "K")
        XCTAssertEqual(Initials.of(" åsa  o'neil "), "ÅO")
        XCTAssertEqual(Initials.of(""), "?")
    }

    func testRegisteringNeedsANameAndMatchingPasswords() {
        let model = AppViewModel.preview(signedIn: false).signIn
        model.session.server = "https://family.example"
        model.contact = "+14155550123"
        model.enrollmentUsername = "John Doe"
        model.enrollmentPassword = "a long synthetic password"
        model.enrollmentConfirmPassword = "something else"
        XCTAssertFalse(model.canRegister)
        model.enrollmentConfirmPassword = model.enrollmentPassword
        XCTAssertTrue(model.canRegister)
        model.enrollmentUsername = " s "
        XCTAssertFalse(model.canRegister)
    }

    func testMapUsesSharedLocationsAndShowsTheLocalMarkerUntilOwnLocationArrives() {
        let app = AppViewModel.preview()
        let alex = app.session.members.first(where: { $0.id == "alex" })!
        let coordinate = app.map.coordinate(for: alex)
        XCTAssertEqual(coordinate?.latitude ?? 0, 40.7306, accuracy: 0.0001)
        XCTAssertFalse(app.map.showsLocalFix)  // no local fix yet
        XCTAssertNil(app.map.coordinate(for: HouseholdMember(id: "new", name: "New")))
    }

    func testOverlappingPlacesAreReported() {
        let app = AppViewModel.preview()
        let home = app.session.places[0]
        let nextDoor = SavedPlace(
            id: "next", name: "Next door", lat: home.lat + 0.0005, lon: home.lon, radius: 50,
            recordId: "", alerts: [:], data: [:])
        let faraway = SavedPlace(
            id: "far", name: "Far", lat: home.lat + 1, lon: home.lon, radius: 50,
            recordId: "", alerts: [:], data: [:])
        app.session.places = [home, nextDoor, faraway]
        XCTAssertEqual(app.places.overlaps(of: home).map(\.id), ["next"])
    }

    func testSavingAndDeletingAPlaceUpdatesTheSession() async throws {
        let app = AppViewModel.preview()
        app.places.savePlace(name: "School", lat: 40.72, lon: -74.0, radius: 100, existing: nil)
        try await finishWork(app)
        XCTAssertTrue(app.session.places.contains(where: { $0.name == "School" }))
        XCTAssertEqual(app.session.message, "Place saved for your household.")
        let school = app.session.places.first(where: { $0.name == "School" })!
        app.places.deletePlace(school)
        try await finishWork(app)
        XCTAssertFalse(app.session.places.contains(where: { $0.name == "School" }))
    }

    func testVeryShortTripsAreHidden() {
        let app = AppViewModel.preview()
        app.trips.trips = [
            trip("noise", distance: 10, minutes: 1), trip("walk", distance: 400, minutes: 6),
        ]
        XCTAssertEqual(app.trips.visibleTrips.map(\.id), ["walk"])
    }

    func testBackgroundCollectionWithoutAlwaysLocationExplains() {
        let app = AppViewModel.preview()
        guard app.settings.tracker.locationPermission != .authorizedAlways else { return }
        app.settings.setTracking(true)
        XCTAssertFalse(app.settings.tracker.trackingEnabled)
        XCTAssertTrue(app.session.message.hasPrefix("Allow Always Location"))
    }

    private func trip(_ id: String, distance: Double, minutes: Int) -> HouseholdTrip {
        HouseholdTrip(
            id: id, accountId: "me", deviceId: "phone", startedAt: 0, endedAt: minutes * 60_000,
            distance: distance, maxSpeed: 2, samples: 10, tripId: nil)
    }

    /// Wait for the session's current action to finish.
    private func finishWork(_ app: AppViewModel) async throws {
        for _ in 0..<200 where app.session.busy {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertFalse(app.session.busy)
    }
}
