package com.robiem.narahem.data.household

/** Whether a member is alerted when someone arrives at or leaves a place. */
data class PlaceAlert(val arrival: Boolean = false, val departure: Boolean = false)
