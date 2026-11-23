package com.robiem.narahem.data.account

/** One or two words of letters, numbers, dots, dashes, apostrophes or underscores. */
private val USERNAME = Regex("[\\p{L}\\p{N}_.'-]+( [\\p{L}\\p{N}_.'-]+)?")

/** Shown for a username that isn't allowed. */
const val USERNAME_RULE =
    "Use one or two words: 3–64 letters, numbers, dots, dashes or apostrophes."

/**
 * Returns the username tidied to single spaces if it's one or two words of 3–64 characters, such
 * as "John Doe", otherwise null. Same rule as the server.
 */
fun tidyUsername(value: String): String? {
    val tidy = value.trim().split(Regex("\\s+")).joinToString(" ")
    return tidy.takeIf { it.length in 3..64 && USERNAME.matches(it) }
}
