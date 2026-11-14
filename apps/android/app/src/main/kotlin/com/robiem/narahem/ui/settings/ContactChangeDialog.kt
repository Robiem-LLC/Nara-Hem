package com.robiem.narahem.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

/**
 * Adds or changes the account's email address ([phone] false) or phone number ([phone] true) in two
 * steps: the new one and the password, then the six-digit code sent to it. Nothing changes until
 * the code is entered, and the other one is left as it is.
 */
@Composable
internal fun ContactChangeDialog(
    events: SettingsEvents,
    phone: Boolean,
    adding: Boolean,
    onClose: () -> Unit
) {
    val what = if (phone) "phone number" else "email address"
    var value by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var code by rememberSaveable { mutableStateOf("") }
    var sentTo by rememberSaveable { mutableStateOf<String?>(null) }
    var problem by rememberSaveable { mutableStateOf("") }
    var busy by rememberSaveable { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val run = { task: suspend () -> Unit ->
        busy = true
        problem = ""
        scope.launch {
            try {
                task()
            } catch (error: Exception) {
                problem = error.message ?: "Something went wrong. Try again."
            } finally {
                busy = false
            }
        }
    }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text((if (adding) "Add " else "Change ") + what) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (sentTo == null) {
                    Text("Enter your new $what and your password. We'll send it a code.")
                    OutlinedTextField(
                        value,
                        { value = it },
                        label = { Text("New $what") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(
                            keyboardType = if (phone) KeyboardType.Phone else KeyboardType.Email
                        ),
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        password,
                        { password = it },
                        label = { Text("Password") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth()
                    )
                } else {
                    Text("Enter the six-digit code sent to $sentTo. It expires in 10 minutes.")
                    OutlinedTextField(
                        code,
                        { code = it.filter(Char::isDigit).take(6) },
                        label = { Text("Six-digit code") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                if (problem.isNotBlank()) Text(problem, color = MaterialTheme.colorScheme.error)
            }
        },
        confirmButton = {
            if (sentTo == null) {
                TextButton(
                    onClick = {
                        run { sentTo = events.requestContactChange(value.trim(), password, phone) }
                    },
                    enabled = !busy && value.isNotBlank() && password.isNotBlank()
                ) { Text("Send code") }
            } else {
                TextButton(
                    onClick = {
                        run {
                            events.confirmContactChange(code)
                            onClose()
                        }
                    },
                    enabled = !busy && code.length == 6
                ) { Text("Confirm") }
            }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Cancel") } }
    )
}
