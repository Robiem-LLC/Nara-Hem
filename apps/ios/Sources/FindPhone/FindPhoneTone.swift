import Foundation

/// Generates the Find My Phone siren: eight 0.15 s beeps alternating between 2.9 and 3.5 kHz, then
/// a 0.1 s pause. Same as Android.
enum FindPhoneTone {
    static let cycle = 1.3
    private static let beep = 0.15
    private static let gain = 0.95 / 0.9334

    /// Returns the siren's amplitude at the given time, between -1 and 1.
    static func sample(at time: Double) -> Double {
        let position = time.truncatingRemainder(dividingBy: cycle)
        guard position < 1.2 else { return 0 }
        let pitch: Double = Int(position / beep) % 2 == 0 ? 2_900 : 3_500
        let local = position.truncatingRemainder(dividingBy: beep)
        let edge = min(1, local * 400, (beep - local) * 400)
        var wave = 0.0
        var harmonic = 1.0
        while pitch * harmonic < 20_000 {
            wave += sin(2 * Double.pi * pitch * harmonic * time) / harmonic
            harmonic += 2
        }
        return max(-1, min(1, gain * edge * wave))
    }
}
