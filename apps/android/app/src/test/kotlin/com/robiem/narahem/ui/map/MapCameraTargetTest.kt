package com.robiem.narahem.ui.map

import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.location.LocalFix
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MapCameraTargetTest {
    private val other = HouseholdPerson("other", "Other", 9.0, 8.0)
    private val me = HouseholdPerson("me", "Me", 1.0, 2.0)

    @Test fun startupWaitsForThisPhoneInsteadOfCenteringOnSomeoneElse() {
        assertNull(mapCameraTarget(null, listOf(other), "me", null))
        assertEquals(1.0 to 2.0, mapCameraTarget(null, listOf(other, me), "me", null))
        assertEquals(
            3.0 to 4.0,
            mapCameraTarget(LocalFix(3.0, 4.0, 10f), listOf(other, me), "me", null)
        )
    }

    @Test fun explicitSelectionCanFocusAnotherMemberAndSelfUsesLocalLocation() {
        val fix = LocalFix(3.0, 4.0, 10f)
        assertEquals(9.0 to 8.0, mapCameraTarget(fix, listOf(other, me), "me", "other"))
        assertEquals(3.0 to 4.0, mapCameraTarget(fix, listOf(other, me), "me", "me"))
        assertNull(mapCameraTarget(fix, listOf(other, me), "me", "missing"))
    }
}
