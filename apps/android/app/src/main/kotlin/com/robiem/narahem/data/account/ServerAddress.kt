package com.robiem.narahem.data.account

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/**
 * Parses a typed server address into an HTTPS origin. Throws IllegalArgumentException with a
 * user-facing message if it's invalid.
 */
fun serverOrigin(raw: String): HttpUrl {
    // Invitation texts write each dot as <.> so Textbelt doesn't take the address for a link.
    val entered = raw.replace(Regex("\\s*<\\s*\\.\\s*>\\s*"), ".").trim()
    require(entered.isNotEmpty()) {
        "Enter your household server address, for example https://family.example.com."
    }
    val normalized = if ("://" in entered) entered else "https://$entered"
    val url =
        normalized.toHttpUrlOrNull()
            ?: throw IllegalArgumentException("Check the server address and port.")
    require(
        url.isHttps && url.username.isEmpty() && url.password.isEmpty() &&
            url.encodedPath == "/" && url.query == null && url.fragment == null
    ) {
        "Use an HTTPS server address without a path, credentials, query or fragment."
    }
    return url
}

/**
 * The server to prefill on the sign-in form, and an invitation server that must be confirmed before
 * it replaces it.
 */
data class InitialServer(val server: String, val unconfirmedInvite: String? = null)

/**
 * Chooses the starting server. An invitation link may fill an empty field but never replaces a
 * saved server without confirmation, so a crafted link can't redirect a password to another host.
 */
fun initialServer(saved: String, invited: String?): InitialServer {
    if (invited == null) return InitialServer(saved)
    if (saved.isBlank()) return InitialServer(invited)
    val same = runCatching { serverOrigin(saved) == serverOrigin(invited) }.getOrDefault(false)
    return if (same) InitialServer(saved) else InitialServer(saved, invited)
}

/**
 * Same check as [serverOrigin], but throws an [AccountRequestException] tied to the server field.
 */
fun validateServer(server: String) {
    try {
        serverOrigin(server)
    } catch (failure: IllegalArgumentException) {
        throw AccountRequestException(
            0,
            failure.message.orEmpty(),
            mapOf("server" to failure.message.orEmpty())
        )
    }
}
