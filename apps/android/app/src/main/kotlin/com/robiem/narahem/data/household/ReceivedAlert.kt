package com.robiem.narahem.data.household

/** An arrival or departure alert from the server, with its display text. */
data class ReceivedAlert(
    val eventId: String,
    val accountId: String,
    val capturedAt: Long,
    val text: String
)
