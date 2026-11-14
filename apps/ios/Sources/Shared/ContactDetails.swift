import Foundation

/// The signed-in account's email address and phone number, either of which may be missing, and
/// whether the server can text (without that, a phone number can't be added).
struct ContactDetails: Equatable {
    var email: String?
    var phone: String?
    var textingOn: Bool
}
