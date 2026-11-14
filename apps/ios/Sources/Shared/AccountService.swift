import Foundation

/// Account operations against the household server: sign-in, session restore, invitations and
/// account requests. Implemented by NaraHemAPI.
@MainActor
protocol AccountService: AnyObject {
    /// Restores the stored session for this server. Returns nil if there is none.
    func restore(server: String) async throws -> NaraHemAccount?

    /// Revokes the session on the server when reachable and clears it locally.
    func signOut() async

    /// Changes the display name and returns the saved value.
    func updateUsername(_ name: String) async throws -> String

    /// Asks the server to email a new invitation link. Returns the server's message.
    func requestInvite(server: String, contact: String) async throws -> String

    /// Completes an invitation by setting the username and password.
    func verifyInvite(server: String, code: String, username: String, password: String) async throws

    /// Signs in with email and password and stores the refresh token.
    func signIn(server: String, identifier: String, password: String) async throws -> NaraHemAccount

    /// Sends a request as the signed-in account.
    func accountRequest(
        _ path: String, payload: Wire.Object?, method: String
    ) async throws -> Wire.Object

    /// Sends a request for the admin to invite this person.
    func requestAccess(
        server: String, contact: String, name: String, relationship: String
    ) async throws -> String
}

/// NaraHemAPI provides the account operations.
extension NaraHemAPI: AccountService {}

extension AccountService {
    /// Sends a six-digit code to a new email address or phone number for this account. Nothing
    /// changes until `confirmContactChange`. Returns where the code went.
    func requestContactChange(
        _ value: String, password: String, phone: Bool
    ) async throws -> String {
        let reply = try await accountRequest(
            "/api/account/contact",
            payload: ["value": value, "password": password, "kind": phone ? "phone" : "email"],
            method: "POST")
        return (reply["to"] as? String) ?? value
    }

    /// Returns the account's email address and phone number, and whether the server can text.
    func contactDetails() async throws -> ContactDetails {
        let session = try await accountRequest("/api/session", payload: nil, method: "GET")
        let setup = try await accountRequest("/api/setup", payload: nil, method: "GET")
        return ContactDetails(
            email: session["email"] as? String, phone: session["phone"] as? String,
            textingOn: setup["texting"] as? Bool ?? false)
    }

    /// Uses the new email address or phone number once its code is entered.
    func confirmContactChange(code: String) async throws {
        _ = try await accountRequest(
            "/api/account/contact/verify", payload: ["code": code], method: "POST")
    }
}
