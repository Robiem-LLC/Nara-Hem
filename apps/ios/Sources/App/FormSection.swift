import SwiftUI

/// A titled panel that groups related fields, like a section of a form. Matches the Android app.
struct FormSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.subheadline.weight(.medium)).foregroundStyle(textLabel)
                .padding(.leading, 4)
            VStack(alignment: .leading, spacing: 10) { content }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(panel, in: RoundedRectangle(cornerRadius: 16))
        }
    }
}
