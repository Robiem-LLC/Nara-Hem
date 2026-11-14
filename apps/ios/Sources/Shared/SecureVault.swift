import CoreLocation
import CryptoKit
import Foundation
import Security

/// Keychain storage for credentials and the location queue key. Items live in the App Group
/// keychain so the notification extension can read them.
enum SecureVault {
    private static let service = "com.robiem.narahem"

    /// Keychain access group shared with the notification service extension.
    private static let sharedGroup = HouseholdAlerts.appGroup

    /// Items kept in memory instead of the keychain. Only tests set this, because unsigned
    /// simulator test runs have no keychain access.
    static var memory: [String: Data]?

    /// Returns the keychain query for an item.
    private static func query(_ key: String, group: String?) -> [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: key,
        ]
        if let group { query[kSecAttrAccessGroup as String] = group }
        return query
    }

    /// Adds or replaces a keychain item.
    private static func write(_ value: Data, key: String, group: String?) -> Bool {
        let query = query(key, group: group)
        let changed = SecItemUpdate(
            query as CFDictionary,
            [kSecValueData as String: value] as CFDictionary)
        if changed == errSecItemNotFound {
            var data = query
            data[kSecValueData as String] = value
            data[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            return SecItemAdd(data as CFDictionary, nil) == errSecSuccess
        }
        return changed == errSecSuccess
    }

    /// Deletes copies of an item that older app versions stored in the app-only keychain group.
    private static func removeLegacyCopies(_ key: String) {
        var search = query(key, group: nil)
        search[kSecReturnAttributes as String] = true
        search[kSecMatchLimit as String] = kSecMatchLimitAll
        var found: CFTypeRef?
        guard SecItemCopyMatching(search as CFDictionary, &found) == errSecSuccess,
            let items = found as? [[String: Any]]
        else { return }
        for item in items {
            if let group = item[kSecAttrAccessGroup as String] as? String, group != sharedGroup {
                SecItemDelete(query(key, group: group) as CFDictionary)
            }
        }
    }

    /// Stores an item in the shared keychain group.
    @discardableResult
    static func put(_ value: Data, key: String) -> Bool {
        if memory != nil {
            memory?[key] = value
            return true
        }
        if write(value, key: key, group: sharedGroup) {
            removeLegacyCopies(key)
            return true
        }
        // Unsigned simulator builds have no App Group, so fall back to the app's own keychain.
        return write(value, key: key, group: nil)
    }

    /// Moves an item from the app-only group into the shared group.
    static func share(_ key: String) {
        if let value = get(key) { put(value, key: key) }
    }

    /// Reads an item from the keychain.
    static func get(_ key: String) -> Data? {
        if let memory { return memory[key] }
        var query = query(key, group: nil)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var data: CFTypeRef?
        return SecItemCopyMatching(query as CFDictionary, &data) == errSecSuccess
            ? data as? Data : nil
    }

    /// Deletes an item from every keychain group the app can access.
    static func delete(_ key: String) {
        if memory != nil {
            memory?[key] = nil
            return
        }
        SecItemDelete(query(key, group: nil) as CFDictionary)
    }
}
