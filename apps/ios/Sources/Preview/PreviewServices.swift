#if DEBUG
    import Foundation

    /// In-memory HouseholdService for previews and tests. No server, keychain or encryption;
    /// records calls in `calls`.
    @MainActor
    final class PreviewHousehold: HouseholdService {
        static let sampleMembers = [
            HouseholdMember(
                id: "me", name: "Sam", lat: 40.7128, lon: -74.0060, capturedAt: 1, battery: 82),
            HouseholdMember(id: "alex", name: "Alex", lat: 40.7306, lon: -73.9866, capturedAt: 1),
        ]
        static let samplePlaces = [
            SavedPlace(
                id: "home", name: "Home", lat: 40.7128, lon: -74.0060, radius: 120,
                recordId: "", alerts: [:], data: [:])
        ]

        var identity: TrustedIdentity?
        var places: [SavedPlace]
        var audience: Set<String> = []
        var choices: [AudienceChoice] = [AudienceChoice(id: "alex", name: "Alex")]
        var ownerViewerId: String?
        var sharing = true
        var findPhoneEnabled = false
        var members: [HouseholdMember]
        var deviceStatus = "ready"
        var trips: [HouseholdTrip] = []
        /// What was asked of it, for tests to check.
        var calls: [String] = []

        init(
            members: [HouseholdMember] = PreviewHousehold.sampleMembers,
            places: [SavedPlace] = PreviewHousehold.samplePlaces
        ) {
            self.members = members
            self.places = places
        }

        func restore(account: NaraHemAccount, server: String) -> Bool { true }
        func status(account: NaraHemAccount) async throws -> String { deviceStatus }
        func ownCode() async throws -> String { "123456" }
        func requestPhoneCode() async throws { calls.append("requestPhoneCode") }
        func discardPendingPhone() async { calls.append("discardPendingPhone") }
        func sendBootstrapCode() async throws { calls.append("sendBootstrapCode") }
        func refreshAudience() async throws -> [String] { [] }
        func setSharing(_ enabled: Bool) async throws { sharing = enabled }
        func setAudience(_ selected: Set<String>) async throws { audience = selected }
        func savePhoto(jpeg: Data, name: String) async throws { calls.append("savePhoto") }
        func tripRoute(_ trip: HouseholdTrip) async throws -> [HouseholdTripPoint] { [] }
        func publishLocation(_ fix: LocalLocation) async throws { calls.append("publishLocation") }
        func publishTrip(_ trip: HouseholdTrip) async throws { calls.append("publishTrip") }
        func setFindPhone(_ enabled: Bool) async throws { findPhoneEnabled = enabled }
        func findCommand() async throws -> (String, String, Int)? { nil }
        func reportFind(_ id: String, state: String, reason: String) async {}
        func subscribePush(token: String, environment: String) async throws {}
        func unsubscribePush() async throws {}

        func enroll(account: NaraHemAccount, server: String) async throws {
            calls.append("enroll")
            deviceStatus = "ready"
        }

        func verifyPhoneCode(_ code: String) async throws {
            calls.append("verifyPhoneCode")
            deviceStatus = "ready"
        }

        func revokeThisPhone() async throws {
            calls.append("revokeThisPhone")
            deviceStatus = "register"
        }

        func bootstrap(code: String) async throws {
            calls.append("bootstrap")
            deviceStatus = "ready"
        }

        func reportDevicePermissions(
            foreground: Bool, background: Bool, alarm: Bool, notifications: Bool, sharing: Bool
        ) async throws {}

        func snapshot() async throws -> HouseholdSnapshot {
            HouseholdSnapshot(members: members, places: places)
        }

        func savePlace(
            name: String, lat: Double, lon: Double, radius: Double, existing: SavedPlace?,
            alerts: Wire.Object
        ) async throws {
            let place = SavedPlace(
                id: existing?.id ?? "place-\(places.count + 1)", name: name, lat: lat, lon: lon,
                radius: radius, recordId: existing?.recordId ?? "", alerts: alerts, data: [:])
            places.removeAll { $0.id == place.id }
            places.append(place)
        }

        func deletePlace(_ place: SavedPlace) async throws {
            places.removeAll { $0.id == place.id }
        }

        func trips(
            accountId: String, days: Int
        ) async throws -> ([HouseholdTrip], [HouseholdTripPoint], Bool?, Bool?) {
            (trips.filter { $0.accountId == accountId }, [], nil, nil)
        }

        func publishLocations(_ fixes: [LocalLocation]) async throws {
            calls.append("publishLocations")
        }
    }

    /// In-memory AccountService for previews and tests. Every call succeeds immediately.
    @MainActor
    final class PreviewAccounts: AccountService {
        static let sam = NaraHemAccount(
            id: "me", name: "Sam", household: "Home", role: "member", verified: true)

        /// Set to make sign-in fail with this message.
        var signInError: String?
        var calls: [String] = []

        func restore(server: String) async throws -> NaraHemAccount? { nil }
        func signOut() async { calls.append("signOut") }
        func updateUsername(_ name: String) async throws -> String { name }

        func signIn(
            server: String, identifier: String, password: String
        ) async throws -> NaraHemAccount {
            if let signInError { throw NaraHemProtocolError.rejected(signInError) }
            return Self.sam
        }

        func accountRequest(
            _ path: String, payload: Wire.Object?, method: String
        ) async throws -> Wire.Object {
            [:]
        }

        func requestInvite(server: String, contact: String) async throws -> String {
            "Invitation email sent."
        }

        func verifyInvite(
            server: String, code: String, username: String, password: String
        ) async throws {
            calls.append("verifyInvite")
        }

        func requestAccess(
            server: String, contact: String, name: String, relationship: String
        ) async throws -> String {
            "Request sent."
        }
    }

    extension AppViewModel {
        /// Creates an AppViewModel on the preview services, signed in with a ready device unless
        /// specified.
        static func preview(signedIn: Bool = true, deviceStatus: String = "ready") -> AppViewModel {
            let household = PreviewHousehold()
            let defaults = UserDefaults(suiteName: "narahem.preview") ?? .standard
            let app = AppViewModel(
                container: AppContainer(
                    accounts: PreviewAccounts(), household: household,
                    settings: AppSettings(defaults: defaults)))
            app.session.restoring = false
            if signedIn {
                app.session.signedIn = true
                app.session.account = PreviewAccounts.sam
                app.session.deviceStatus = deviceStatus
                app.session.members = household.members
                app.session.places = household.places
                app.session.audienceChoices = household.choices
                app.session.sharing = true
            }
            return app
        }
    }
#endif
