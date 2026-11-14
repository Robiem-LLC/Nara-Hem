import XCTest

@testable import NaraHem

final class HouseholdProtocolTests: XCTestCase {
    func testCrossPlatformCanonicalJsonAndPairingCode() throws {
        let base64 = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
        let registration: Wire.Object = [
            "domain": "narahem.device.v1",
            "household": "0123456789abcdef0123456789abcdef",
            "id": "fedcba98765432100123456789abcdef",
            "account_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "signing_key": base64, "box_key": base64,
        ]
        // Expected values come from the other implementations: the server's canonical JSON
        // (Python json.dumps(sort_keys=True, ensure_ascii=False)) hashed with SHA-256, and the
        // web client's pairingCode() in apps/webapp/frontend/src/crypto.mjs.
        XCTAssertEqual(
            Wire.hash(try Wire.canonical(registration)),
            "5300a510533fcfe2cf92b19587e3f20fcb065ec3b1ab46927c598effcc5d2425")
        XCTAssertEqual(try Wire.pairingCode(registration: registration, anchor: base64), "238474")
    }

    func testDetachedSignatureCannotAuthenticateModifiedRoster() throws {
        let signing = try HouseholdCipher.signingKeys()
        let original: Wire.Object = [
            "domain": "narahem.roster.v1",
            "household": "0123456789abcdef0123456789abcdef",
            "revision": 1, "previous": "", "signer": "fedcba98765432100123456789abcdef",
            "issued_at": 1700000000,
            "devices": [
                [
                    "id": "fedcba98765432100123456789abcdef",
                    "account_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "signing_key": signing.pub, "box_key": try HouseholdCipher.boxKeys().pub,
                ]
            ],
        ]
        let sig = try HouseholdCipher.sign(original, key: signing.secret)
        XCTAssertTrue(HouseholdCipher.verify(original, signature: sig, key: signing.pub))
        var modified = original
        modified["revision"] = 2
        XCTAssertFalse(HouseholdCipher.verify(modified, signature: sig, key: signing.pub))
    }

    func testLibsodiumSealedBoxesRoundTripAndRejectWrongKey() throws {
        let bob = try HouseholdCipher.boxKeys()
        let eve = try HouseholdCipher.boxKeys()
        let payload: Wire.Object = [
            "domain": "narahem.payload.v1", "kind": "location",
            "data": ["lat": 40.123, "lon": -74.456, "accuracy": 10],
        ]
        let ciphertext = try HouseholdCipher.seal(payload, recipient: bob.pub)
        let opened = try HouseholdCipher.open(ciphertext, publicKey: bob.pub, secret: bob.secret)
        XCTAssertEqual(try Wire.canonical(opened), try Wire.canonical(payload))
        XCTAssertThrowsError(
            try HouseholdCipher.open(ciphertext, publicKey: eve.pub, secret: eve.secret))
    }
}
