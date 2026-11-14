import AVFoundation
import AudioToolbox
import Foundation
import UIKit
import UserNotifications

// PARKED: kept for a possible future version. Nothing in the app calls it; iPhones only get
// the Find My Phone push notification sound.

/// In-app Find My Phone alarm. Not used (see the PARKED note above).
@MainActor
final class FindPhoneAlarm {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var autoStop: Task<Void, Never>?
    private var systemAlarmStop: (() -> Void)?
    private(set) var commandId: String?
    var onStopped: ((String, String) -> Void)?

    /// Configures the audio session.
    init() {
        engine.attach(player)
        let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1)!
        engine.connect(player, to: engine.mainMixerNode, format: format)
        NotificationCenter.default.addObserver(
            forName: .narahemAlarmStop, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in self?.stop("user_stopped") }
        }
    }

    /// Plays the alarm until stopped or the command expires.
    func ring(command: String, expires: Int) async throws {
        stop("remote_stop")
        let remaining = max(1, min(60, expires - Wire.timestamp()))

        // The signed Find My Phone inbox has already been verified by the
        // caller; never trigger this path directly from an APNs payload.
        if #available(iOS 26.0, *) {
            let system = SystemFindPhoneAlarm()
            if SystemFindPhoneEligibility.canSchedule(
                optedIn: UserDefaults.standard.bool(
                    forKey: SystemFindPhoneEligibility.preferenceKey),
                authorized: system.authorized, commandExpires: expires,
                now: Wire.timestamp())
            {
                do {
                    try await system.ring(expires: expires)
                    systemAlarmStop = { system.stop() }
                    commandId = command
                    scheduleAutoStop(seconds: remaining)
                    return
                } catch {
                }
            }
        }
        try ringAudio(command: command, remaining: remaining)
    }

    /// Plays the siren on a loop.
    private func ringAudio(command: String, remaining: Int) throws {
        let audio = AVAudioSession.sharedInstance()
        try audio.setCategory(.playback, mode: .default, options: [.duckOthers])
        try audio.setActive(true)
        let frames = AVAudioFrameCount(FindPhoneTone.cycle * 44_100)
        guard let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1),
            let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames),
            let samples = buffer.floatChannelData?[0]
        else {
            throw NaraHemProtocolError.rejected("Unable to initialize iPhone alarm")
        }
        buffer.frameLength = frames
        for i in 0..<Int(frames) {
            samples[i] = Float(FindPhoneTone.sample(at: Double(i) / 44_100))
        }
        player.scheduleBuffer(buffer, at: nil, options: [.loops])
        try engine.start()
        player.play()
        commandId = command
        AudioServicesPlaySystemSound(kSystemSoundID_Vibrate)
        let content = UNMutableNotificationContent()
        content.title = "Find my phone"
        content.body = "Open Nära Hem or tap Stop to silence the alarm."
        content.sound = nil
        content.categoryIdentifier = "narahem-find-phone"
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(
                identifier: "narahem-find-active",
                content: content, trigger: nil))
        scheduleAutoStop(seconds: remaining)
    }

    /// Stops the alarm after the given number of seconds.
    private func scheduleAutoStop(seconds: Int) {
        autoStop = Task { [weak self] in
            try? await Task.sleep(for: .seconds(seconds))
            guard !Task.isCancelled else { return }
            self?.stop("timeout")
        }
    }

    /// Stops the alarm.
    func stop(_ reason: String) {
        autoStop?.cancel()
        autoStop = nil
        systemAlarmStop?()
        systemAlarmStop = nil
        if player.isPlaying { player.stop() }
        engine.stop()
        try? AVAudioSession.sharedInstance().setActive(
            false, options: [.notifyOthersOnDeactivation])
        UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: [
            "narahem-find-active"
        ])
        if let id = commandId {
            commandId = nil
            onStopped?(id, reason)
        }
    }
}

/// Posted to stop the alarm.
extension Notification.Name {
    static let narahemAlarmStop = Notification.Name("narahem.alarm.stop")
}
