import SwiftUI

/// A heading inside a Settings section (Location sharing, Find my phone…): small amber capitals,
/// clearly below the section's own title.
struct SettingsSubheading: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.caption.weight(.bold))
            .textCase(.uppercase)
            .tracking(1.2)
            .foregroundStyle(accent)
            .padding(.top, 6)
    }
}
