package com.robiem.narahem.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.robiem.narahem.data.account.serverOrigin
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.settings.SettingsForm

/** Asks whether to switch to the server named in an invitation link. */
@Composable
internal fun InviteServerDialog(
    invite: String,
    current: String,
    onSwitch: () -> Unit,
    onKeep: () -> Unit
) {
    val host = { url: String ->
        runCatching { serverOrigin(url).host }.getOrDefault(url)
    }
    AlertDialog(
        onDismissRequest = onKeep,
        title = { Text("Different server in this link") },
        text = {
            Text(
                "This invitation link points to ${host(invite)}, but this app is set up for " +
                    "${host(current)}. Only switch if your household administrator gave you " +
                    "the new address. A link from anyone else could be an attempt to collect " +
                    "your password."
            )
        },
        confirmButton = {
            TextButton(onClick = onSwitch) { Text("Switch to ${host(invite)}") }
        },
        dismissButton = {
            TextButton(onClick = onKeep) { Text("Keep ${host(current)}") }
        }
    )
}

/** Asks for consent before sharing location and loading map tiles. */
@Composable
internal fun LocationConsentDialog(onAccept: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Share your location with your household?") },
        text = {
            Text(
                "Nära Hem sends your location to your household's server. Members you share " +
                    "with can see it. You can pause sharing in Settings. The map provider " +
                    "receives the region you view."
            )
        },
        confirmButton = { TextButton(onClick = onAccept) { Text("Continue") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Not now") } }
    )
}

/** Lets the user choose which members can see this phone's location. */
@Composable
internal fun AudienceDialog(state: AppState, form: SettingsForm, onSave: (Set<String>) -> Unit) {
    val eligible = state.audienceChoices.filter { it.id != state.account!!.id }
    val selectedOthers = form.audienceDraft - state.account!!.id
    val savedOthers = state.audience - state.account!!.id
    AlertDialog(
        onDismissRequest = { form.audienceOpen = false },
        title = { Text("Who can see this phone?") },
        text = {
            Column(
                Modifier.heightIn(max = 360.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Text(
                    "Choose household members who can see NEW locations " +
                        "shared by this phone. Other devices you own can " +
                        "still have separate sharing settings.",
                    style = MaterialTheme.typography.bodySmall
                )
                if (eligible.isEmpty()) {
                    Text(
                        if (state.syncProblem || !state.audienceLoaded) {
                            "Cannot load household members. Try again when " + "connected."
                        } else {
                            "No other household members to select. Your own " +
                                "approved devices can still see your location."
                        }
                    )
                }
                eligible.forEach { person ->
                    Row(
                        Modifier.fillMaxWidth().clickable {
                            form.audienceDraft =
                                if (person.id in form.audienceDraft) {
                                    form.audienceDraft - person.id
                                } else {
                                    form.audienceDraft + person.id
                                }
                        },
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Checkbox(
                            checked = person.id in form.audienceDraft,
                            onCheckedChange = { checked ->
                                form.audienceDraft =
                                    if (checked) {
                                        form.audienceDraft + person.id
                                    } else {
                                        form.audienceDraft -
                                            person.id
                                    }
                            }
                        )
                        Text(person.name)
                    }
                }
                Text(
                    "Removing someone blocks further downloads from this " +
                        "server, but cannot erase locations they already saved.",
                    style = MaterialTheme.typography.bodySmall
                )
            }
        },
        confirmButton = {
            Button(
                enabled =
                    eligible.isNotEmpty() && !state.syncProblem &&
                        !state.busy && selectedOthers != savedOthers,
                onClick = {
                    onSave(selectedOthers)
                    form.audienceOpen = false
                }
            ) { Text("Save sharing choices") }
        },
        dismissButton = {
            TextButton(onClick = { form.audienceOpen = false }) { Text("Cancel") }
        }
    )
}
