package com.robiem.narahem.ui

/** Returns the message shown when members join, e.g. "Kim has joined the household. …". */
internal fun joinedMessage(names: List<String>): String {
    val who = when (names.size) {
        1 -> names[0] + " has"
        else -> names.dropLast(1).joinToString(", ") + " and " + names.last() + " have"
    }
    return "$who joined the household. Your location is being shared with them."
}
