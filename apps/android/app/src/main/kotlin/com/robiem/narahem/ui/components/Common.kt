package com.robiem.narahem.ui.components

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * Returns the text colour for a form message: the error colour for errors, otherwise the primary
 * colour.
 */
@Composable
internal fun messageColor(error: Boolean): Color =
    if (error) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary
