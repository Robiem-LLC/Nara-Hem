package com.robiem.narahem.data.household

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

class HouseholdCryptoTest {
    @Test fun canonicalJsonSortsKeysWithoutEscapingForwardSlashes() {
        val payload = JSONObject()
            .put("z", "//+/base64==")
            .put("nested", JSONObject().put("b", 2).put("a", 1))
            .put("a", "é")
        assertEquals(
            """{"a":"é","nested":{"a":1,"b":2},"z":"//+/base64=="}""",
            CanonicalJson.canonical(payload)
        )
    }

    @Test fun canonicalJsonQuotesControlCharactersAndLeavesUnicodeLiteral() {
        val payload = JSONObject().put("key", "a\nb\t\"\\" + "\u0001" + "😀")
        assertEquals("""{"key":"a\nb\t\"\\\u0001😀"}""", CanonicalJson.canonical(payload))
    }
}
