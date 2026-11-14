import SwiftUI

/// A short banner over the tabs when members join. Tap to dismiss, or it goes after 8 seconds.
struct JoinNoticeView: View {
    let session: HouseholdSession

    var body: some View {
        if !session.joinNotice.isEmpty {
            Text(session.joinNotice)
                .font(.callout)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(midnight, in: RoundedRectangle(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(accent.opacity(0.6)))
                .padding()
                .onTapGesture { session.joinNotice = "" }
                .task(id: session.joinNotice) {
                    try? await Task.sleep(for: .seconds(8))
                    session.joinNotice = ""
                }
                .accessibilityAddTraits(.isStaticText)
        }
    }
}
