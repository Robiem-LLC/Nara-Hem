import Foundation

/// Holds the account service, household service and settings the app runs on. Previews and tests
/// pass in fakes.
@MainActor
final class AppContainer {
    let accounts: AccountService
    let household: HouseholdService
    let settings: AppSettings
    let tracker: LocationTracker

    /// Creates a container from the given services.
    init(accounts: AccountService, household: HouseholdService, settings: AppSettings) {
        self.accounts = accounts
        self.household = household
        self.settings = settings
        tracker = LocationTracker(household: household, settings: settings)
    }

    /// Creates the production container: the server API and the encrypted household, sharing one
    /// API session.
    convenience init() {
        let api = NaraHemAPI()
        self.init(accounts: api, household: TrustedHousehold(api: api), settings: AppSettings())
    }
}
