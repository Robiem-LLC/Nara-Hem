package com.robiem.narahem.ui.map

import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.household.HouseholdPlace
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AvatarFanTest {
    private fun person(id: String, lat: Double, lon: Double = -74.0) =
        HouseholdPerson(id, id, lat, lon, 10.0)

    @Test fun nearbyMembersSitSideBySideAndFarOnesStay() {
        // About 11 m apart: one pair, centered on the shared spot. 1 km away: unmoved.
        val fan = AvatarFan.layout(
            listOf(person("b", 40.0001), person("a", 40.0), person("c", 40.01)),
            emptyList(),
            92
        )
        assertEquals(AvatarFan.Offset(-42, 0, 2), fan["a"])
        assertEquals(AvatarFan.Offset(42, 0, 2), fan["b"])
        assertTrue("c" !in fan)
    }

    @Test fun sameSavedPlaceGroupsWiderAndBigGroupsGetASecondRow() {
        val home = HouseholdPlace("h", "Home", 40.0, -74.0, 150.0)
        val apart = listOf(person("a", 40.0), person("b", 40.0007)) // ~78 m apart, both at Home
        assertEquals(2, AvatarFan.layout(apart, listOf(home), 46)["a"]?.groupSize)
        assertTrue(AvatarFan.layout(apart, emptyList(), 46).isEmpty())
        val five = (1..5).map { person("m$it", 40.0 + it * 0.00001) }
        val rows = AvatarFan.layout(five, emptyList(), 46)
        assertEquals(4, rows.values.count { it.dy == 0 })
        assertEquals(AvatarFan.Offset(0, -36, 5), rows["m5"])
    }
}
