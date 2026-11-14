import Foundation
import SwiftUI

/// Outlined button style.
struct NaraHemOutlineButton: ButtonStyle {
    /// Draws the button.
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.subheadline.weight(.medium))
            .foregroundStyle(cream).padding(.horizontal, 18).frame(minHeight: 40)
            .overlay(Capsule().stroke(lineStrong, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}
