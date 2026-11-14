package com.robiem.narahem.tracking

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TrackingCadenceTest {
    @Test fun firstFixIsImmediateAndDuplicateProviderCallbacksAreGated() {
        val gate = TrackingCadence()
        assertTrue(gate.accept(1000))
        gate.schedule(1000, 120000)
        assertFalse(gate.accept(1001))
        assertFalse(gate.accept(120999))
        assertTrue(gate.accept(121000))
    }

    @Test fun realDepartureOverridesFourMinuteStationaryGateWithoutFlooding() {
        val gate = TrackingCadence()
        assertTrue(gate.accept(1000))
        gate.schedule(1000, 240000)
        assertFalse(gate.accept(1200, true))
        assertTrue(gate.accept(6000, true))
        gate.schedule(6000, 4000)
        assertFalse(gate.accept(7000, true))
        assertTrue(gate.accept(11000, true))
    }

    @Test fun elapsedTimeAfterSleepIsNotResetAndResumeStartsImmediately() {
        val gate = TrackingCadence()
        gate.schedule(1000, 90000)
        assertTrue(gate.accept(600000))
        assertTrue(TrackingCadence().accept(600000))
        gate.schedule(600000, 15000)
        assertTrue(gate.accept(615000))
    }
}
