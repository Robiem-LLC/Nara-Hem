import SwiftUI

extension View {
    /// A card: the panel colour with a thin border in the bottom bar's blue.
    func cardStyle(cornerRadius: CGFloat = 14) -> some View {
        background(panel, in: RoundedRectangle(cornerRadius: cornerRadius))
            .overlay(RoundedRectangle(cornerRadius: cornerRadius).stroke(midnight, lineWidth: 1))
    }
}
