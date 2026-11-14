package com.robiem.narahem.ui.map

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MarkerMotionTest {
    private val home = 40.0 to -74.0
    private val down = 40.001 to -74.0 // about 111 m north

    @Test fun firstFixAppearsInPlace() {
        val motion = MarkerMotion()
        assertEquals(home, motion.update("a", null, home, 1_000, 0))
        assertFalse(motion.moving)
    }

    @Test fun newerFixGlidesOverMostOfTheGapAndStopsAtTheFix() {
        val motion = MarkerMotion()
        motion.update("a", null, home, 0, 0)
        assertEquals(home, motion.update("a", home, down, 15_000, 1_000))
        assertTrue(motion.moving)
        val halfway = motion.positionAt("a", 1_000 + 6_000)!!
        assertEquals(40.0005, halfway.first, 1e-9)
        assertEquals(down, motion.positionAt("a", 1_000 + 12_000))
        assertFalse(motion.moving)
        assertNull(motion.positionAt("a", 20_000))
    }

    @Test fun olderOrRepeatedFixesDoNotMoveTheMarker() {
        val motion = MarkerMotion()
        motion.update("a", null, home, 10_000, 0)
        assertEquals(home, motion.update("a", home, down, 10_000, 1_000))
        assertEquals(home, motion.update("a", home, down, 5_000, 1_000))
        assertFalse(motion.moving)
    }

    @Test fun implausibleChangesJump() {
        val far = 41.0 to -74.0
        val motion = MarkerMotion()
        motion.update("a", null, home, 0, 0)
        assertEquals(far, motion.update("a", home, far, 15_000, 0))
        motion.update("b", null, home, 0, 0)
        assertEquals(down, motion.update("b", home, down, 300_000, 0))
        motion.update("c", null, home, 0, 0)
        assertEquals(40.00001 to -74.0, motion.update("c", home, 40.00001 to -74.0, 15_000, 0))
        assertFalse(motion.moving)
    }

    @Test fun forgottenMarkersStartAgain() {
        val motion = MarkerMotion()
        motion.update("a", null, home, 0, 0)
        motion.update("a", home, down, 15_000, 0)
        motion.forget("a")
        assertFalse(motion.moving)
        assertEquals(down, motion.update("a", home, down, 30_000, 0))
    }

    @Test fun durationsFollowTheIphone() {
        assertEquals(500, MarkerMotion.durationMillis(0.2))
        assertEquals(12_000, MarkerMotion.durationMillis(15.0))
        assertEquals(12_000, MarkerMotion.durationMillis(60.0))
        assertEquals(0, MarkerMotion.durationMillis(0.0))
        assertEquals(111.2, MarkerMotion.distanceMeters(home, down), 0.5)
    }
}
