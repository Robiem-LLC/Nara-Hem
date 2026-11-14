package com.robiem.narahem.data.household

/** A saved place: a named circle and the members who get arrival or departure alerts for it. */
data class HouseholdPlace(
    val id: String,
    val name: String,
    val latitude: Double,
    val longitude: Double,
    val radius: Double,
    val recordId: String? = null,
    val alerts: Map<String, PlaceAlert> = emptyMap(),
    val extraData: String = "{}"
)
