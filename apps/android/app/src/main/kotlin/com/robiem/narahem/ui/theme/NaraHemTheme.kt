package com.robiem.narahem.ui.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** Material roles filled from [NaraHemColors], so components pick up the theme on their own. */
private val colors = darkColorScheme(
    primary = NaraHemColors.Accent,
    onPrimary = NaraHemColors.OnAccent,
    primaryContainer = NaraHemColors.AccentContainer,
    onPrimaryContainer = NaraHemColors.Accent,
    secondary = NaraHemColors.AccentText,
    onSecondary = NaraHemColors.OnAccent,
    secondaryContainer = NaraHemColors.AccentContainer,
    onSecondaryContainer = NaraHemColors.Accent,
    tertiary = NaraHemColors.TextLabel,
    background = NaraHemColors.Background,
    onBackground = NaraHemColors.Text,
    surface = NaraHemColors.Background,
    onSurface = NaraHemColors.Text,
    surfaceVariant = NaraHemColors.Panel,
    onSurfaceVariant = NaraHemColors.TextSubdued,
    surfaceContainerLowest = NaraHemColors.PanelSunken,
    surfaceContainerLow = NaraHemColors.Panel,
    surfaceContainer = NaraHemColors.Panel,
    surfaceContainerHigh = NaraHemColors.PanelRaised,
    surfaceContainerHighest = NaraHemColors.PanelRaised,
    outline = NaraHemColors.LineStrong,
    outlineVariant = NaraHemColors.Line,
    error = NaraHemColors.DangerText,
    errorContainer = NaraHemColors.Danger
)

/** Paints the screen background: the deep blue glow. */
fun Modifier.appBackground() = background(NaraHemColors.Glow)

/** A thin border in the bottom bar's blue around a card (Material's 12dp card corners). */
fun Modifier.cardBorder() = border(1.dp, NaraHemColors.Background, RoundedCornerShape(12.dp))

/** Applies the app's theme. */
@Composable
fun NaraHemTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = colors, content = content)
}
