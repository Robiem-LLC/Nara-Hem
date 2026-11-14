import Foundation
import SwiftUI

/// Pill-shaped button style, filled when selected.
struct NaraHemChip: ButtonStyle {
    let selected: Bool

    /// Draws the chip.
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.subheadline.weight(.medium))
            .foregroundStyle(selected ? accent : cream)
            .padding(.horizontal, 17).frame(minHeight: 38)
            .background(selected ? accentContainer : panel, in: RoundedRectangle(cornerRadius: 11))
            .overlay(
                RoundedRectangle(cornerRadius: 11)
                    .stroke(selected ? Color.clear : lineStrong, lineWidth: 1)
            )
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}
