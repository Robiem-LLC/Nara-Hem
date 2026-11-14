import SwiftUI

/// Full-screen background: the deep blue glow, lighter at the top and never as dark as the
/// bottom bar.
struct AppBackground: View {
    var body: some View {
        LinearGradient(
            stops: [
                .init(color: glowTop, location: 0),
                .init(color: glowMiddle, location: 0.35),
                .init(color: glowLow, location: 0.75),
                .init(color: glowBottom, location: 1),
            ], startPoint: .top, endPoint: .bottom
        )
        .ignoresSafeArea()
    }
}
