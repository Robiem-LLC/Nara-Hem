package com.robiem.narahem

import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.robiem.narahem.data.account.AccountRepository
import com.robiem.narahem.data.household.HouseholdRepository
import com.robiem.narahem.data.location.AddressLookup
import com.robiem.narahem.data.location.LocationRepository
import com.robiem.narahem.data.settings.AppSettings
import com.robiem.narahem.tracking.TrackingController
import com.robiem.narahem.ui.AppViewModel
import com.robiem.narahem.ui.HouseholdSession
import com.robiem.narahem.ui.map.MapViewModel
import com.robiem.narahem.ui.places.PlacesViewModel
import com.robiem.narahem.ui.settings.SettingsViewModel
import com.robiem.narahem.ui.signin.SignInViewModel
import com.robiem.narahem.ui.trips.TripsViewModel

/**
 * Creates the repositories and view model factories the app runs on. MainActivity uses
 * [PhoneAppContainer]; UI tests supply a container of fakes through MainActivity.testContainer.
 */
interface AppContainer {
    /** Signs in and out of the household server. */
    val accounts: AccountRepository

    /** Reads this phone's location. */
    val locations: LocationRepository

    /** Encrypted household data. Null in UI tests that run without it. */
    val household: HouseholdRepository?

    /** Settings stored on this phone. */
    val settings: AppSettings

    /** Looks up street addresses. */
    val addresses: AddressLookup

    /** Starts and stops background location sharing. */
    val tracking: TrackingController

    /** Creates the [AppViewModel], which owns the shared [HouseholdSession]. */
    val appViewModelFactory: ViewModelProvider.Factory
        get() = viewModelFactory {
            initializer { AppViewModel(accounts, household, settings, tracking) }
        }

    /** Creates a factory for each screen's view model, all bound to the given [session]. */
    fun screenViewModelFactory(session: HouseholdSession): ViewModelProvider.Factory =
        viewModelFactory {
            initializer { SignInViewModel(session, accounts) }
            initializer { MapViewModel(session, locations, household, addresses) }
            initializer { TripsViewModel(session, household, addresses) }
            initializer { PlacesViewModel(session, household, addresses) }
            initializer { SettingsViewModel(session, accounts, household, tracking) }
        }
}
