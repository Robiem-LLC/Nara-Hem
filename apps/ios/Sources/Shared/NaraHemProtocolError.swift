import CoreFoundation
import CryptoKit
import Foundation
import Sodium

/// Errors from invalid or rejected server responses.
enum NaraHemProtocolError: LocalizedError {
    case rejected(String)
    case http(Int, String)

    var errorDescription: String? {
        switch self {
        case .rejected(let message): return message
        case .http(_, let message): return message
        }
    }
}
