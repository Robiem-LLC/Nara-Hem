import SwiftUI

/// Device setup screen: register this iPhone, confirm it by email, or set up a new household's
/// first device.
struct DeviceApprovalView: View {
    @Bindable var model: DeviceApprovalViewModel

    var body: some View {
        NavigationStack {
            Form {
                Section("Device approval") {
                    Label(
                        model.session.account?.name ?? "Signed in",
                        systemImage: "person.crop.circle")
                    Text(model.explanation).foregroundStyle(.secondary)
                    if model.session.deviceStatus == "register" {
                        Button("Register this iPhone") { model.enrollDevice() }
                            .disabled(model.session.busy)
                    }
                    if model.session.deviceStatus == "first-device" {
                        Button("Email the first-device code") { model.requestFirstCode() }.disabled(
                            model.session.busy)
                        TextField("Six-digit code", text: $model.code).keyboardType(.numberPad)
                        Button("Create signed household trust root") {
                            model.finishFirstCode()
                        }
                        .disabled(model.session.busy || model.code.count != 6)
                    }
                    if model.session.deviceStatus == "email-code" {
                        Text(
                            """
                            Email verification authorizes your phone automatically. No \
                            additional household approval is required.
                            """
                        )
                        .font(.footnote)
                        Button("Send my six-digit code") { model.requestPhoneCode() }.disabled(
                            model.session.busy)
                        TextField("Six-digit code", text: $model.code)
                            .keyboardType(.numberPad)
                        Button("Verify and register this iPhone") {
                            model.confirmPhoneCode()
                        }
                        .disabled(model.session.busy || model.code.count != 6)
                        Button("Start registration over") { model.restartPhoneRegistration() }
                            .disabled(model.session.busy)
                    }
                    if model.session.deviceStatus == "replacement-required" {
                        Text(
                            """
                            Your account already has a registered phone. Ask the \
                            administrator to revoke the previous phone, then start \
                            registration again.
                            """
                        )
                        .foregroundStyle(warn)
                        Button("Check again") { model.restartPhoneRegistration() }.disabled(
                            model.session.busy)
                    }
                    if ["pending", "pairing"].contains(model.session.deviceStatus) {
                        if !model.session.pairingCode.isEmpty {
                            Text(model.session.pairingCode).font(
                                .system(size: 44, weight: .bold, design: .monospaced)
                            )
                            .frame(maxWidth: .infinity).textSelection(.enabled)
                        }
                        Text(
                            """
                            Compare this code on an already-approved phone or owner browser. \
                            Approve there, then refresh here. Do not share the code through \
                            the server.
                            """
                        )
                        .font(.footnote).foregroundStyle(.secondary)
                    }
                    Button("Check approval") { model.checkApproval() }.disabled(model.session.busy)
                }
                Section { Button("Sign out", role: .destructive) { model.signOut() } }
                NoticeView(session: model.session)
            }.navigationTitle("Trust this iPhone")
                // Registers straight away, as Android does, so the next screen is the code. If it
                // fails, the button stays to try again.
                .task(id: model.session.deviceStatus) {
                    if model.session.deviceStatus == "register", !model.session.busy {
                        model.enrollDevice()
                    }
                }
        }
    }
}

#if DEBUG
    #Preview {
        DeviceApprovalView(model: AppViewModel.preview(deviceStatus: "email-code").approval)
    }
#endif
