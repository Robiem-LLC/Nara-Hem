import Foundation

/// The letters shown for someone without a profile photo: the first letter of each word of their
/// name, so "John Doe" is "JD" and "Kim" is "K". Same rule as Android and the web app.
enum Initials {
    /// Returns up to two capital letters for the name, or "?" for an empty one.
    static func of(_ name: String) -> String {
        let letters = name.split(whereSeparator: \.isWhitespace).prefix(2).compactMap(\.first)
        return letters.isEmpty ? "?" : String(letters).uppercased()
    }
}
