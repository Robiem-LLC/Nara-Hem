package com.robiem.narahem.tracking

import org.junit.Assert.assertEquals
import org.junit.Test

class TrackingResumePolicyTest {
    @Test fun everyRequiredPermissionAndPriorOptInMustRemainEnabled() {
        for (mask in 0..15) {
            assertEquals(
                "permission/consent combination $mask",
                mask == 15,
                TrackingResumePolicy.permits(
                    (mask and 1) != 0,
                    (mask and 2) != 0,
                    (mask and 4) != 0,
                    (mask and 8) != 0
                )
            )
        }
    }
}
