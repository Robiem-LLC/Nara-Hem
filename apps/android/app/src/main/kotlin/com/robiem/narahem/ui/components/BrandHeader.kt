package com.robiem.narahem.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.robiem.narahem.R

/** The NÄRA HEM wordmark with the tagline under it, used on sign-in, loading and Settings. */
@Composable
internal fun BrandHeader(
    modifier: Modifier = Modifier,
    height: Dp = 64.dp,
    centered: Boolean = false
) {
    Column(
        modifier,
        horizontalAlignment = if (centered) Alignment.CenterHorizontally else Alignment.Start,
        verticalArrangement = Arrangement.spacedBy(height / 6)
    ) {
        Image(
            painterResource(R.drawable.nara_hem_wordmark),
            contentDescription = "Nära Hem",
            modifier = Modifier.height(height)
        )
        Text(
            "YOUR HOME. YOUR DATA.",
            color = MaterialTheme.colorScheme.primary,
            fontWeight = FontWeight.SemiBold,
            fontSize = (height.value / 5).coerceIn(10f, 14f).sp,
            letterSpacing = 3.sp
        )
    }
}
