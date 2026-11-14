package com.robiem.narahem.ui.settings

import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.setValue

/** Values entered on the Settings screen, saved across rotation. */
@Stable
class SettingsForm(username: String = "") {
    var username by mutableStateOf(username)
    var bootstrapCode by mutableStateOf("")
    var fingerprint by mutableStateOf("")

    /** Whether the audience dialog is open. [audienceDraft] holds the choices made in it. */
    var audienceOpen by mutableStateOf(false)
    var audienceDraft by mutableStateOf<Set<String>>(emptySet())

    /** Opens the audience dialog with [current] as the starting selection. */
    fun openAudience(current: Set<String>) {
        audienceDraft = current
        audienceOpen = true
    }

    /** State saver. */
    companion object {
        val Saver = listSaver<SettingsForm, String>(
            save = { listOf(it.username, it.bootstrapCode, it.fingerprint) },
            restore = { saved ->
                SettingsForm(saved[0]).apply {
                    bootstrapCode = saved[1]
                    fingerprint = saved[2]
                }
            }
        )
    }
}
