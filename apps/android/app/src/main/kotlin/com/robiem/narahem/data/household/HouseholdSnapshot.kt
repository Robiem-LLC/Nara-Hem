package com.robiem.narahem.data.household

/** Members and saved places from one refresh. */
data class HouseholdSnapshot(val people: List<HouseholdPerson>, val places: List<HouseholdPlace>)
