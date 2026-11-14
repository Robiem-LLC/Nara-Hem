package com.robiem.narahem.findphone

import kotlin.math.abs
import kotlin.math.sqrt
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FindPhoneToneTest {
    private val sampleCount = (FindPhoneTone.CYCLE_SECONDS * FindPhoneTone.SAMPLE_RATE).toInt()

    private val samples = (0 until sampleCount)
        .map { FindPhoneTone.sample(it.toDouble() / FindPhoneTone.SAMPLE_RATE) }

    @Test fun sirenIsLoudButNeverClips() {
        val peak = samples.maxOf { abs(it) }
        assertTrue("Siren plays near full scale", peak > 0.9 && peak <= 1.0)
        assertTrue(
            "Far louder than a gentle chime",
            sqrt(samples.sumOf { it * it } / samples.size) > 0.6
        )
    }

    @Test fun eachCycleEndsInAPauseSoLoopingNeverClicks() {
        assertEquals(0.0, FindPhoneTone.sample(1.25), 0.0)
        assertEquals(0.0, samples.last(), 0.0)
    }

    @Test fun wavHeaderDescribesOneMonoCycle() {
        val wav = FindPhoneTone.wav()
        assertArrayEquals("RIFF".toByteArray(), wav.copyOfRange(0, 4))
        assertArrayEquals("WAVE".toByteArray(), wav.copyOfRange(8, 12))
        assertEquals(44 + samples.size * 2, wav.size)
    }
}
