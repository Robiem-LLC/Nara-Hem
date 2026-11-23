package com.robiem.narahem.ui.components

/**
 * Returns the letters shown for someone without a profile photo: the first letter of each word of
 * their name, so "John Doe" is "JD" and "Kim" is "K". Same rule as the iPhone and web apps.
 */
fun initials(name: String): String =
    name.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.take(2)
        .joinToString("") { it.take(1) }.uppercase().ifEmpty { "?" }
