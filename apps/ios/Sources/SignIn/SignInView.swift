import SwiftUI

/// Signed-out screen: sign in, finish an invitation, or request access. Same structure as Android.
struct SignInView: View {
    @Bindable var model: SignInViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                BrandHeader()
                    .padding(.top, 48)
                    .padding(.bottom, 8)
                VStack(spacing: 14) {
                    loginField("Server address", text: Bindable(model.session).server, url: true)
                    loginField("Email or phone number", text: $model.contact, email: true)
                }
                if model.mode == "signin" {
                    if model.firstStep {
                        Button("Continue") { model.firstStep = false }
                            .buttonStyle(NaraHemPrimaryButton())
                            .disabled(model.session.server.isEmpty || model.contact.isEmpty)
                    } else {
                        HStack {
                            if model.showPassword {
                                TextField("Password", text: $model.password)
                            } else {
                                SecureField("Password", text: $model.password)
                            }
                            Button(model.showPassword ? "Hide" : "Show") {
                                model.showPassword.toggle()
                            }
                            .font(.footnote)
                        }.padding(16).background(panel, in: RoundedRectangle(cornerRadius: 9))
                        Button("Sign in") { model.signIn() }
                            .buttonStyle(NaraHemPrimaryButton())
                            .disabled(model.session.busy || model.password.isEmpty)
                        Button("Set up invited account") { model.mode = "invitation" }
                        Button("Change email or phone") { model.firstStep = true }
                    }
                    Button("Request household access") { model.mode = "request" }
                        .font(.subheadline.weight(.semibold)).padding(.top, 2)
                } else if model.mode == "invitation" {
                    Text("Set up an invited account").font(.headline)
                    loginField("Username (display name)", text: $model.enrollmentUsername)
                    SecureField("Password (15+ characters)", text: $model.enrollmentPassword)
                        .padding(16).background(panel, in: RoundedRectangle(cornerRadius: 9))
                    SecureField("Confirm password", text: $model.enrollmentConfirmPassword)
                        .padding(16).background(panel, in: RoundedRectangle(cornerRadius: 9))
                    Button("Resend invitation email") { model.requestInvite() }
                    loginField("Confirmation link or token", text: $model.invitationCode)
                    Button("Confirm invitation") {
                        model.verifyInvite()
                    }.disabled(!model.canConfirmInvitation)
                    Text(
                        """
                        Your email is used for login and recovery. Your username is the name \
                        your household sees. After confirming, verify this iPhone by email.
                        """
                    )
                    .font(.caption).foregroundStyle(subdued)
                    Button("Back to sign-in") { model.mode = "signin" }
                } else {
                    Text("Request household access").font(.headline)
                    loginField("Your name", text: $model.requestedName)
                    loginField("Relationship to household", text: $model.relationship)
                    Button("Request invitation") {
                        model.requestAccess()
                    }.buttonStyle(NaraHemPrimaryButton()).disabled(
                        model.session.busy || model.contact.isEmpty)
                    Button("Back to sign-in") { model.mode = "signin" }
                }
                NoticeView(session: model.session)
                if model.session.busy { ProgressView("Connecting securely") }
            }
            .padding(.horizontal, 24)
            .frame(maxWidth: 520, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }

    /// A text field styled for the sign-in form.
    private func loginField(
        _ title: String, text: Binding<String>, url: Bool = false, email: Bool = false
    ) -> some View {
        TextField(title, text: text)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .keyboardType(url ? .URL : email ? .emailAddress : .default)
            .textContentType(url ? .URL : .username)
            .padding(16)
            .frame(height: 60)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(subdued.opacity(0.65)))
    }
}

#if DEBUG
    #Preview {
        SignInView(model: AppViewModel.preview(signedIn: false).signIn)
    }
#endif
