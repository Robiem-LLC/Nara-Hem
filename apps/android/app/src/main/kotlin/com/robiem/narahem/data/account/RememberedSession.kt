package com.robiem.narahem.data.account

/** A stored session: the server and its rotating refresh token. Passwords are never stored. */
internal data class RememberedSession(val server: String, val refreshToken: String)
