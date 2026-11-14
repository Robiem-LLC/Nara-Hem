package com.robiem.narahem.data.trips

import com.robiem.narahem.data.household.HouseholdTrip

/** A member's trips and GPS points for a date range. */
data class TripHistory(
    val trips: List<HouseholdTrip>,
    val points: List<TripPoint>,
    val hasEarlier: Boolean
)
