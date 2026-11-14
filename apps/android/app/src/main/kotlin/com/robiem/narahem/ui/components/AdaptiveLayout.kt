package com.robiem.narahem.ui.components

/**
 * Layout decisions based on the window size in dp, so rotated phones, tablets and split-screen
 * windows all work.
 */
internal object AdaptiveLayout {
    /** Maximum content width for text-heavy screens. */
    const val READABLE_WIDTH_DP = 720

    /** Returns true for windows wide enough to show the map and a side panel together. */
    fun landscape(widthDp: Int, heightDp: Int): Boolean = widthDp > heightDp && widthDp >= 600

    /** Returns the side panel width for a landscape window. */
    fun sidePanelWidthDp(widthDp: Int): Int = (widthDp * 0.4f).toInt().coerceIn(280, 360)
}
