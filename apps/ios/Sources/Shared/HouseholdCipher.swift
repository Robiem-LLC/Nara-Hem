import CoreFoundation
import CryptoKit
import Foundation
import Sodium

/// Libsodium operations used by the household protocol: Ed25519 signatures and sealed boxes.
enum HouseholdCipher {
    private static let sodium = Sodium()

    /// Generates an Ed25519 signing key pair.
    static func signingKeys() throws -> KeyPair {
        guard let result = sodium.sign.keyPair() else {
            throw NaraHemProtocolError.rejected("Unable to generate signing identity")
        }
        return KeyPair(pub: Wire.b64(result.publicKey), secret: Wire.b64(result.secretKey))
    }

    /// Generates an X25519 key pair for sealed boxes.
    static func boxKeys() throws -> KeyPair {
        guard let result = sodium.box.keyPair() else {
            throw NaraHemProtocolError.rejected("Unable to generate encryption identity")
        }
        return KeyPair(pub: Wire.b64(result.publicKey), secret: Wire.b64(result.secretKey))
    }

    /// Returns a detached Ed25519 signature over the canonical JSON.
    static func sign(_ object: Wire.Object, key: String) throws -> String {
        let message = Array((try Wire.canonical(object)).utf8)
        guard
            let signature = sodium.sign.signature(
                message: message, secretKey: try Wire.bytes(key, length: 64))
        else {
            throw NaraHemProtocolError.rejected("Signing operation failed")
        }
        return Wire.b64(signature)
    }

    /// Verifies a detached signature over the canonical JSON. Returns false on any error.
    static func verify(_ body: Wire.Object, signature: String, key: String) -> Bool {
        guard let data = try? Wire.canonical(body),
            let sig = try? Wire.bytes(signature, length: 64),
            let publicKey = try? Wire.bytes(key, length: 32)
        else { return false }
        return sodium.sign.verify(message: Array(data.utf8), publicKey: publicKey, signature: sig)
    }

    /// Encrypts the canonical JSON as a sealed box for the recipient's public key.
    static func seal(_ object: Wire.Object, recipient: String) throws -> String {
        guard
            let cipher = sodium.box.seal(
                message: Array((try Wire.canonical(object)).utf8),
                recipientPublicKey: try Wire.bytes(recipient, length: 32))
        else {
            throw NaraHemProtocolError.rejected("Encryption failed")
        }
        return Wire.b64(cipher)
    }

    /// Decrypts a sealed box addressed to this key pair and parses the JSON inside.
    static func open(_ sealed: String, publicKey: String, secret: String) throws -> Wire.Object {
        guard
            let plain = sodium.box.open(
                anonymousCipherText: try Wire.bytes(sealed),
                recipientPublicKey: try Wire.bytes(publicKey, length: 32),
                recipientSecretKey: try Wire.bytes(secret, length: 32))
        else {
            throw NaraHemProtocolError.rejected("Encrypted record could not be authenticated")
        }
        return try Wire.decode(Data(plain))
    }

    /// A public and private key, both base64.
    struct KeyPair: Codable {
        var pub: String
        var secret: String
    }
}
