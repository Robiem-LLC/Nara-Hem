package com.robiem.narahem.ui.components

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AdaptiveLayoutTest {
    @Test fun landscapeWindowsUseTheSideLayout() {
        assertTrue(AdaptiveLayout.landscape(1280, 720)) // car screen
        assertTrue(AdaptiveLayout.landscape(1024, 552)) // car screen under a status bar
        assertTrue(AdaptiveLayout.landscape(800, 360)) // phone turned sideways
        assertFalse(AdaptiveLayout.landscape(411, 891)) // phone upright
        assertFalse(AdaptiveLayout.landscape(560, 400)) // small split-screen window
    }

    @Test fun panelWidthFollowsTheWindow() {
        assertEquals(280, AdaptiveLayout.sidePanelWidthDp(640))
        assertEquals(320, AdaptiveLayout.sidePanelWidthDp(800))
        assertEquals(360, AdaptiveLayout.sidePanelWidthDp(1280))
    }
}
