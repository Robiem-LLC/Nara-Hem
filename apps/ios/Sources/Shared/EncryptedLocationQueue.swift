import CoreLocation
import CryptoKit
import Foundation
import Security

/// GPS fixes waiting to upload, stored on disk encrypted with a key kept in the keychain.
final class EncryptedLocationQueue {
    private let url: URL
    private var points: [LocalLocation] = []
    var count: Int { points.count }
    var latest: LocalLocation? { points.last }

    /// Loads the queue saved by the previous run.
    init() {
        let directory = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        url = directory.appendingPathComponent("unsent-location-queue.aesgcm")
        if let ciphertext = try? Data(contentsOf: url),
            let key = SecureVault.get("location-queue-key"),
            let box = try? AES.GCM.SealedBox(combined: ciphertext),
            let plaintext = try? AES.GCM.open(box, using: SymmetricKey(data: key)),
            let stored = try? JSONDecoder().decode([LocalLocation].self, from: plaintext)
        {
            points = stored
        }
    }

    /// Returns up to `limit` of the oldest queued fixes.
    func pending(limit: Int = 12) -> [LocalLocation] { Array(points.prefix(limit)) }

    /// Adds a fix, dropping the oldest when the queue is full.
    func append(
        _ sample: CLLocation, tripId: String? = nil, batteryPct: Int? = nil, charging: Bool? = nil
    ) {
        guard sample.horizontalAccuracy >= 0, sample.horizontalAccuracy <= 250,
            sample.timestamp.timeIntervalSinceNow > -14 * 86400,
            sample.timestamp.timeIntervalSinceNow < 300,
            abs(sample.coordinate.latitude) <= 90, abs(sample.coordinate.longitude) <= 180
        else { return }
        points.append(
            LocalLocation(sample, tripId: tripId, batteryPct: batteryPct, charging: charging))
        if points.count > 2500 { points.removeFirst(points.count - 2500) }
        save()
    }

    /// Removes a fix the server has accepted.
    func acknowledge(_ id: UUID) {
        guard points.first?.id == id else { return }
        points.removeFirst()
        save()
    }

    /// Encrypts and writes the queue to disk.
    private func save() {
        var data = SecureVault.get("location-queue-key")
        if data == nil {
            var bytes = Data(count: 32)
            _ = bytes.withUnsafeMutableBytes { buffer in
                SecRandomCopyBytes(kSecRandomDefault, 32, buffer.baseAddress!)
            }
            SecureVault.put(bytes, key: "location-queue-key")
            data = bytes
        }
        guard let keyData = data, let payload = try? JSONEncoder().encode(points),
            let sealed = try? AES.GCM.seal(payload, using: SymmetricKey(data: keyData)).combined
        else { return }
        try? sealed.write(
            to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    /// Deletes every queued fix.
    func clear() {
        points.removeAll()
        try? FileManager.default.removeItem(at: url)
    }
}
