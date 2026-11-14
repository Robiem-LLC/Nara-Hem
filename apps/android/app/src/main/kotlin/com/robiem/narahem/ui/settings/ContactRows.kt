package com.robiem.narahem.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.robiem.narahem.data.account.ContactDetails

/**
 * The account's email address and phone number, each with a button to add or change it. The phone
 * is Unavailable, with no button, while the server can't text.
 */
@Composable
internal fun ContactRows(events: SettingsEvents, enabled: Boolean) {
    var details by remember { mutableStateOf<ContactDetails?>(null) }
    var loads by remember { mutableIntStateOf(0) }
    var changing by rememberSaveable { mutableStateOf<String?>(null) }
    LaunchedEffect(loads) { details = runCatching { events.contactDetails() }.getOrNull() }
    val email = details?.email
    val phone = details?.phone
    ContactRow("Email", email ?: "None", if (email == null) "Add" else "Change", enabled) {
        changing = "email"
    }
    ContactRow(
        "Phone",
        phone ?: if (details?.textingOn == true) "None" else "Unavailable",
        if (phone == null) "Add" else "Change",
        enabled && details?.textingOn == true
    ) { changing = "phone" }
    changing?.let { kind ->
        ContactChangeDialog(
            events,
            phone = kind == "phone",
            adding = (if (kind == "phone") phone else email) == null
        ) {
            changing = null
            loads++
        }
    }
}

/** One labelled contact value with its button. */
@Composable
private fun ContactRow(
    label: String,
    value: String,
    action: String,
    enabled: Boolean,
    onClick: () -> Unit
) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.labelLarge)
            Text(
                value,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        OutlinedButton(onClick = onClick, enabled = enabled) { Text(action) }
    }
}
