import Foundation
import SwiftUI

/// Filled primary button style, matching the Android app. A compact one sizes to its label, like
/// Android's standard button.
struct NaraHemPrimaryButton: ButtonStyle {
    var compact = false

    /// Draws the button.
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(compact ? .subheadline.weight(.bold) : .headline)
            .foregroundStyle(onAccent)
            .padding(.horizontal, compact ? 24 : 22).frame(minHeight: compact ? 40 : 47)
            .frame(maxWidth: compact ? nil : .infinity)
            .background(accent, in: Capsule())
            .opacity(configuration.isPressed ? 0.75 : 1)
    }
}
