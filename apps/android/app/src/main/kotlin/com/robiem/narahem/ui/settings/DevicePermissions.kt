package com.robiem.narahem.ui.settings

import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue

/** Permission states shown on the Settings screen. */
data class DevicePermissions(
    val location: Boolean = false,
    /** Always-allow location (or an Android version that has no separate choice). */
    val backgroundLocation: Boolean = false,
    /** Whether Do Not Disturb access is granted, which Find My Phone needs to ring. */
    val findPhoneAccess: Boolean = false
)
