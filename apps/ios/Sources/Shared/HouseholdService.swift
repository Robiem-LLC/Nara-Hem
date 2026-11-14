import Foundation

/// Access to the encrypted household: this device's setup state, members and places, sharing, trips
/// and Find My Phone. Implemented by TrustedHousehold.
@MainActor
protocol HouseholdService: AnyObject {
    var identity: TrustedIdentity? { get }
    var places: [SavedPlace] { get }
    var audience: Set<String> { get }
    var choices: [AudienceChoice] { get }
    var ownerViewerId: String? { get }
    var sharing: Bool { get }
    var findPhoneEnabled: Bool { get set }

    /// Loads the stored device identity for this account and server. Returns false if there is
    /// none.
    func restore(account: NaraHemAccount, server: String) -> Bool

    /// Returns this device's setup state, such as "register", "email-code", "pairing" or "ready".
    func status(account: NaraHemAccount) async throws -> String

    /// Returns this device's six-digit pairing code.
    func ownCode() async throws -> String

    /// Generates keys and registers this device.
    func enroll(account: NaraHemAccount, server: String) async throws

    /// Requests the email with this phone's approval code.
    func requestPhoneCode() async throws

    /// Submits the approval code.
    func verifyPhoneCode(_ code: String) async throws

    /// Cancels an unfinished registration.
    func discardPendingPhone() async

    /// Permanently revokes this phone.
    func revokeThisPhone() async throws

    /// Requests the first-device email code for a new household.
    func sendBootstrapCode() async throws

    /// Registers the household's first device with the emailed code.
    func bootstrap(code: String) async throws

    /// Fetches every member's latest location and the saved places.
    func snapshot() async throws -> HouseholdSnapshot

    /// Reloads this phone's sharing audience and returns the names of members who just joined.
    @discardableResult func refreshAudience() async throws -> [String]

    /// Enables or disables location sharing.
    func setSharing(_ enabled: Bool) async throws

    /// Sets which accounts can see this phone's location.
    func setAudience(_ selected: Set<String>) async throws

    /// Deletes a saved place for the whole household.
    func deletePlace(_ place: SavedPlace) async throws

    /// Publishes this member's display name and profile photo.
    func savePhoto(jpeg: Data, name: String) async throws

    /// Fetches the full route of one trip.
    func tripRoute(_ trip: HouseholdTrip) async throws -> [HouseholdTripPoint]

    /// Publishes one location immediately.
    func publishLocation(_ fix: LocalLocation) async throws

    /// Publishes several locations in one request.
    func publishLocations(_ fixes: [LocalLocation]) async throws

    /// Publishes a completed trip summary.
    func publishTrip(_ trip: HouseholdTrip) async throws

    /// Enables or disables Find My Phone.
    func setFindPhone(_ enabled: Bool) async throws

    /// Returns the next verified Find My Phone command as (id, action, expiry), or nil.
    func findCommand() async throws -> (String, String, Int)?

    /// Reports a Find My Phone command's status.
    func reportFind(_ id: String, state: String, reason: String) async

    /// Uploads this phone's APNs token.
    func subscribePush(token: String, environment: String) async throws

    /// Removes this phone's APNs token from the server.
    func unsubscribePush() async throws

    /// Reports this phone's permission state to the server.
    func reportDevicePermissions(
        foreground: Bool, background: Bool, alarm: Bool, notifications: Bool, sharing: Bool
    ) async throws

    /// Creates or updates a saved place.
    func savePlace(
        name: String, lat: Double, lon: Double, radius: Double, existing: SavedPlace?,
        alerts: Wire.Object
    ) async throws

    /// Fetches a member's trip summaries for the last few days.
    func trips(
        accountId: String, days: Int
    ) async throws -> ([HouseholdTrip], [HouseholdTripPoint], Bool?, Bool?)
}

/// TrustedHousehold provides the household operations.
extension TrustedHousehold: HouseholdService {}
