import SwiftUI

/// Top-level view: the restoring screen, sign-in, device setup, or the four tabs.
struct RootView: View {
    let app: AppViewModel
    @State private var selectedTab = 0

    var body: some View {
        ZStack {
            // Behind everything, full screen, whatever size the screen's content is.
            AppBackground()
            content
        }
        .foregroundStyle(cream)
        .preferredColorScheme(.dark)
        .tint(accent)
        .onAppear { app.session.tracker.askForLocationOnFirstLaunch() }
    }

    /// The restoring screen, sign-in, device setup, or the tabs.
    @ViewBuilder private var content: some View {
        Group {
            if app.session.restoring {
                VStack(spacing: 28) {
                    BrandHeader(height: 56, centered: true)
                    ProgressView("Restoring secure session")
                }
            } else if !app.session.signedIn {
                SignInView(model: app.signIn)
            } else if app.session.deviceStatus != "ready" {
                DeviceApprovalView(model: app.approval)
            } else {
                tabs
            }
        }
    }

    private var tabs: some View {
        VStack(spacing: 0) {
            Group {
                switch selectedTab {
                case 0:
                    NavigationStack {
                        HouseholdMapScreen(
                            model: app.map,
                            onViewTrips: { member in
                                app.trips.loadTrips(memberId: member)
                                selectedTab = 1
                            })
                    }
                case 1: NavigationStack { TripsScreen(model: app.trips, places: app.places) }
                case 2: NavigationStack { PlacesScreen(model: app.places) }
                default: NavigationStack { SettingsScreen(model: app.settings) }
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
            HStack(spacing: 0) {
                navItem(0, "Map", "map.fill")
                navItem(1, "Trips", "car.side.fill")
                navItem(2, "Places", "mappin")
                navItem(3, "Settings", "gearshape.fill")
            }
            .padding(.top, 6)
            .padding(.bottom, 2)
            .background(midnight)
        }
        .overlay(alignment: .top) { JoinNoticeView(session: app.session) }
    }

    /// One button in the bottom tab bar.
    private func navItem(_ index: Int, _ label: String, _ icon: String) -> some View {
        Button {
            selectedTab = index
        } label: {
            VStack(spacing: 2) {
                NaraHemNavIcon(kind: index, color: selectedTab == index ? accent : subdued)
                    .frame(width: 60, height: 29)
                    .background(
                        selectedTab == index ? subdued.opacity(0.23) : .clear,
                        in: Capsule())
                Text(label).font(.caption.weight(.medium))
            }
            .foregroundStyle(selectedTab == index ? accent : subdued)
            .frame(maxWidth: .infinity)
            .contentShape(Rectangle())
        }.buttonStyle(.plain)
            .accessibilityLabel(label)
            .accessibilityAddTraits(selectedTab == index ? [.isSelected] : [])
    }
}

#if DEBUG
    #Preview {
        RootView(app: AppViewModel.preview())
    }
#endif
