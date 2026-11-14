package com.robiem.narahem.ui

import com.robiem.narahem.data.settings.MapCamera

/** Stored phone settings shown in the UI. See [HouseholdSession.phoneSettings]. */
data class PhoneSettings(
    val mapConsent: Boolean = false,
    val addressLookup: Boolean = false,
    val mapCamera: MapCamera? = null
)
