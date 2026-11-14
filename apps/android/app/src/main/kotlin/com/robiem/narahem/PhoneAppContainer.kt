package com.robiem.narahem

import android.content.Context
import com.robiem.narahem.data.account.ServerAccountRepository
import com.robiem.narahem.data.household.NativeHouseholdRepository
import com.robiem.narahem.data.location.PhoneAddressLookup
import com.robiem.narahem.data.location.PhoneLocationRepository
import com.robiem.narahem.data.settings.PhoneAppSettings
import com.robiem.narahem.tracking.ServiceTrackingController

/**
 * Production [AppContainer]: connects to the household server, the phone's location services,
 * SharedPreferences and the Keystore-backed device identity.
 */
class PhoneAppContainer(context: Context) : AppContainer {
    private val appContext = context.applicationContext
    override val accounts = ServerAccountRepository(context = appContext)
    override val locations = PhoneLocationRepository(appContext)
    override val household = NativeHouseholdRepository(appContext, accounts)
    override val settings = PhoneAppSettings(appContext)
    override val addresses = PhoneAddressLookup(appContext)
    override val tracking = ServiceTrackingController(appContext)
}
