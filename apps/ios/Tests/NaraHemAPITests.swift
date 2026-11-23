import XCTest

@testable import NaraHem

/// NaraHemAPI against FakeHouseholdServer: addresses, sign-in, saved sessions, token refresh and
/// invitations.
@MainActor
final class NaraHemAPITests: XCTestCase {
    private var fake: FakeHouseholdServer!
    private var api: NaraHemAPI!
    private let address = FakeHouseholdServer.address

    override func setUp() async throws {
        SecureVault.memory = [:]
        SecureVault.delete("ios-native-session")
        fake = FakeHouseholdServer()
        api = NaraHemAPI(configuration: fake.start())
    }

    override func tearDown() async throws {
        SecureVault.delete("ios-native-session")
        FakeHouseholdServer.active = nil
        SecureVault.memory = nil
    }

    /// Returns the message of the error `body` throws, or nil if it succeeds.
    private func message(_ body: () async throws -> Void) async -> String? {
        do {
            try await body()
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    func testServerAddressesMustBePlainHttpsOrigins() throws {
        XCTAssertEqual(
            try NaraHemAPI.serverURL(" family.example:8443 ").absoluteString,
            "https://family.example:8443")
        XCTAssertEqual(try NaraHemAPI.serverURL("https://family.example/").host, "family.example")
        for bad in [
            "http://family.example", "https://user:pw@family.example", "https://family.example/x",
            "https://family.example?q=1", "https://family.example#f", "",
        ] {
            XCTAssertThrowsError(try NaraHemAPI.serverURL(bad), bad)
        }
    }

    func testSignInLoadsTheAccountAndRemembersTheSession() async throws {
        let blank = await message {
            _ = try await self.api.signIn(server: self.address, identifier: " ", password: "pw")
        }
        XCTAssertEqual(blank, "Enter your email or phone number and password.")
        fake.role = "admin"
        let account = try await api.signIn(
            server: address, identifier: " sam@example.invalid ", password: "pw")
        XCTAssertEqual(account.id, fake.phoneAccount)
        XCTAssertEqual(account.household, fake.household)
        XCTAssertEqual(account.role, "admin")
        XCTAssertEqual(fake.bodies["POST /api/login"]?["email"] as? String, "sam@example.invalid")
        XCTAssertNotNil(SecureVault.get("ios-native-session"))
        XCTAssertEqual(api.token, fake.accessToken)

        let later = NaraHemAPI(configuration: fake.start())
        let restored = try await later.restore(server: address)
        XCTAssertEqual(restored?.id, fake.phoneAccount)
        XCTAssertEqual(fake.count("POST /api/native/session/refresh"), 1)
        let elsewhere = try await NaraHemAPI(configuration: fake.start())
            .restore(server: "https://other.test")
        XCTAssertNil(elsewhere)
    }

    func testExpiredAccessIsRefreshedOnceAndRetried() async throws {
        _ = try await api.signIn(server: address, identifier: "sam", password: "pw")
        fake.accessToken = "rotated-on-the-server"
        let members = try await api.accountRequest("/api/household/members")
        XCTAssertNotNil(members["members"])
        XCTAssertEqual(fake.count("POST /api/native/session/refresh"), 1)
        XCTAssertEqual(api.token, fake.accessToken)
        fake.failNext("GET /api/household/members", 409, "Conflict")
        let conflict = await message {
            _ = try await self.api.accountRequest("/api/household/members")
        }
        XCTAssertEqual(conflict, "Conflict")
        XCTAssertEqual(fake.count("POST /api/native/session/refresh"), 1)
    }

    func testSignedOutRequestsAndBadPathsAreRefused() async throws {
        let signedOut = await message { _ = try await self.api.accountRequest("/api/household") }
        XCTAssertEqual(signedOut, "Sign in required")
        try api.setServer(address)
        let path = await message {
            _ = try await self.api.deviceRequest("https://evil.test/api/x", credential: "c")
        }
        XCTAssertEqual(path, "Invalid API endpoint")
        fake.failNext("POST /api/login", 500)
        let failed = await message {
            _ = try await self.api.signIn(server: self.address, identifier: "a", password: "b")
        }
        XCTAssertEqual(failed, "Failed")
    }

    func testUsernamesAreCheckedThenSaved() async throws {
        _ = try await api.signIn(server: address, identifier: "sam", password: "pw")
        let rule = "Use one or two words: 3–64 letters, numbers, periods, dashes or apostrophes."
        for name in ["x", "John Q Doe"] {
            let invalid = await message { _ = try await self.api.updateUsername(name) }
            XCTAssertEqual(invalid, rule)
        }
        let saved = try await api.updateUsername(" sam.lee ")
        XCTAssertEqual(saved, "sam.lee")
        // Two words are fine, with the spaces between them tidied.
        let named = try await api.updateUsername("  John   Doe ")
        XCTAssertEqual(named, "John Doe")
    }

    func testSignOutRevokesTheSessionAndForgetsIt() async throws {
        _ = try await api.signIn(server: address, identifier: "sam", password: "pw")
        await api.signOut()
        XCTAssertNil(api.token)
        XCTAssertNil(SecureVault.get("ios-native-session"))
        XCTAssertEqual(fake.count("POST /api/native/session/revoke"), 1)
        XCTAssertEqual(fake.count("POST /api/logout"), 1)
    }

    func testInvitationsAndAccessRequests() async throws {
        try await api.register(
            server: address, contact: "+14155550123", username: "John Doe",
            password: "a long synthetic password")
        let registered = try XCTUnwrap(fake.bodies["POST /api/enrollment/register"])
        XCTAssertEqual(registered["email"] as? String, "+14155550123")
        XCTAssertEqual(registered["username"] as? String, "John Doe")
        let request = try await api.requestAccess(
            server: address, contact: "sam@example.invalid", name: "Sam", relationship: "Child")
        XCTAssertEqual(request, "Request sent.")
    }
}
