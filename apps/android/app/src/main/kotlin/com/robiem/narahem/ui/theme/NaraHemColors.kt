package com.robiem.narahem.ui.theme

import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

/**
 * Theme: every colour in the Android app. Change a value here and it changes everywhere. Same
 * names and order as the web (style.css) and iOS (Theme.swift) theme files.
 */
object NaraHemColors {
    val Accent = Color(0xFFFFC35A)
    val AccentText = Color(0xFFFFD27A)
    val OnAccent = Color(0xFF2A1A05)
    val Text = Color(0xFFF6EFE3)
    val TextLabel = Color(0xFFC4CEE8)
    val TextSubdued = Color(0xFFAEBBDD)
    val Background = Color(0xFF06143A)
    val GlowTop = Color(0xFF143C95)
    val GlowMiddle = Color(0xFF0A2160)

    /** The lower background: a step lighter than the bottom bar ([Background]) all the way down. */
    val GlowLow = Color(0xFF0B2160)
    val GlowBottom = Color(0xFF0A1C52)
    val Panel = Color(0xFF0C1D4D)
    val PanelRaised = Color(0xFF0F2459)
    val PanelSunken = Color(0xFF081639)
    val Chip = Color(0xFF1A3170)
    val ChipHover = Color(0xFF24407F)
    val Line = Color(0xFF1E3A7A)
    val LineStrong = Color(0xFF2D4C8F)
    val White = Color(0xFFFFFFFF)
    val Place = Color(0xFFFFC35A)
    val Route = Color(0xFFFFC35A)
    val RouteCasing = Color(0xFF081639)
    val TripStart = Color(0xFF22C55E)
    val TripEnd = Color(0xFFEF4444)
    val Ok = Color(0xFF247D41)
    val AccentContainer = Color(0xFF3D2C0E)
    val Warn = Color(0xFFFFA726)
    val Danger = Color(0xFFDB5359)
    val DangerText = Color(0xFFFFB8BA)

    /** The glow behind every screen, lighter at the top. */
    val Glow = Brush.verticalGradient(
        0f to GlowTop,
        0.35f to GlowMiddle,
        0.75f to GlowLow,
        1f to GlowBottom
    )
}
