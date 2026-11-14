import Foundation

/// Returns the message shown when members join, e.g. "Kim has joined the household. …".
func joinedMessage(_ names: [String]) -> String {
    let who =
        names.count == 1
        ? names[0] + " has"
        : names.dropLast().joined(separator: ", ") + " and " + names[names.count - 1] + " have"
    return who + " joined the household. Your location is being shared with them."
}
