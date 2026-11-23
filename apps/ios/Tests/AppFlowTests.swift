import UIKit
import XCTest

@testable import NaraHem

/// The sign-in, approval and Settings view models with the preview household and accounts.
@MainActor
final class AppFlowTests: XCTestCase {
    private var fake = PreviewHousehold()
    private var accounts = PreviewAccounts()

    /// Builds the app on fresh preview services, signed in with a ready device unless specified,
    /// like AppViewModel.preview but keeping the fakes.
    private func makeApp(signedIn: Bool = true, deviceStatus: String = "ready") -> AppViewModel {
        fake = PreviewHousehold()
        accounts = PreviewAccounts()
        let suite = "narahem.tests." + Wire.freshId()
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        let app = AppViewModel(
            container: AppContainer(
                accounts: accounts, household: fake, settings: AppSettings(defaults: defaults)))
        app.session.restoring = false
        if signedIn {
            app.session.signedIn = true
            app.session.account = PreviewAccounts.sam
            app.session.deviceStatus = deviceStatus
            app.session.members = fake.members
            app.session.places = fake.places
            app.session.audienceChoices = fake.choices
            app.session.sharing = true
        }
        return app
    }

    private func finishWork(_ app: AppViewModel) async throws {
        for _ in 0..<300 where app.session.busy {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertFalse(app.session.busy)
    }

    func testSignInConnectsTheHouseholdOrExplainsTheError() async throws {
        let app = makeApp(signedIn: false)
        app.session.server = "https://family.example"
        app.signIn.contact = "sam@example.invalid"
        app.signIn.password = "pw"
        app.signIn.signIn()
        try await finishWork(app)
        XCTAssertTrue(app.session.signedIn)
        XCTAssertEqual(app.signIn.password, "")
        XCTAssertTrue(app.session.message.hasPrefix("Signed in."))

        let failing = makeApp(signedIn: false)
        accounts.signInError = "Email or password is wrong"
        failing.signIn.signIn()
        try await finishWork(failing)
        XCTAssertFalse(failing.session.signedIn)
        XCTAssertEqual(failing.session.message, "Email or password is wrong")
    }

    func testInvitationStepsReportTheServersMessage() async throws {
        let app = makeApp(signedIn: false)
        app.signIn.contact = "+14155550123"
        app.signIn.enrollmentUsername = "John Doe"
        app.signIn.enrollmentPassword = "a long synthetic password"
        app.signIn.register()
        try await finishWork(app)
        // Registering signs straight in, on to approving this iPhone.
        XCTAssertTrue(accounts.calls.contains("register"))
        XCTAssertTrue(app.session.signedIn)
        XCTAssertEqual(app.signIn.mode, "signin")
        app.session.signedIn = false
        app.signIn.requestAccess()
        try await finishWork(app)
        XCTAssertEqual(app.session.message, "Request sent.")
    }

    func testApprovalStepsCallTheHousehold() async throws {
        let app = makeApp(deviceStatus: "email-code")
        fake.deviceStatus = "email-code"
        app.approval.requestPhoneCode()
        try await finishWork(app)
        XCTAssertTrue(app.session.message.hasPrefix("A six-digit code was sent"))
        app.approval.code = "123456"
        app.approval.confirmPhoneCode()
        try await finishWork(app)
        app.approval.restartPhoneRegistration()
        try await finishWork(app)
        app.approval.requestFirstCode()
        try await finishWork(app)
        app.approval.finishFirstCode()
        try await finishWork(app)
        app.approval.enrollDevice()
        try await finishWork(app)
        XCTAssertEqual(
            fake.calls,
            [
                "requestPhoneCode", "verifyPhoneCode", "discardPendingPhone", "enroll",
                "sendBootstrapCode", "bootstrap", "enroll",
            ])
        XCTAssertEqual(app.session.deviceStatus, "ready")
    }

    func testApprovalExplainsEveryStatus() {
        let app = makeApp()
        for status in [
            "register", "verify-email", "first-device", "email-code", "replacement-required",
            "pending", "pairing", "revoked", "unknown",
        ] {
            app.session.deviceStatus = status
            XCTAssertFalse(app.approval.explanation.isEmpty, status)
        }
    }

    func testSettingsChangeSharingAudienceAndFindMyPhone() async throws {
        let app = makeApp()
        app.settings.opened()
        XCTAssertEqual(app.settings.editableUsername, "Sam")
        XCTAssertEqual(app.settings.me?.name, "Sam")
        XCTAssertFalse(app.settings.locationDescription.isEmpty)
        app.settings.setSharing(false)
        try await finishWork(app)
        XCTAssertFalse(fake.sharing)
        XCTAssertEqual(app.session.message, "Location sharing paused.")
        app.settings.setViewer("alex", included: true)
        try await finishWork(app)
        XCTAssertEqual(fake.audience, ["alex"])
        app.session.syncProblem = true
        app.settings.setViewer("alex", included: false)
        try await finishWork(app)
        XCTAssertEqual(app.session.message, "Refresh the household before editing recipients")
        app.settings.setFindPhone(true)
        try await finishWork(app)
        XCTAssertTrue(fake.findPhoneEnabled)
        app.settings.clearLocalLocations()
        XCTAssertEqual(app.session.message, "Offline locations and pending trips cleared.")
    }

    func testUsernameAndProfilePhotoAreSaved() async throws {
        let app = makeApp()
        app.settings.editableUsername = "sam.lee"
        app.settings.changeUsername()
        try await finishWork(app)
        XCTAssertEqual(app.session.account?.name, "sam.lee")
        let image = UIGraphicsImageRenderer(size: CGSize(width: 300, height: 200)).image {
            context in
            UIColor.orange.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 300, height: 200))
        }
        app.settings.saveProfileImage(image)
        try await finishWork(app)
        XCTAssertTrue(fake.calls.contains("savePhoto"))
    }

    func testRevokingThePhoneSignsOut() async throws {
        let app = makeApp()
        app.settings.revokeThisPhone()
        try await finishWork(app)
        XCTAssertTrue(fake.calls.contains("revokeThisPhone"))
        XCTAssertFalse(app.session.signedIn)
    }

    func testTripsLoadForAMemberAndOpenRoutes() async throws {
        let app = makeApp()
        fake.trips = [
            HouseholdTrip(
                id: "t1", accountId: "alex", deviceId: "phone", startedAt: 0,
                endedAt: 20 * 60_000, distance: 5000, maxSpeed: 20, samples: 30, tripId: nil)
        ]
        app.trips.openTrips()
        app.trips.loadTrips(memberId: "alex", days: 7)
        for _ in 0..<300 where app.trips.trips.isEmpty {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertEqual(app.trips.trips.map(\.id), ["t1"])
        XCTAssertEqual(app.trips.tripDays, 7)
        let preview = await app.trips.cardPreview(for: fake.trips[0])
        XCTAssertEqual(preview.id, "t1")
        app.trips.loadTripRoute(fake.trips[0])
        for _ in 0..<300 where app.trips.isLoadingTripRoute {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertFalse(app.trips.isLoadingTripRoute)
    }

    func testSigningOutClearsTheSession() async throws {
        let app = makeApp()
        app.settings.signOut()
        for _ in 0..<300 where app.session.signedIn {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertFalse(app.session.signedIn)
        XCTAssertNil(app.session.account)
    }
}
