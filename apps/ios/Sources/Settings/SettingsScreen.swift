import PhotosUI
import SwiftUI
import UIKit

/// Settings tab: profile, sharing, Find My Phone, permissions and account.
struct SettingsScreen: View {
    @Bindable var model: SettingsViewModel
    @State private var pickedImage: PhotosPickerItem?
    @State private var showingCamera = false
    @State private var showAudience = false
    @State private var showNotificationHelp = false
    @State private var changingContact: Bool?
    @State private var contact: ContactDetails?
    @State private var showLocationHelp = false

    private var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "unknown"
    }

    private var appBuild: String {
        Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "unknown"
    }

    /// Username and profile photo.
    @ViewBuilder private var profileSection: some View {
        TextField("Display username", text: $model.editableUsername)
            .textInputAutocapitalization(.words)
            .padding(14).background(panelSunken, in: RoundedRectangle(cornerRadius: 9))
        Button("Change username") { model.changeUsername() }
            .buttonStyle(NaraHemOutlineButton())
            .disabled(model.session.busy || model.editableUsername.count < 3)
        Text(
            """
            Email remains your login; changing your username does not reset devices \
            or history.
            """
        )
        .font(.footnote).foregroundStyle(subdued)
        Text("Your photo is visible to approved household members.")
            .font(.footnote).foregroundStyle(subdued)
        HStack(spacing: 10) {
            PhotosPicker(selection: $pickedImage, matching: .images) {
                Text("Choose photo")
            }.buttonStyle(NaraHemOutlineButton())
            Button("Take photo") { showingCamera = true }
                .buttonStyle(NaraHemOutlineButton())
                .disabled(!UIImagePickerController.isSourceTypeAvailable(.camera))
        }
    }

    /// Sharing toggle and the audience for this phone's location.
    @ViewBuilder private var sharingSection: some View {
        HStack {
            VStack(alignment: .leading) {
                Text("Share this phone's location")
                Text(
                    model.session.sharing
                        ? "On · sharing with selected members"
                        : "Off · location updates paused"
                )
                .font(.footnote).foregroundStyle(subdued)
            }
            Spacer()
            Toggle(
                "Share location",
                isOn: Binding(get: { model.session.sharing }, set: { model.setSharing($0) })
            )
            .labelsHidden().disabled(model.session.busy)
        }
        DisclosureGroup("Who can see this phone?", isExpanded: $showAudience) {
            ForEach(model.session.audienceChoices) { viewer in
                Toggle(
                    viewer.name,
                    isOn: Binding(
                        get: { model.session.audience.contains(viewer.id) },
                        set: { model.setViewer(viewer.id, included: $0) }
                    )
                ).disabled(model.session.busy || model.session.syncProblem)
            }
        }
    }

    /// Find My Phone toggle and Do Not Disturb help.
    @ViewBuilder private var findPhoneSection: some View {
        SettingsSubheading(text: "Find my phone")
        Toggle(
            "Allow Find My Phone",
            isOn: Binding(
                get: { model.session.findPhoneEnabled },
                set: { enabled in
                    model.setFindPhone(enabled)
                    if enabled && !model.session.pushPermission {
                        if model.session.notificationPermissionDenied {
                            showNotificationHelp = true
                        } else {
                            model.requestNotifications()
                        }
                    }
                })
        )
        .disabled(model.session.busy)
        Text(
            """
            Rings through Do Not Disturb. If a Focus mode blocks it, turn on Time Sensitive \
            Notifications for Nära Hem.
            """
        )
        .font(.footnote).foregroundStyle(subdued)
        Button("Open notification settings") { model.openNotificationSettings() }
            .buttonStyle(NaraHemOutlineButton())
    }

    /// Notification and background location permissions.
    @ViewBuilder private var accessSection: some View {
        SettingsSubheading(text: "Notifications & location")
        HStack {
            Text("Notifications")
            Spacer()
            Text(model.session.pushPermission ? "Allowed" : "Needs permission")
                .foregroundStyle(model.session.pushPermission ? accent : warn)
        }
        Button(
            model.session.pushPermission
                ? "Review notification permissions" : "Enable notifications"
        ) {
            if model.session.pushPermission || model.session.notificationPermissionDenied {
                showNotificationHelp = true
            } else {
                model.requestNotifications()
            }
        }.buttonStyle(NaraHemOutlineButton())
        HStack {
            Text("Background location")
            Spacer()
            Text(model.locationDescription)
                .foregroundStyle(
                    model.tracker.locationPermission == .authorizedAlways ? accent : warn)
        }
        Toggle(
            "Collect GPS in background",
            isOn: Binding(
                get: { model.tracker.trackingEnabled }, set: { model.setTracking($0) }))
        Text(
            """
            Stationary location check-ins are automatic while location sharing is on. \
            While parked, GPS is off and a check-in is sent about every 15 minutes; \
            iOS may still delay or suspend location updates. An old location is never \
            relabeled as new.
            """
        )
        .font(.footnote).foregroundStyle(subdued)
        if model.tracker.locationPermission != .authorizedAlways {
            Button("Enable Always location") { showLocationHelp = true }
                .buttonStyle(NaraHemOutlineButton())
                .alert("Enable background location", isPresented: $showLocationHelp) {
                    Button("Request location permission") {
                        model.tracker.requestBackgroundLocation()
                    }
                    Button("Open Nära Hem Settings") { model.openSettings() }
                    Button("Cancel", role: .cancel) {}
                } message: {
                    Text(
                        """
                        Allow Location While Using the App, then choose Always when \
                        iOS offers it. If already denied, use Settings → Nära Hem → \
                        Location → Always and enable Precise Location. Return to \
                        Nära Hem to update the server.
                        """
                    )
                }
        }
    }

    /// Device status, revoke, sign out and build information.
    @ViewBuilder private var accountSection: some View {
        Text("Device trust: \(model.session.deviceStatus)")
            .foregroundStyle(subdued)
        contactRow("Email", value: contact?.email ?? "None", phone: false, enabled: true)
        contactRow(
            "Phone",
            value: contact?.phone ?? (contact?.textingOn == true ? "None" : "Unavailable"),
            phone: true, enabled: contact?.textingOn == true)
        Button("Revoke this iPhone", role: .destructive) { model.revokeThisPhone() }
        Button("Sign out", role: .destructive) { model.signOut() }
        BrandHeader(height: 34).padding(.top, 12)
        VStack(alignment: .leading, spacing: 4) {
            Text("Version \(appVersion) · Build \(appBuild)")
            Text("Built \(NaraHemBuild.dateString)")
            Text("Commit \(NaraHemBuild.commit)")
        }
        .font(.footnote.monospacedDigit()).foregroundStyle(subdued)
        .textSelection(.enabled)
    }

    /// One labelled contact value with its Add or Change button. The phone has no button while the
    /// server can't text.
    private func contactRow(
        _ label: String, value: String, phone: Bool, enabled: Bool
    ) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(.subheadline.weight(.semibold))
                Text(value).font(.footnote).foregroundStyle(subdued)
            }
            Spacer()
            Button((phone ? contact?.phone : contact?.email) == nil ? "Add" : "Change") {
                changingContact = phone
            }
            .buttonStyle(NaraHemOutlineButton())
            .disabled(!enabled)
        }
    }

    /// Loads the account's email and phone for the rows above.
    private func loadContact() async {
        contact = try? await model.session.contactDetails()
    }

    /// Photo, name and sharing status, always shown above the sections.
    @ViewBuilder private var accountCard: some View {
        HStack(spacing: 14) {
            if let me = model.me {
                ProfileAvatar(member: me).frame(width: 56, height: 56)
            } else {
                Image(systemName: "person.crop.circle.fill")
                    .resizable().frame(width: 56, height: 56).foregroundStyle(accent)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(model.session.account?.name ?? "Member").font(.headline)
                Text(sharingStatus).font(.footnote).foregroundStyle(accent)
            }
        }
    }

    private var sharingStatus: String {
        guard model.session.sharing else { return "Location sharing is off" }
        let viewers = model.session.audienceChoices.filter {
            model.session.audience.contains($0.id)
        }
        return "Sharing your location · \(viewers.count) can see you"
    }

    private var profileSummary: String {
        let name = model.session.account?.name ?? "Member"
        let photo = model.me?.photo ?? ""
        return name + (photo.isEmpty ? " · no photo" : " · photo set")
    }

    /// How many things on this iPhone stop sharing, alerts or Find my phone from working.
    private var permissionIssues: Int {
        [
            model.tracker.locationPermission != .authorizedAlways,
            !model.session.pushPermission,
        ].filter { $0 }.count
    }

    private var permissionsSummary: String {
        switch permissionIssues {
        case 0:
            "Sharing \(model.session.sharing ? "on" : "off") · Find my phone "
                + (model.session.findPhoneEnabled ? "on" : "off")
        case 1: "1 needs attention"
        default: "\(permissionIssues) need attention"
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Settings").font(.largeTitle.weight(.regular))
                accountCard
                NoticeView(session: model.session)
                SettingsGroup(title: "Profile", summary: profileSummary) { profileSection }
                SettingsGroup(
                    title: "Permissions", summary: permissionsSummary,
                    attention: permissionIssues > 0
                ) {
                    SettingsSubheading(text: "Location sharing")
                    sharingSection
                    Divider()
                    findPhoneSection
                    Divider()
                    accessSection
                }
                SettingsGroup(title: "Account & about", summary: "Version \(appVersion)") {
                    accountSection
                }
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(AppBackground())
        .alert("Check iPhone notification permissions", isPresented: $showNotificationHelp) {
            Button("Open notification settings") { model.openNotificationSettings() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(
                """
                Turn on Allow Notifications, Sounds, Lock Screen and Time Sensitive \
                Notifications for Nära Hem.
                """
            )
        }
        .onAppear { model.opened() }
        .sheet(
            isPresented: Binding(
                get: { changingContact != nil }, set: { if !$0 { changingContact = nil } }),
            onDismiss: { Task { await loadContact() } }
        ) {
            let phone = changingContact ?? false
            ContactChangeSheet(
                session: model.session, phone: phone,
                adding: (phone ? contact?.phone : contact?.email) == nil)
        }
        .task { await loadContact() }
        .toolbar(.hidden, for: .navigationBar)
        .sheet(isPresented: $showingCamera) {
            CameraCaptureView(
                onCapture: { image in
                    showingCamera = false
                    model.saveProfileImage(image)
                }, onCancel: { showingCamera = false })
        }
        .onChange(of: pickedImage) { _, item in
            Task {
                guard let raw = try? await item?.loadTransferable(type: Data.self),
                    let image = UIImage(data: raw)
                else { return }
                model.saveProfileImage(image)
            }
        }
    }
}

#if DEBUG
    #Preview {
        SettingsScreen(model: AppViewModel.preview().settings)
    }
#endif
