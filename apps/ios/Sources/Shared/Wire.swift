import CoreFoundation
import CryptoKit
import Foundation
import Sodium

/// JSON helpers for the household protocol: typed field access that throws, and canonical encoding
/// for signatures.
enum Wire {
    /// A JSON object.
    typealias Object = [String: Any]

    /// Returns a nested object, or throws if missing.
    static func dict(_ source: Object, _ key: String) throws -> Object { try object(source[key]) }

    /// Returns the SHA-256 of a string's UTF-8 bytes as hex.
    static func hash(_ text: String) -> String { hash(Data(text.utf8)) }

    /// Returns the current Unix time in seconds.
    static func timestamp() -> Int { Int(Date().timeIntervalSince1970) }

    /// Encodes bytes as base64.
    static func b64(_ bytes: [UInt8]) -> String { Data(bytes).base64EncodedString() }

    /// Returns the value as an object, or throws.
    static func object(_ value: Any?) throws -> Object {
        guard let result = value as? Object else {
            throw NaraHemProtocolError.rejected("Invalid server response")
        }
        return result
    }

    /// Returns an array of objects, or throws if missing or of another type.
    static func array(_ source: Object, _ key: String) throws -> [Object] {
        guard let raw = source[key] as? [Any] else {
            throw NaraHemProtocolError.rejected("Missing \(key)")
        }
        return try raw.map(object)
    }

    /// Returns a string field, or throws.
    static func string(_ source: Object, _ key: String) throws -> String {
        guard let value = source[key] as? String else {
            throw NaraHemProtocolError.rejected("Missing \(key)")
        }
        return value
    }

    /// Returns an integer field, or throws.
    static func integer(_ source: Object, _ key: String) throws -> Int {
        guard let value = source[key] as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID()
        else {
            throw NaraHemProtocolError.rejected("Invalid \(key)")
        }
        // Millisecond timestamps don't fit in 32 bits.
        return Int(value.int64Value)
    }

    /// Returns a numeric field, or throws.
    static func number(_ source: Object, _ key: String) throws -> Double {
        guard let v = source[key] as? NSNumber, CFGetTypeID(v) != CFBooleanGetTypeID(),
            v.doubleValue.isFinite
        else {
            throw NaraHemProtocolError.rejected("Invalid \(key)")
        }
        return v.doubleValue
    }

    /// Serializes an object as JSON.
    static func encode(_ body: Object) throws -> Data {
        try JSONSerialization.data(
            withJSONObject: body, options: [.fragmentsAllowed, .withoutEscapingSlashes])
    }

    /// Parses JSON into an object.
    static func decode(_ bytes: Data) throws -> Object {
        try object(JSONSerialization.jsonObject(with: bytes))
    }

    /// Escapes a string as a JSON literal exactly like the server's json.dumps(ensure_ascii=False).
    /// Signed bodies contain only integers, so float formatting never differs between platforms.
    private static func quoted(_ text: String) -> String {
        var value = "\""
        for char in text.unicodeScalars {
            switch char.value {
            case 34: value += "\\\""
            case 92: value += "\\\\"
            case 8: value += "\\b"
            case 12: value += "\\f"
            case 10: value += "\\n"
            case 13: value += "\\r"
            case 9: value += "\\t"
            case 0..<32: value += String(format: "\\u%04x", char.value)
            default: value.unicodeScalars.append(char)
            }
        }
        return value + "\""
    }

    /// Serializes a value with sorted keys and no whitespace, so every app signs identical bytes.
    static func canonical(_ value: Any) throws -> String {
        if value is NSNull { return "null" }
        if let obj = value as? Object {
            return "{"
                + (try obj.keys.sorted().map { key in
                    quoted(key) + ":" + (try canonical(obj[key]!))
                }).joined(separator: ",") + "}"
        }
        if let list = value as? [Any] {
            return "[" + (try list.map { try canonical($0) }).joined(separator: ",") + "]"
        }
        if let text = value as? String { return quoted(text) }
        if let number = value as? NSNumber {
            if CFGetTypeID(number) == CFBooleanGetTypeID() {
                return number.boolValue ? "true" : "false"
            }
            return number.stringValue
        }
        throw NaraHemProtocolError.rejected("Unsupported signed JSON type")
    }

    /// Returns the SHA-256 digest as hex.
    static func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// Returns a random 128-bit ID as 32 hex characters.
    static func freshId() -> String {
        UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
    }

    /// Decodes base64, checking the length when given.
    static func bytes(_ value: String, length: Int? = nil) throws -> [UInt8] {
        guard let data = Data(base64Encoded: value), length == nil || data.count == length else {
            throw NaraHemProtocolError.rejected("Invalid encoded key or signature")
        }
        return Array(data)
    }

    /// Derives a six-digit code from a registration and the household root key.
    static func pairingCode(registration: Object, anchor: String) throws -> String {
        _ = try bytes(anchor, length: 32)
        let digest = hash(
            "narahem.pairing-code.v1:" + anchor + ":" + hash(try canonical(registration)))
        guard let prefix = UInt64(digest.prefix(12), radix: 16) else {
            throw NaraHemProtocolError.rejected("Invalid pairing digest")
        }
        return String(format: "%06d", Int(prefix % 1_000_000))
    }
}
