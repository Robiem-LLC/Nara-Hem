package com.robiem.narahem.findphone

import org.junit.Assert.assertEquals
import org.junit.Test

class FindPhonePollingPolicyTest {
    @Test fun pushWakesRingSoPollingIsOnlyAFallback() {
        assertEquals(60_000L, FindPhonePollingPolicy.interval(enabled = true, connected = true))
    }

    @Test fun disabledFinderOrNoNetworkDoesNotWasteRadioPolling() {
        assertEquals(
            15 * 60_000L,
            FindPhonePollingPolicy.interval(enabled = false, connected = true)
        )
        assertEquals(60_000L, FindPhonePollingPolicy.interval(enabled = true, connected = false))
        assertEquals(60_000L, FindPhonePollingPolicy.interval(enabled = false, connected = false))
    }

    @Test fun failureBackoffPreventsImmediateRetries() {
        assertEquals(60_000L, FindPhonePollingPolicy.ERROR_INTERVAL_MS)
    }
}
