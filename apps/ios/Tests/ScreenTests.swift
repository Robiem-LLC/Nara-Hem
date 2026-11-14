import CoreLocation
import SwiftUI
import XCTest

@testable import NaraHem

/// Lays out every screen in its main states on the preview services, so each SwiftUI body runs
/// without crashing.
@MainActor
final class ScreenTests: XCTestCase {
    private var window: UIWindow?

    private let trip: HouseholdTrip = {
        var trip = HouseholdTrip(
            id: "t1", accountId: "alex", deviceId: "phone", startedAt: 1_700_000_000_000,
            endedAt: 1_700_001_200_000, distance: 5000, maxSpeed: 20, samples: 30,
            tripId: "trip-1")
        trip.start = [40.7128, -74.0060]
        trip.end = [40.7306, -73.9866]
        trip.preview = [[40.7128, -74.0060], [40.72, -74.0], [40.7306, -73.9866]]
        trip.startLabel = "Home"
        return trip
    }()

    override func tearDown() async throws {
        window?.isHidden = true
        window = nil
    }

    /// Shows `view` in a phone-sized window and lets SwiftUI lay it out.
    private func render<Content: View>(_ view: Content) {
        let host = UIHostingController(rootView: view)
        let frame = CGRect(x: 0, y: 0, width: 393, height: 852)
        let window = window ?? UIWindow(frame: frame)
        window.rootViewController = host
        window.makeKeyAndVisible()
        host.view.frame = frame
        host.view.setNeedsLayout()
        host.view.layoutIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.05))
        self.window = window
        XCTAssertNotNil(host.view)
    }

    func testRootShowsRestoringSignInApprovalAndTabs() {
        let restoring = AppViewModel.preview(signedIn: false)
        restoring.session.restoring = true
        render(RootView(app: restoring))
        render(RootView(app: AppViewModel.preview(signedIn: false)))
        render(RootView(app: AppViewModel.preview(deviceStatus: "pending")))
        render(RootView(app: AppViewModel.preview()))
    }

    func testSignInShowsEachMode() {
        let app = AppViewModel.preview(signedIn: false)
        render(SignInView(model: app.signIn))
        app.signIn.firstStep = false
        app.signIn.showPassword = true
        render(SignInView(model: app.signIn))
        for mode in ["invitation", "request"] {
            app.signIn.mode = mode
            render(SignInView(model: app.signIn))
        }
        app.session.busy = true
        app.session.message = "Working"
        render(SignInView(model: app.signIn))
    }

    func testApprovalShowsEveryDeviceStatus() {
        for status in [
            "register", "verify-email", "first-device", "email-code", "replacement-required",
            "pending", "pairing", "revoked",
        ] {
            let app = AppViewModel.preview(deviceStatus: status)
            app.session.pairingCode = "424242"
            app.session.message = "Status: " + status
            render(DeviceApprovalView(model: app.approval))
        }
    }

    func testMapShowsMembersPlacesAndMessages() {
        let app = AppViewModel.preview()
        render(HouseholdMapScreen(model: app.map, onViewTrips: { _ in }))
        app.session.members = []
        app.session.syncProblem = true
        app.session.message = "Could not refresh"
        render(HouseholdMapScreen(model: app.map, onViewTrips: { _ in }))
    }

    func testTripsShowTheListAndAnEmptyDay() {
        let app = AppViewModel.preview()
        render(TripsScreen(model: app.trips, places: app.places))
        app.trips.selectedMemberId = "alex"
        app.trips.trips = [trip]
        app.trips.tripHistoryPartial = true
        app.trips.roadMatchingEnabled = false
        render(TripsScreen(model: app.trips, places: app.places))
    }

    func testTripPiecesRender() {
        let points = (0..<3).map { index in
            HouseholdTripPoint(
                id: "p\(index)", lat: 40.7128 + Double(index) * 0.01, lon: -74.0,
                capturedAt: trip.startedAt + index * 60_000, tripId: trip.tripId)
        }
        let home = PreviewHousehold.samplePlaces
        render(
            TripHistoryRow(
                trip: trip, viewerId: "me", places: home, loadDetails: { $0 }, open: { _ in }))
        render(TripEndpointsLabel(trip: trip, points: points, places: home))
        var unlabelled = trip
        unlabelled.startLabel = nil
        unlabelled.start = nil
        render(TripEndpointsLabel(trip: unlabelled, points: [], places: []))
        render(TripPreviewImage(trip: trip, viewerId: "me"))
        render(
            TripDetailMap(
                trip: trip, points: points, places: home,
                members: PreviewHousehold.sampleMembers, onSavePlace: { _, _, _, _, _ in }))
    }

    func testPlacesListAndEditor() {
        let app = AppViewModel.preview()
        render(PlacesScreen(model: app.places))
        app.session.places = []
        render(PlacesScreen(model: app.places))
        render(
            PlaceEditor(
                existing: nil, members: PreviewHousehold.sampleMembers,
                initialCoordinate: CLLocationCoordinate2D(latitude: 40.71, longitude: -74.0),
                onSave: { _, _, _, _, _ in }))
        render(
            PlaceEditor(
                existing: PreviewHousehold.samplePlaces[0], members: PreviewHousehold.sampleMembers,
                initialCoordinate: nil, onDelete: {}, onSave: { _, _, _, _, _ in }))
    }

    func testSettingsInSeveralStates() {
        let app = AppViewModel.preview()
        render(SettingsScreen(model: app.settings))
        app.session.sharing = false
        app.session.findPhoneEnabled = true
        app.session.ownerViewerId = "owner"
        app.session.audience = ["alex", "owner"]
        app.session.notificationPermissionDenied = true
        app.session.syncProblem = true
        app.session.message = "Location sharing paused."
        render(SettingsScreen(model: app.settings))
        app.session.account = NaraHemAccount(
            id: "me", name: "Admin", household: "Home", role: "admin", verified: true)
        app.session.audienceChoices = []
        render(SettingsScreen(model: app.settings))
    }

    func testSmallPiecesRender() {
        for kind in 0..<4 { render(NaraHemNavIcon(kind: kind, color: .green)) }
        var member = PreviewHousehold.sampleMembers[0]
        render(ProfileAvatar(member: member))
        member.photo = "data:image/jpeg;base64,not-an-image"
        render(ProfileAvatar(member: member))
        let app = AppViewModel.preview()
        app.session.busy = true
        app.session.message = "Saved"
        render(NoticeView(session: app.session))
    }
}
