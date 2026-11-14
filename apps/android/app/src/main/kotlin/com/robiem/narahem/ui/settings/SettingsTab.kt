package com.robiem.narahem.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.robiem.narahem.BuildConfig
import com.robiem.narahem.data.account.Account
import com.robiem.narahem.formatNaraHemBuild
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.components.AdaptiveLayout
import com.robiem.narahem.ui.components.BrandHeader
import com.robiem.narahem.ui.components.SettingsGroup
import com.robiem.narahem.ui.components.SettingsSubheading
import com.robiem.narahem.ui.components.messageColor
import com.robiem.narahem.ui.theme.NaraHemTheme

/** Settings tab connected to [SettingsViewModel]. */
@Composable
internal fun BoxScope.SettingsTab(
    state: AppState,
    form: SettingsForm,
    server: String,
    email: String,
    permissions: DevicePermissions,
    addressLookup: Boolean,
    model: SettingsViewModel,
    onAllowLocation: () -> Unit,
    onBackgroundLocation: () -> Unit,
    onFindPhoneAccess: () -> Unit,
    onChoosePhoto: () -> Unit,
    onTakePhoto: () -> Unit
) = SettingsContent(
    state, form, server, email, permissions, addressLookup, events = model,
    onAllowLocation = onAllowLocation,
    onBackgroundLocation = onBackgroundLocation,
    onFindPhoneAccess = onFindPhoneAccess,
    onChoosePhoto = onChoosePhoto,
    onTakePhoto = onTakePhoto
)

/** Settings tab UI. Stateless; actions go to [events] or the callbacks. */
@Composable
internal fun BoxScope.SettingsContent(
    state: AppState,
    form: SettingsForm,
    server: String,
    email: String,
    permissions: DevicePermissions,
    addressLookup: Boolean,
    events: SettingsEvents,
    onAllowLocation: () -> Unit,
    onBackgroundLocation: () -> Unit,
    onFindPhoneAccess: () -> Unit,
    onChoosePhoto: () -> Unit,
    onTakePhoto: () -> Unit
) {
    Column(
        Modifier.align(
            Alignment.TopCenter
        ).widthIn(
            max = AdaptiveLayout.READABLE_WIDTH_DP.dp
        ).fillMaxSize()
            .verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("Settings", style = MaterialTheme.typography.headlineMedium)
        AccountCard(state)
        if (state.syncProblem) {
            Text(
                "Cannot reach the server right now. " +
                    "Showing your last available " + "information.",
                color = MaterialTheme.colorScheme.error
            )
        }
        if (state.message.isNotBlank()) Text(state.message, color = messageColor(state.error))
        if (state.deviceStatus == "ready") {
            SettingsGroup("Profile", profileSummary(state)) {
                ProfileSection(state, form, events, onChoosePhoto, onTakePhoto)
            }
            val issues = permissionIssues(state, permissions)
            SettingsGroup(
                "Permissions",
                permissionsSummary(state, issues),
                attention = issues > 0
            ) {
                SettingsSubheading("Location sharing")
                SharingSection(state, form, addressLookup, events)
                HorizontalDivider()
                FindPhoneSection(state, permissions, events, onFindPhoneAccess)
                HorizontalDivider()
                PermissionsSection(permissions, onAllowLocation, onBackgroundLocation)
            }
        } else {
            DeviceSetupSection(state, form, server, email, events)
        }
        SettingsGroup("Account & about", "Version ${BuildConfig.VERSION_NAME}") {
            ContactRows(events, enabled = !state.busy)
            TextButton(onClick = events::signOut) { Text("Sign out") }
            Button(
                onClick = events::revokeThisPhone,
                enabled = !state.busy && state.deviceStatus == "ready"
            ) {
                Text("Revoke this phone")
            }
            BrandHeader(Modifier.padding(top = 12.dp), height = 34.dp)
            Text(
                "Version ${BuildConfig.VERSION_NAME} · Build " + "${BuildConfig.VERSION_CODE}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                "Built ${formatNaraHemBuild(
                    BuildConfig.BUILD_UTC
                )} · Commit ${BuildConfig.BUILD_COMMIT.take(10)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

/** Photo, name and sharing status, always shown above the sections. */
@Composable
private fun AccountCard(state: AppState) {
    val account = state.account!!
    val mine = state.people.firstOrNull { it.id == account.id }
    val viewers = state.audienceChoices.count { it.id in state.audience && it.id != account.id }
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        RoundProfilePhoto(mine?.photo, account.name, size = 56.dp)
        Column {
            Text(account.name, style = MaterialTheme.typography.titleMedium)
            Text(
                when {
                    state.deviceStatus != "ready" -> "Finish setting up this phone below"
                    !state.sharing -> "Location sharing is off"
                    state.audienceLoaded -> "Sharing your location · $viewers can see you"
                    else -> "Sharing your location"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary
            )
        }
    }
}

/** Closed summary for Profile: the name, and whether a photo is shared. */
private fun profileSummary(state: AppState): String {
    val account = state.account!!
    val photo = state.people.firstOrNull { it.id == account.id }?.photo
    return account.name + if (photo.isNullOrBlank()) " · no photo" else " · photo set"
}

/** How many things on this phone stop sharing or Find my phone from working. */
private fun permissionIssues(state: AppState, permissions: DevicePermissions): Int = listOf(
    !permissions.location,
    permissions.location && !permissions.backgroundLocation,
    state.findPhoneEnabled && !permissions.findPhoneAccess
).count { it }

/** Closed summary for Permissions. */
private fun permissionsSummary(state: AppState, issues: Int): String = when (issues) {
    0 -> "Sharing " + (if (state.sharing) "on" else "off") +
        " · Find my phone " + (if (state.findPhoneEnabled) "on" else "off")

    1 -> "1 needs attention"

    else -> "$issues need attention"
}

/**
 * Device setup steps for every state other than "ready": registration, email code, first device and
 * recovery.
 */
@Composable
private fun ColumnScope.DeviceSetupSection(
    state: AppState,
    form: SettingsForm,
    server: String,
    email: String,
    events: SettingsEvents
) {
    when (state.deviceStatus) {
        "register" -> {
            Text(
                "No verified phone registration is " +
                    "available. Register again to " + "begin email verification."
            )
            Button(onClick = {
                events.restartPhoneRegistration(server)
            }, enabled = !state.busy) {
                Text("Register this phone")
            }
        }

        "verify-email" -> {
            Text(
                "Confirm your email first. Check the " +
                    "confirmation message sent by " + "your server."
            )
            Button(onClick = {
                events.resendEmailConfirmation(
                    server,
                    email.ifBlank {
                        state.account!!.name
                    }
                )
            }) { Text("Resend confirmation email") }
        }

        "first-device" -> {
            Text(
                "No trusted device exists yet. " +
                    "Verify this administrator " +
                    "device using a one-time code " + "sent to your verified email."
            )
            Button(onClick = {
                events.sendBootstrapCode()
            }, enabled = !state.busy) {
                Text("Email my six-digit code")
            }
            OutlinedTextField(
                form.bootstrapCode,
                {
                    form.bootstrapCode = it
                },
                label = { Text("Six-digit code") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
            )
            Button(onClick = {
                events.finishBootstrap(form.bootstrapCode)
            }, enabled = !state.busy) {
                Text("Trust this device")
            }
        }

        "email-code" -> {
            Text(
                "A six-digit code sent to your email or phone will " +
                    "verify this phone. No " + "additional administrator " + "approval is needed."
            )
            Button(onClick = {
                events.requestPhoneCode()
            }, enabled = !state.busy) {
                Text("Send verification code")
            }
            OutlinedTextField(
                form.bootstrapCode,
                {
                    form.bootstrapCode = it
                },
                label = { Text("Six-digit code") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
            )
            Button(
                onClick = {
                    events.confirmPhoneCode(form.bootstrapCode)
                },
                enabled = !state.busy && form.bootstrapCode.length == 6
            ) {
                Text("Verify and register this phone")
            }
            TextButton(onClick = {
                events.restartPhoneRegistration(server)
            }, enabled = !state.busy) {
                Text("Start registration again")
            }
        }

        "replacement-required" -> {
            Text(
                "This account already has a " +
                    "registered phone. Ask your " +
                    "administrator to revoke it " + "before registering a replacement.",
                color = MaterialTheme.colorScheme.error
            )
            Button(onClick = {
                events.restartPhoneRegistration(server)
            }, enabled = !state.busy) {
                Text("Check again")
            }
        }

        "pending", "pairing", "verify-household" -> {
            Text("Waiting for a trusted household " + "device to approve this phone.")
            Text(
                "Compare this six-digit code with " +
                    "the code on the trusted device. " + "No fingerprint transfer."
            )
            Text(
                state.pairingCode.ifBlank {
                    "Checking…"
                },
                style = MaterialTheme.typography.headlineLarge
            )
            Text("Approval is checked automatically.", style = MaterialTheme.typography.bodySmall)
            if (state.deviceStatus != "pending") {
                Text(
                    "Older app versions cannot issue " +
                        "the signed pairing proof. " +
                        "Upgrade that trusted device " + "if necessary.",
                    style = MaterialTheme.typography.bodySmall
                )
                var advanced by remember {
                    mutableStateOf(false)
                }
                TextButton(onClick = {
                    advanced = !advanced
                }) { Text("Advanced manual recovery") }
                if (advanced) {
                    OutlinedTextField(form.fingerprint, {
                        form.fingerprint = it
                    }, label = {
                        Text("Trusted owner fingerprint")
                    })
                    Button(onClick = {
                        events.verifyHousehold(form.fingerprint)
                    }, enabled = !state.busy) {
                        Text("Verify manually")
                    }
                }
            }
        }

        else -> {
            Text(
                "Complete email verification and " +
                    "device enrollment to share your " + "location."
            )
            Button(onClick = {
                events.prepareDevice(server)
            }, enabled = !state.busy) {
                Text("Retry device enrollment")
            }
        }
    }
}

/** Find My Phone toggle and Do Not Disturb access. */
@Composable
private fun ColumnScope.FindPhoneSection(
    state: AppState,
    permissions: DevicePermissions,
    events: SettingsEvents,
    onFindPhoneAccess: () -> Unit
) {
    SettingsSubheading("Find my phone")
    Text(
        "An approved administrator can " + "request an alarm on this phone.",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant
    )
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text("Allow Find My Phone", Modifier.weight(1f))
        Switch(state.findPhoneEnabled, events::setFindPhone, enabled = !state.busy)
    }
    TextButton(onClick = onFindPhoneAccess) {
        Text(
            if (permissions.findPhoneAccess) {
                "Revoke Find my phone access"
            } else {
                "Enable Find my phone access"
            }
        )
    }
    Text(
        if (permissions.findPhoneAccess && state.findPhoneEnabled) {
            "Enabled · Tap the alarm " + "notification to stop ringing."
        } else if (permissions.findPhoneAccess) {
            "DND access granted · Allow " + "remote alarm is off."
        } else {
            "DND access missing · Open Find " + "my phone access to enable."
        },
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant
    )
}

/** Display name and profile photo. */
@Composable
private fun ColumnScope.ProfileSection(
    state: AppState,
    form: SettingsForm,
    events: SettingsEvents,
    onChoosePhoto: () -> Unit,
    onTakePhoto: () -> Unit
) {
    OutlinedTextField(
        form.username,
        {
            form.username = it
        },
        label = { Text("Display username") },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true
    )
    Button(
        onClick = {
            events.changeUsername(form.username)
        },
        enabled = !state.busy && form.username.length in 3..64
    ) {
        Text("Change username")
    }
    Text(
        "Your email remains your login. " +
            "Changing this name does not " + "reset location history or " + "device trust.",
        style = MaterialTheme.typography.bodySmall
    )
    Text(
        "Your photo is visible to approved household members.",
        style = MaterialTheme.typography.bodySmall
    )
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        OutlinedButton(
            onClick = {
                onChoosePhoto()
            },
            enabled = !state.busy,
            shape = RoundedCornerShape(50)
        ) {
            Text("Choose photo")
        }
        OutlinedButton(
            onClick = {
                onTakePhoto()
            },
            enabled = !state.busy,
            shape = RoundedCornerShape(50)
        ) {
            Text("Take photo")
        }
    }
}

/** Location sharing toggle, audience, admin browser access and address lookups. */
@Composable
private fun ColumnScope.SharingSection(
    state: AppState,
    form: SettingsForm,
    addressLookup: Boolean,
    events: SettingsEvents
) {
    Row(
        Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Column(Modifier.weight(1f)) {
            Text("Share this phone's location", style = MaterialTheme.typography.bodyLarge)
            Text(
                if (state.sharing) {
                    "On · sharing with " + "selected household " + "members"
                } else {
                    "Off · location updates paused"
                },
                style = MaterialTheme.typography.bodySmall
            )
        }
        Switch(
            checked = state.sharing,
            enabled = !state.busy,
            onCheckedChange = { enabled ->
                events.setSharing(enabled)
            }
        )
    }
    OutlinedButton(
        onClick = {
            form.openAudience(state.audience)
        },
        enabled =
            !state.busy && state.audienceLoaded &&
                !state.syncProblem &&
                state.audienceChoices.any {
                    it.id !=
                        state.account?.id
                },
        shape = RoundedCornerShape(50)
    ) {
        Text(
            "Who can see this phone? (" +
                state.audienceChoices.count {
                    it.id in
                        state.audience
                } + " other members)"
        )
    }
    if (state.audienceLoaded &&
        state.audienceChoices.none {
            it.id !=
                state.account?.id
        }
    ) {
        Text(
            "No other eligible household " +
                "members to share with. " +
                "Invite and approve a member " +
                "first. Your own approved " +
                "devices can still read this " + "phone's shared location.",
            style = MaterialTheme.typography.bodySmall
        )
    }
}

/** Location permission state with buttons to grant what's missing. */
@Composable
private fun ColumnScope.PermissionsSection(
    permissions: DevicePermissions,
    onAllowLocation: () -> Unit,
    onBackgroundLocation: () -> Unit
) {
    SettingsSubheading("Location access")
    if (permissions.location && permissions.backgroundLocation) {
        Text("Background location: Always allowed", color = MaterialTheme.colorScheme.primary)
    }
    if (!permissions.location) {
        Text(
            "Location permission needed to " + "share from this phone.",
            color = MaterialTheme.colorScheme.error
        )
        OutlinedButton(onClick = onAllowLocation) { Text("Allow location") }
    } else if (!permissions.backgroundLocation) {
        Text(
            "Enable Always location to keep " + "sharing when the screen is " + "off.",
            style = MaterialTheme.typography.bodySmall
        )
        OutlinedButton(onClick = onBackgroundLocation) {
            Text("Enable background location")
        }
    }
}

/** [SettingsEvents] that ignores every action, for previews and tests. */
internal object NoSettingsEvents : SettingsEvents {
    override fun setFindPhone(enabled: Boolean) {}
    override fun stopFindPhoneAlarm() {}
    override fun requestPhoneCode() {}
    override fun confirmPhoneCode(code: String) {}
    override fun restartPhoneRegistration(server: String) {}
    override fun prepareDevice(server: String) {}
    override fun revokeThisPhone() {}
    override fun changeUsername(username: String) {}
    override fun sendBootstrapCode() {}
    override fun finishBootstrap(code: String) {}
    override fun verifyHousehold(fingerprint: String) {}
    override fun setSharing(enabled: Boolean) {}
    override fun setOwnerBrowserAccess(enabled: Boolean) {}
    override fun setAddressLookup(enabled: Boolean) {}
    override fun resendEmailConfirmation(server: String, email: String) {}
    override fun signOut() {}
}

/** Preview of Settings for a ready phone. */
@Preview
@Composable
private fun SettingsPreview() {
    NaraHemTheme {
        Box {
            SettingsContent(
                state = AppState(
                    restoring = false,
                    account = Account("Sam", verified = true, household = "Home", id = "1"),
                    deviceStatus = "ready"
                ),
                form = SettingsForm("Sam"),
                server = "https://family.example",
                email = "sam@example.invalid",
                permissions = DevicePermissions(location = true),
                addressLookup = false,
                events = NoSettingsEvents,
                onAllowLocation = {},
                onBackgroundLocation = {},
                onFindPhoneAccess = {},
                onChoosePhoto = {},
                onTakePhoto = {}
            )
        }
    }
}
