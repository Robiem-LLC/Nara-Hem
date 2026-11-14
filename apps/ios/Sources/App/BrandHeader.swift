import SwiftUI

/// The NÄRA HEM wordmark with the tagline under it, used on sign-in, loading and Settings.
struct BrandHeader: View {
    var height: CGFloat = 64
    var centered = false

    var body: some View {
        VStack(alignment: centered ? .center : .leading, spacing: height / 6) {
            Image("NaraHemWordmark")
                .resizable()
                .scaledToFit()
                .frame(height: height)
                .accessibilityLabel("Nära Hem")
            Text("YOUR HOME. YOUR DATA.")
                .font(.system(size: min(max(height / 5, 10), 14), weight: .semibold))
                .tracking(3)
                .foregroundStyle(accent)
        }
    }
}
