package com.robiem.narahem.ui.components

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * A heading inside a Settings section (Location sharing, Find my phone…): small amber capitals,
 * clearly below the section's own title.
 */
@Composable
internal fun SettingsSubheading(text: String) {
    Text(
        text.uppercase(),
        Modifier.padding(top = 6.dp),
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.Bold,
        letterSpacing = 1.2.sp,
        color = MaterialTheme.colorScheme.primary
    )
}
