import SwiftUI

/// Adds or changes the account's email address or phone number in two steps: the new one and the
/// password, then the six-digit code sent to it. Nothing changes until the code is entered, and the
/// other one is left as it is.
struct ContactChangeSheet: View {
    @Environment(\.dismiss) private var dismiss
    let session: HouseholdSession
    let phone: Bool
    let adding: Bool
    private var what: String { phone ? "phone number" : "email address" }
    @State private var value = ""
    @State private var password = ""
    @State private var code = ""
    @State private var sentTo: String?
    @State private var problem = ""
    @State private var busy = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let sentTo {
                        FormSection(title: "Enter the code") {
                            Text(codePrompt(sentTo)).font(.footnote).foregroundStyle(subdued)
                            TextField("Six-digit code", text: $code)
                                .keyboardType(.numberPad).textContentType(.oneTimeCode)
                        }
                    } else {
                        FormSection(title: "New \(what)") {
                            Text("Enter your new \(what) and your password. We'll send it a code.")
                                .font(.footnote).foregroundStyle(subdued)
                            TextField("New \(what)", text: $value)
                                .keyboardType(phone ? .phonePad : .emailAddress)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                            SecureField("Password", text: $password)
                        }
                    }
                    if !problem.isEmpty {
                        Text(problem).font(.footnote).foregroundStyle(dangerText)
                    }
                    if busy { ProgressView() }
                }
                .textFieldStyle(NaraHemFieldStyle())
                .padding(18)
            }
            .background(AppBackground())
            .foregroundStyle(cream)
            .navigationTitle((adding ? "Add " : "Change ") + what)
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(midnight, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if sentTo == nil {
                        Button("Send code") { sendCode() }
                            .disabled(busy || value.isEmpty || password.isEmpty)
                    } else {
                        Button("Confirm") { confirm() }.disabled(busy || code.count != 6)
                    }
                }
            }
        }
        .preferredColorScheme(.dark)
        .tint(accent)
    }

    /// Says where the code went.
    private func codePrompt(_ destination: String) -> String {
        "Enter the six-digit code sent to \(destination). It expires in 10 minutes."
    }

    /// Asks the server to send a code to the new email address or phone number.
    private func sendCode() {
        run {
            sentTo = try await session.requestContactChange(
                value.trimmingCharacters(in: .whitespaces), password: password, phone: phone)
        }
    }

    /// Confirms the code, which makes the change.
    private func confirm() {
        run {
            try await session.confirmContactChange(code: code)
            dismiss()
        }
    }

    /// Runs a request, showing progress and any error.
    private func run(_ task: @escaping () async throws -> Void) {
        busy = true
        problem = ""
        Task {
            do { try await task() } catch { problem = error.localizedDescription }
            busy = false
        }
    }
}
