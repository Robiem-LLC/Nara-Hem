package com.robiem.narahem.ui.signin

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.components.BrandHeader
import com.robiem.narahem.ui.components.messageColor
import com.robiem.narahem.ui.theme.NaraHemTheme

/** Signed-out screen, connected to [SignInViewModel]. */
@Composable
internal fun SignInScreen(state: AppState, form: SignInForm, model: SignInViewModel) {
    SignInContent(
        state = state,
        form = form,
        onRetryRememberedSignIn = { model.retryRememberedSession(form.server) },
        onResendInvitation = { model.findInvitation(form.server, form.email) },
        onShow = model::onboarding,
        onFinishEnrollment = {
            model.completeInvitation(
                form.server,
                form.confirmation,
                form.chosenUsername,
                form.password
            )
        },
        onRegister = {
            model.register(form.server, form.email, form.chosenUsername, form.password)
        },
        onRequestInvitation = {
            model.requestInvitation(form.server, form.email, form.requestName, form.relationship)
        },
        onSignIn = { model.signIn(form.server, form.email, form.password) }
    )
}

/**
 * Signed-out UI: sign in, register an invited account, finish an email invitation, or request
 * one. Stateless; every action is a callback.
 */
@Composable
internal fun SignInContent(
    state: AppState,
    form: SignInForm,
    onRetryRememberedSignIn: () -> Unit,
    onResendInvitation: () -> Unit,
    onShow: (step: String) -> Unit,
    onFinishEnrollment: () -> Unit,
    onRegister: () -> Unit,
    onRequestInvitation: () -> Unit,
    onSignIn: () -> Unit
) {
    Box(Modifier.fillMaxSize().safeDrawingPadding(), contentAlignment = Alignment.TopCenter) {
        Column(
            Modifier.widthIn(
                max = 520.dp
            ).fillMaxSize().verticalScroll(
                rememberScrollState()
            ).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Spacer(Modifier.height(32.dp))
            BrandHeader()
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                form.server,
                {
                    form.server = it
                },
                label = { Text("Server address") },
                placeholder = {
                    Text("https://your-household-server.example")
                },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                isError = state.fields.containsKey("server"),
                supportingText = { state.fields["server"]?.let { Text(it) } }
            )
            OutlinedTextField(
                form.email,
                {
                    form.email = it
                },
                label = {
                    Text("Email or phone number")
                },
                modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                singleLine = true
            )
            if (state.message.isNotBlank()) Text(state.message, color = messageColor(state.error))
            if (state.syncProblem) {
                OutlinedButton(onClick = {
                    onRetryRememberedSignIn()
                }) { Text("Retry remembered sign-in") }
            }
            if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            when (state.onboarding) {
                "claim" -> {
                    Text(
                        "Invited by email? Use the link in the invitation, or have it sent " +
                            "again. No additional administrator approval."
                    )
                    Button(onClick = {
                        onResendInvitation()
                    }, enabled = !state.busy) {
                        Text("Resend invitation email")
                    }
                    TextButton(onClick = {
                        onShow("enroll")
                    }) { Text("Enter invitation link") }
                    TextButton(onClick = {
                        onShow("signin")
                    }) { Text("Back to sign-in") }
                }

                "enroll" -> {
                    Text(
                        "Choose your display username and password. Your " +
                            "email remains your login and recovery address."
                    )
                    OutlinedTextField(form.confirmation, {
                        form.confirmation = it
                    }, label = {
                        Text("Email link or token")
                    }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(
                        form.chosenUsername,
                        { form.chosenUsername = it },
                        label = {
                            Text("Display username")
                        },
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        form.password,
                        {
                            form.password = it
                        },
                        label = { Text("Choose password (new members)") },
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        form.passwordConfirmation,
                        {
                            form.passwordConfirmation = it
                        },
                        label = { Text("Confirm password") },
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth()
                    )
                    Button(
                        onClick = {
                            onFinishEnrollment()
                        },
                        enabled =
                            !state.busy && form.password == form.passwordConfirmation &&
                                form.chosenUsername.length in 3..64
                    ) {
                        Text("Finish enrollment")
                    }
                    TextButton(onClick = {
                        onShow("claim")
                    }, enabled = !state.busy) { Text("Resend invitation") }
                    TextButton(onClick = {
                        onShow("request")
                    }, enabled = !state.busy) { Text("Request access") }
                    TextButton(onClick = {
                        onShow("signin")
                        form.firstStep = false
                    }, enabled = !state.busy) { Text("Back to sign-in") }
                }

                "register" -> {
                    Text("Register new account")
                    Text(
                        "Use the email or phone number you were invited with. Your name is " +
                            "what your household sees. Next, this phone is sent a code to " +
                            "confirm it's you."
                    )
                    OutlinedTextField(
                        form.chosenUsername,
                        { form.chosenUsername = it },
                        label = { Text("Your name (one or two words)") },
                        keyboardOptions = KeyboardOptions(
                            capitalization = KeyboardCapitalization.Words
                        ),
                        singleLine = true,
                        isError = state.fields.containsKey("username"),
                        supportingText = { state.fields["username"]?.let { Text(it) } },
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        form.password,
                        { form.password = it },
                        label = { Text("Password (15+ characters)") },
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        form.passwordConfirmation,
                        { form.passwordConfirmation = it },
                        label = { Text("Verify password") },
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth()
                    )
                    Button(
                        onClick = { onRegister() },
                        enabled = !state.busy && form.registrationProblem() == null,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Create account") }
                    form.registrationProblem()?.let { Text(it) }
                    TextButton(onClick = {
                        onShow("enroll")
                    }, enabled = !state.busy) { Text("I have an email link") }
                    TextButton(onClick = {
                        onShow("signin")
                    }, enabled = !state.busy) { Text("Back to sign-in") }
                }

                "request" -> {
                    Text(
                        "The administrator approves invitations. " +
                            "Requesting access doesn't automatically " + "join the household."
                    )
                    OutlinedTextField(form.requestName, {
                        form.requestName = it
                    }, label = {
                        Text("Your name")
                    }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(form.relationship, {
                        form.relationship = it
                    }, label = {
                        Text("Relationship to household")
                    }, modifier = Modifier.fillMaxWidth())
                    Button(onClick = {
                        onRequestInvitation()
                    }, enabled = !state.busy) { Text("Request invitation") }
                    TextButton(onClick = {
                        onShow("signin")
                        form.firstStep = true
                    }) { Text("Back") }
                }

                else -> {
                    if (form.firstStep) {
                        Button(onClick = {
                            if (form.email.isNotBlank() && form.server.isNotBlank()) {
                                form.firstStep = false
                            }
                        }, modifier = Modifier.fillMaxWidth()) {
                            Text("Continue")
                        }
                        OutlinedButton(onClick = {
                            onShow("register")
                        }, modifier = Modifier.fillMaxWidth()) {
                            Text("Register new account")
                        }
                    } else {
                        OutlinedTextField(
                            form.password,
                            { form.password = it },
                            label = { Text("Password") },
                            visualTransformation = if (form.showPassword) {
                                VisualTransformation.None
                            } else {
                                PasswordVisualTransformation()
                            },
                            trailingIcon = {
                                TextButton(onClick = {
                                    form.showPassword = !form.showPassword
                                }) {
                                    Text(if (form.showPassword) "Hide" else "Show")
                                }
                            },
                            modifier = Modifier.fillMaxWidth()
                        )
                        Button(onClick = {
                            onSignIn()
                        }, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) {
                            Text("Sign in")
                        }
                        OutlinedButton(onClick = {
                            onShow("register")
                        }, enabled = !state.busy) {
                            Text("Register new account")
                        }
                        TextButton(onClick = {
                            form.firstStep = true
                        }) { Text("Change email or phone") }
                    }
                    TextButton(onClick = {
                        onShow("request")
                    }) { Text("Request household access") }
                }
            }
        }
    }
}

/** Preview of the sign-in form. */
@Preview
@Composable
private fun SignInPreview() {
    NaraHemTheme {
        SignInContent(
            state = AppState(restoring = false),
            form = SignInForm(server = "https://family.example").apply { firstStep = false },
            onRetryRememberedSignIn = {},
            onResendInvitation = {},
            onShow = {},
            onFinishEnrollment = {},
            onRegister = {},
            onRequestInvitation = {},
            onSignIn = {}
        )
    }
}

/** Preview of the invitation form. */
@Preview
@Composable
private fun EnrollmentPreview() {
    NaraHemTheme {
        SignInContent(
            state = AppState(restoring = false, onboarding = "enroll"),
            form = SignInForm(server = "https://family.example", confirmation = "token"),
            onRetryRememberedSignIn = {},
            onResendInvitation = {},
            onShow = {},
            onFinishEnrollment = {},
            onRegister = {},
            onRequestInvitation = {},
            onSignIn = {}
        )
    }
}
