import SwiftUI

/// Signed-out screen: sign in, register an invited account, or request access. Same structure as
/// Android.
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
                        Button("Register new account") { model.mode = "register" }
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
                        Button("Register new account") { model.mode = "register" }
                        Button("Change email or phone") { model.firstStep = true }
                    }
                    Button("Request household access") { model.mode = "request" }
                        .font(.subheadline.weight(.semibold)).padding(.top, 2)
                } else if model.mode == "register" {
                    Text("Register new account").font(.headline)
                    loginField(
                        "Your name (one or two words)", text: $model.enrollmentUsername,
                        name: true)
                    SecureField("Password (15+ characters)", text: $model.enrollmentPassword)
                        .padding(16).background(panel, in: RoundedRectangle(cornerRadius: 9))
                    SecureField("Verify password", text: $model.enrollmentConfirmPassword)
                        .padding(16).background(panel, in: RoundedRectangle(cornerRadius: 9))
                    Button("Create account") { model.register() }
                        .buttonStyle(NaraHemPrimaryButton())
                        .disabled(!model.canRegister)
                    Text(
                        """
                        Use the email or phone number you were invited with. Your name is what \
                        your household sees. Next, this iPhone is sent a code to confirm it's you.
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
        _ title: String, text: Binding<String>, url: Bool = false, email: Bool = false,
        name: Bool = false
    ) -> some View {
        TextField(title, text: text)
            .textInputAutocapitalization(name ? .words : .never)
            .autocorrectionDisabled()
            .keyboardType(url ? .URL : email ? .emailAddress : .default)
            .textContentType(url ? .URL : name ? .name : .username)
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
