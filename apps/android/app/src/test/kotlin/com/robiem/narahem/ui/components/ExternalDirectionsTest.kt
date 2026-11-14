package com.robiem.narahem.ui.components

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ExternalDirectionsTest {
    @Test fun formatsCoordinatesWithoutUserNamesOrLocaleAmbiguity() {
        assertEquals(
            "40.1234567,-74.1234567",
            ExternalDirections.coordinates(40.1234567, -74.1234567)
        )
        assertEquals("0.0000000,0.0000000", ExternalDirections.coordinates(0.0, 0.0))
        assertEquals("90.0000000,-180.0000000", ExternalDirections.coordinates(90.0, -180.0))
    }

    @Test fun rejectsUnknownOrInvalidDestinations() {
        assertNull(ExternalDirections.coordinates(Double.NaN, -74.0))
        assertNull(ExternalDirections.coordinates(Double.POSITIVE_INFINITY, 0.0))
        assertNull(ExternalDirections.coordinates(-91.0, 0.0))
        assertNull(ExternalDirections.coordinates(0.0, 180.1))
    }
}
