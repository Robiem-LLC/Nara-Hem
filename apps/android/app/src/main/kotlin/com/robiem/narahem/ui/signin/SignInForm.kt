package com.robiem.narahem.ui.signin

import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.setValue

/** Text entered on the signed-out screens, saved across rotation. */
@Stable
class SignInForm(server: String = "", confirmation: String = "") {
    var server by mutableStateOf(server)
    var email by mutableStateOf("")
    var password by mutableStateOf("")
    var passwordConfirmation by mutableStateOf("")
    var showPassword by mutableStateOf(false)

    /** True while asking for the email; the password is asked on the next step. */
    var firstStep by mutableStateOf(true)
    var chosenUsername by mutableStateOf("")

    /** The invitation link or token from the enrollment email. */
    var confirmation by mutableStateOf(confirmation)
    var requestName by mutableStateOf("")
    var relationship by mutableStateOf("")

    /** Returns what still stops registering, such as a short password, or null when ready. */
    fun registrationProblem(): String? = when {
        server.isBlank() -> "Enter the server address at the top."
        email.isBlank() -> "Enter the email or phone number you were invited with, at the top."
        chosenUsername.trim().length < 3 -> "Enter your name, at least 3 characters."
        password.length < 15 -> "Password needs 15+ characters (${password.length} so far)."
        password != passwordConfirmation -> "The two passwords don't match."
        else -> null
    }

    /** State saver. */
    companion object {
        /** Passwords are never written to the saved screen state. */
        val Saver = listSaver<SignInForm, Any>(
            save = {
                listOf(
                    it.server,
                    it.email,
                    it.firstStep,
                    it.chosenUsername,
                    it.confirmation,
                    it.requestName,
                    it.relationship
                )
            },
            restore = { saved ->
                SignInForm(saved[0] as String, saved[4] as String).apply {
                    email = saved[1] as String
                    firstStep = saved[2] as Boolean
                    chosenUsername = saved[3] as String
                    requestName = saved[5] as String
                    relationship = saved[6] as String
                }
            }
        )
    }
}
