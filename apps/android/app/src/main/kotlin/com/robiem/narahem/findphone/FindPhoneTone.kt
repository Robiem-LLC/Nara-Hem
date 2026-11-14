package com.robiem.narahem.findphone

import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * Generates the Find My Phone siren, the same as the iPhone's: eight 0.15 s beeps alternating
 * between 2.9 and 3.5 kHz, then a 0.1 s pause.
 */
object FindPhoneTone {
    /** Samples per second. */
    const val SAMPLE_RATE = 44_100

    /** Length of one siren cycle. */
    const val CYCLE_SECONDS = 1.3

    /** Length of one beep. */
    private const val BEEP_SECONDS = 0.15
    private const val GAIN = 0.95 / 0.9334

    /** Returns the siren's amplitude at [time] seconds, between -1 and 1. */
    fun sample(time: Double): Double {
        val position = time % CYCLE_SECONDS
        if (position >= 1.2) return 0.0
        val pitch = if ((position / BEEP_SECONDS).toInt() % 2 == 0) 2_900.0 else 3_500.0
        val local = position % BEEP_SECONDS
        val edge = min(1.0, min(local * 400, (BEEP_SECONDS - local) * 400))
        var wave = 0.0
        var harmonic = 1.0
        while (pitch * harmonic < 20_000) {
            wave += sin(2 * PI * pitch * harmonic * time) / harmonic
            harmonic += 2
        }
        return (GAIN * edge * wave).coerceIn(-1.0, 1.0)
    }

    /** Returns one siren cycle as a 16-bit mono WAV file, for looping playback. */
    fun wav(): ByteArray {
        val count = (CYCLE_SECONDS * SAMPLE_RATE).toInt()
        val buffer = ByteBuffer.allocate(44 + count * 2).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put("RIFF".toByteArray()).putInt(36 + count * 2).put("WAVE".toByteArray())
        buffer.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1)
            .putInt(SAMPLE_RATE).putInt(SAMPLE_RATE * 2).putShort(2).putShort(16)
        buffer.put("data".toByteArray()).putInt(count * 2)
        for (index in 0 until count) {
            buffer.putShort(
                (sample(index.toDouble() / SAMPLE_RATE) * Short.MAX_VALUE).roundToInt().toShort()
            )
        }
        return buffer.array()
    }
}
