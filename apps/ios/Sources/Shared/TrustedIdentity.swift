import Foundation

/// This phone's household identity: keys, device credential, household ID and the last verified
/// roster state.
struct TrustedIdentity: Codable {
    var server: String
    var id: String
    var accountId: String
    var household: String
    var signing: HouseholdCipher.KeyPair
    var box: HouseholdCipher.KeyPair
    var credential: String
    var anchor: String = ""
    var revision: Int = 0
    var chainHash: String = ""
    var sequence: Int = 0
    var pinnedAudience: [String]? = nil

    /// Members this phone has already seen, so newcomers can be added to a pinned audience.
    var knownMembers: [String]? = nil

    var registration: Wire.Object {
        [
            "domain": "narahem.device.v1", "household": household, "id": id,
            "account_id": accountId, "signing_key": signing.pub, "box_key": box.pub,
            "platform": "ios",
        ]
    }

    var record: Wire.Object {
        ["id": id, "account_id": accountId, "signing_key": signing.pub, "box_key": box.pub]
    }
}
