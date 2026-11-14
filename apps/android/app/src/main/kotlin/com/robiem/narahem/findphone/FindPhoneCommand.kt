package com.robiem.narahem.findphone

/** A verified ring or stop command: its ID, action and expiry time. */
data class FindPhoneCommand(val id: String, val action: String, val expiresAt: Long)
