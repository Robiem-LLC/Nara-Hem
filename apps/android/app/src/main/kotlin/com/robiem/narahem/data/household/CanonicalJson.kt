package com.robiem.narahem.data.household

import org.json.JSONArray
import org.json.JSONObject

/**
 * Serializes JSON the same way as the server and the other apps, so signatures match byte for byte.
 */
internal object CanonicalJson {
    /**
     * Escapes a string as a JSON literal. Escaping is fixed across Android versions, and '/' is
     * never escaped.
     */
    private fun quoteJson(value: String): String = buildString {
        append('"')
        value.forEach { char ->
            when (char) {
                '"' -> append("\\\"")
                '\\' -> append("\\\\")
                '\b' -> append("\\b")
                '\u000C' -> append("\\f")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> if (char.code < 32) append("\\u%04x".format(char.code)) else append(char)
            }
        }
        append('"')
    }

    /**
     * Serializes a value with object keys sorted at every level and array order kept, matching
     * Python's json.dumps(sort_keys=True, separators=(",", ":")).
     */
    fun canonical(value: Any?): String = when (value) {
        null, JSONObject.NULL -> "null"

        is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",", "{", "}") {
            quoteJson(it) + ":" + canonical(value.get(it))
        }

        is JSONArray -> (0 until value.length()).joinToString(",", "[", "]") {
            canonical(value.get(it))
        }

        is String -> quoteJson(value)

        is Number, is Boolean -> value.toString()

        else -> error("Unsupported signed JSON value")
    }
}
