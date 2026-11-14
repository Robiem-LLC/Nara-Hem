import Foundation

/// Notification sound for Find My Phone pushes. iOS plays it even while the app is suspended. It is
/// not a Critical Alert, so Silent Mode and Focus still apply.
enum FindPhoneNotificationSound {
    static let filename = "narahem-find-phone-v1.wav"
    private static let sampleRate = 44_100

    // iOS plays at most 30 seconds of a notification sound.
    private static let seconds = 30

    /// Writes the siren WAV to Library/Sounds if it isn't there, so pushes can use it.
    static func installIfNeeded() {
        let fm = FileManager.default
        guard let library = fm.urls(for: .libraryDirectory, in: .userDomainMask).first else {
            return
        }
        let folder = library.appendingPathComponent("Sounds", isDirectory: true)
        let destination = folder.appendingPathComponent(filename)
        let expectedBytes = 44 + sampleRate * seconds * 2
        if (try? fm.attributesOfItem(atPath: destination.path)[.size] as? Int) == expectedBytes {
            return
        }
        do {
            try fm.createDirectory(at: folder, withIntermediateDirectories: true)
            var audio = Data(capacity: expectedBytes)
            func bytes(_ string: String) { audio.append(contentsOf: string.utf8) }
            func le16(_ value: UInt16) {
                let v = value.littleEndian
                audio.append(UInt8(truncatingIfNeeded: v))
                audio.append(UInt8(truncatingIfNeeded: v >> 8))
            }
            func le32(_ value: UInt32) {
                let v = value.littleEndian
                for shift in stride(from: 0, through: 24, by: 8) {
                    audio.append(UInt8(truncatingIfNeeded: v >> shift))
                }
            }
            let count = sampleRate * seconds
            bytes("RIFF"); le32(UInt32(36 + count * 2)); bytes("WAVE")
            bytes("fmt "); le32(16); le16(1); le16(1)
            le32(UInt32(sampleRate)); le32(UInt32(sampleRate * 2)); le16(2); le16(16)
            bytes("data"); le32(UInt32(count * 2))

            for index in 0..<count {
                let amplitude = FindPhoneTone.sample(at: Double(index) / Double(sampleRate))
                let sample = Int16((amplitude * Double(Int16.max)).rounded())
                le16(UInt16(bitPattern: sample))
            }
            // The file must stay readable while the phone is locked, or iOS can't play it.
            try audio.write(to: destination, options: .atomic)
            try fm.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: destination.path)
        } catch {
        }
    }
}
