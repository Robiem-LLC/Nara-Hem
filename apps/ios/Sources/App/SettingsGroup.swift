import SwiftUI

/// A Settings section that opens and closes. Closed, it shows the title and a one-line summary.
/// When `attention` is true it shows an amber dot and opens by itself.
struct SettingsGroup<Content: View>: View {
    let title: String
    let summary: String
    var attention = false
    @ViewBuilder let content: () -> Content

    /// Nil until the user taps the header; until then the section follows `attention`.
    @State private var open: Bool?

    var body: some View {
        let isOpen = open ?? attention
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) { open = !isOpen }
            } label: {
                HStack(spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(title).font(.title3.weight(.bold)).foregroundStyle(cream)
                        Text(summary).font(.footnote).foregroundStyle(attention ? accent : subdued)
                    }
                    Spacer()
                    if attention {
                        Circle().fill(accent).frame(width: 10, height: 10)
                    }
                    Image(systemName: "chevron.down")
                        .rotationEffect(.degrees(isOpen ? 180 : 0))
                        .foregroundStyle(subdued)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 14)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityValue(isOpen ? "Open" : "Closed")
            if isOpen {
                VStack(alignment: .leading, spacing: 14) { content() }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 16)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(panel, in: RoundedRectangle(cornerRadius: 16))
        .onChange(of: attention) { _, now in
            if now { open = true }
        }
    }
}
