package com.robiem.narahem.ui.components

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

private val destinations = listOf(
    "map" to "Map",
    "trips" to "Trips",
    "places" to "Places",
    "settings" to "Settings"
)

/** Tab navigation: a bottom bar in portrait, a side rail when [rail] is true. */
@Composable
internal fun AdaptiveNavigation(selected: String, rail: Boolean, onSelect: (String) -> Unit) {
    /** Draws the icon for one tab. */
    @Composable
    fun icon(index: Int, key: String) = NaraHemTabIcon(
        index,
        if (selected == key) {
            MaterialTheme.colorScheme.primary
        } else {
            MaterialTheme.colorScheme.onSurfaceVariant
        }
    )
    if (rail) {
        NavigationRail(
            containerColor = MaterialTheme.colorScheme.background,
            header = { Spacer(Modifier.height(8.dp)) }
        ) {
            destinations.forEachIndexed { index, (key, label) ->
                NavigationRailItem(
                    selected = selected == key,
                    onClick = { onSelect(key) },
                    icon = { icon(index, key) },
                    label = { Text(label) }
                )
            }
        }
    } else {
        NavigationBar(
            containerColor = MaterialTheme.colorScheme.background,
            tonalElevation = 0.dp
        ) {
            destinations.forEachIndexed { index, (key, label) ->
                NavigationBarItem(
                    selected = selected == key,
                    onClick = { onSelect(key) },
                    icon = { icon(index, key) },
                    label = { Text(label) }
                )
            }
        }
    }
}
