import Foundation
import Observation

/// View model for device setup: registration, email codes and first-device bootstrap.
@MainActor
@Observable
final class DeviceApprovalViewModel {
    /// The six-digit code entered from the email.
    var code = ""
    let session: HouseholdSession
    private let household: HouseholdService

    /// Instructions for the current setup state.
    var explanation: String {
        switch session.deviceStatus {
        case "register":
            return "Sign-in is complete, but this iPhone is not registered with your household yet."
        case "first-device": return "Start a brand-new household with a time-limited email code."
        case "email-code":
            return
                "Confirm it's you with a code sent to your email or phone to register this iPhone."
        case "replacement-required":
            return "Your previous phone must be revoked before this iPhone can replace it."
        case "pending", "pairing":
            return
                """
                This iPhone must be cryptographically approved by an existing trusted \
                household device.
                """
        case "revoked": return "This device was revoked. A trusted owner must restore access."
        case "verify-email": return "Ask the household administrator to approve your account."
        default: return "Updating signed household membership."
        }
    }

    /// Creates the view model on the shared session.
    init(session: HouseholdSession, household: HouseholdService) {
        self.session = session
        self.household = household
    }

    /// Re-checks whether this device has been approved.
    func checkApproval() { session.refreshHousehold() }

    /// Signs out.
    func signOut() { session.signOut() }

    /// Generates keys and registers this device.
    func enrollDevice() {
        session.work {
            guard let account = self.session.account else {
                throw NaraHemProtocolError.rejected("Sign in first")
            }
            try await self.household.enroll(account: account, server: self.session.server)
            await self.session.refreshNow()
        }
    }

    /// Requests the email with this phone's approval code.
    func requestPhoneCode() {
        session.work {
            try await self.household.requestPhoneCode()
            self.session.message =
                "A six-digit code was sent to your email or phone. It expires in ten minutes."
        }
    }

    /// Submits the approval code.
    func confirmPhoneCode() {
        session.work {
            try await self.household.verifyPhoneCode(self.code)
            await self.session.refreshNow()
        }
    }

    /// Discards the pending registration and registers again.
    func restartPhoneRegistration() {
        session.work {
            await self.household.discardPendingPhone()
            guard let account = self.session.account else { return }
            try await self.household.enroll(account: account, server: self.session.server)
            await self.session.refreshNow()
        }
    }

    /// Requests the first-device email code for a new household.
    func requestFirstCode() {
        session.work {
            try await self.household.sendBootstrapCode()
            self.session.message = "Six-digit verification code sent to your administrator email."
        }
    }

    /// Registers the first device with the emailed code.
    func finishFirstCode() {
        session.work {
            try await self.household.bootstrap(code: self.code)
            await self.session.refreshNow()
        }
    }
}
