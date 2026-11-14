import Foundation
import Observation

/// View model for sign-in, invitations and access requests.
@MainActor
@Observable
final class SignInViewModel {
    var contact = ""
    var password = ""

    /// Current form: "signin", "invitation" or "request".
    var mode = "signin"

    /// True while asking for the email; the password is asked on the next step.
    var firstStep = true
    var showPassword = false
    var enrollmentUsername = ""
    var enrollmentPassword = ""
    var enrollmentConfirmPassword = ""
    var invitationCode = ""
    var requestedName = ""
    var relationship = ""
    let session: HouseholdSession
    private let accounts: AccountService
    private let household: HouseholdService
    private let settings: AppSettings
    private let tracker: LocationTracker

    /// True when the invitation form has a token, a username and matching passwords.
    var canConfirmInvitation: Bool {
        !session.busy && !invitationCode.isEmpty && enrollmentPassword == enrollmentConfirmPassword
            && enrollmentUsername.count >= 3
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
        session.work {
            let user = try await self.accounts.signIn(
                server: self.session.server, identifier: self.contact, password: self.password)
            self.session.account = user
            self.password = ""
            self.session.signedIn = true
            self.tracker.askForAlwaysAfterSignIn()
            self.settings.server = self.session.server
            _ = self.household.restore(account: user, server: self.session.server)
            await self.session.refreshNow()
            self.session.startForegroundRefresh()
            let next =
                self.session.deviceStatus == "ready"
                ? "Household connected." : "Approve this device to share locations."
            self.session.message = "Signed in. \(next)"
        }
    }

    /// Asks the server to email a new invitation link.
    func requestInvite() {
        session.work {
            self.session.message = try await self.accounts.requestInvite(
                server: self.session.server, contact: self.contact)
        }
    }

    /// Completes an invitation and signs in.
    func verifyInvite() {
        session.work {
            try await self.accounts.verifyInvite(
                server: self.session.server, code: self.invitationCode,
                username: self.enrollmentUsername, password: self.enrollmentPassword)
            self.session.message = "Invitation verified. Sign in and approve this device."
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
