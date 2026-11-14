package com.robiem.narahem.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class JoinedMessageTest {
    @Test fun oneMember() = assertEquals(
        "Kim has joined the household. Your location is being shared with them.",
        joinedMessage(listOf("Kim"))
    )

    @Test fun severalMembers() = assertEquals(
        "Kim, Lee and Ari have joined the household. Your location is being shared with them.",
        joinedMessage(listOf("Kim", "Lee", "Ari"))
    )
}
