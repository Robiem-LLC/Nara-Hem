package com.robiem.narahem.findphone

import org.json.JSONObject

/** Tracks used command IDs until they expire, so a replayed command can't ring again. */
object FindPhoneReplay {
    /**
     * Returns the updated set of used IDs with [command] added and expired ones removed, or null if
     * [command] was already used.
     */
    fun consume(previous: JSONObject, command: FindPhoneCommand, now: Long): JSONObject? {
        val retained = JSONObject()
        previous.keys().forEach { id ->
            if (previous.getLong(id) > now) retained.put(id, previous.getLong(id))
        }
        if (retained.has(command.id)) return null
        require(retained.length() < 128) { "Too many recent alarm commands" }
        retained.put(command.id, command.expiresAt)
        return retained
    }
}
