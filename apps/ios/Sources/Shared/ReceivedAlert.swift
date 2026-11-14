import Foundation

/// An arrival or departure alert from the server, with its display text.
struct ReceivedAlert {
    var id: String
    var accountId: String
    var capturedAt: Int
    var text: String
}
