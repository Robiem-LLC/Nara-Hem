import Foundation

/// Creates the shared session and each screen's view model from one container.
@MainActor
final class AppViewModel {
    let session: HouseholdSession
    let signIn: SignInViewModel
    let approval: DeviceApprovalViewModel
    let map: MapViewModel
    let trips: TripsViewModel
    let places: PlacesViewModel
    let settings: SettingsViewModel

    /// Creates the view models with the production container.
    convenience init() {
        self.init(container: AppContainer())
    }

    /// Creates the view models with the given container.
    init(container: AppContainer) {
        session = HouseholdSession(container: container)
        signIn = SignInViewModel(
            session: session, accounts: container.accounts, household: container.household,
            settings: container.settings, tracker: container.tracker)
        approval = DeviceApprovalViewModel(session: session, household: container.household)
        map = MapViewModel(session: session, tracker: container.tracker)
        trips = TripsViewModel(session: session, household: container.household)
        places = PlacesViewModel(
            session: session, household: container.household, tracker: container.tracker)
        settings = SettingsViewModel(
            session: session, tracker: container.tracker, accounts: container.accounts,
            household: container.household)
    }
}
