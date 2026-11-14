import SwiftUI

/// Shows the running action and the latest message at the bottom of a screen.
struct NoticeView: View {
    let session: HouseholdSession

    var body: some View {
        if session.busy { ProgressView("Working") }
        if !session.message.isEmpty {
            Text(session.message).font(.footnote).foregroundStyle(warn)
        }
    }
}
