import SwiftUI

/// An outlined text field, like the Android app's.
struct NaraHemFieldStyle: TextFieldStyle {
    /// Draws the field.
    func _body(configuration: TextField<Self._Label>) -> some View {
        configuration
            .padding(.horizontal, 14).frame(minHeight: 50)
            .background(panelSunken, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(lineStrong, lineWidth: 1))
    }
}
