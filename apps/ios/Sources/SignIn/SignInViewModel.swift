import Foundation
import Observation

/// View model for sign-in, invitations and access requests.
@MainActor
@Observable
final class SignInViewModel {
    var contact = ""
    var password = ""

    /// Current form: "signin", "register" or "request".
    var mode = "signin"

    /// True while asking for the email; the password is asked on the next step.
    var firstStep = true
    var showPassword = false
    var enrollmentUsername = ""
    var enrollmentPassword = ""
    var enrollmentConfirmPassword = ""
    var requestedName = ""
    var relationship = ""
    let session: HouseholdSession
    private let accounts: AccountService
    private let household: HouseholdService
    private let settings: AppSettings
    private let tracker: LocationTracker

    /// True when the registration form has a name and matching passwords of 15+ characters.
    var canRegister: Bool {
        !session.busy && !session.server.isEmpty && !contact.isEmpty
            && enrollmentPassword.count >= 15 && enrollmentPassword == enrollmentConfirmPassword
            && enrollmentUsername.trimmingCharacters(in: .whitespaces).count >= 3
    }

    /// Creates the view model on the shared session.
    init(
        session: HouseholdSession, accounts: AccountService, household: HouseholdService,
        settings: AppSettings, tracker: LocationTracker
    ) {
        self.session = session
        self.accounts = accounts
        self.household = household
        self.settings = settings
        self.tracker = tracker
    }

    /// Signs in with the entered email and password.
    func signIn() {
        session.work { try await self.signInNow() }
    }

    /// Signs in with the entered email and password, inside work already started.
    private func signInNow() async throws {
        let user = try await accounts.signIn(
            server: session.server, identifier: contact, password: password)
        session.account = user
        password = ""
        session.signedIn = true
        tracker.askForAlwaysAfterSignIn()
        settings.server = session.server
        _ = household.restore(account: user, server: session.server)
        await session.refreshNow()
        session.startForegroundRefresh()
        let next =
            session.deviceStatus == "ready"
            ? "Household connected." : "Approve this device to share locations."
        session.message = "Signed in. \(next)"
    }

    /// Registers the invited account, then signs in, which leads to approving this iPhone with
    /// the code that also confirms the account.
    func register() {
        session.work {
            try await self.accounts.register(
                server: self.session.server, contact: self.contact,
                username: self.enrollmentUsername, password: self.enrollmentPassword)
            self.password = self.enrollmentPassword
            self.enrollmentPassword = ""
            self.enrollmentConfirmPassword = ""
            self.mode = "signin"
            self.firstStep = false
            try await self.signInNow()
        }
    }

    /// Sends a request for the admin to invite this person.
    func requestAccess() {
        session.work {
            self.session.message = try await self.accounts.requestAccess(
                server: self.session.server, contact: self.contact, name: self.requestedName,
                relationship: self.relationship)
        }
    }
}
