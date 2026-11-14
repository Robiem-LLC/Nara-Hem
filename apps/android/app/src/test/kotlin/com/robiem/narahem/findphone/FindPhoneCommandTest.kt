package com.robiem.narahem.findphone

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class FindPhoneCommandTest {
    private val signer = FindPhoneSigner("issuer", "owner", "key")

    private fun body() =
        JSONObject().put("domain", "narahem.find-phone.v1").put("household", "household")
            .put(
                "target",
                "phone"
            ).put(
                "issuer",
                "issuer"
            ).put(
                "id",
                "1".repeat(32)
            ).put("action", "ring").put("issued_at", 1000).put("expires_at", 1120)

    private fun check(b: JSONObject, owner: String = "owner", valid: Boolean = true) =
        FindPhoneCommandValidator.validate(
            b,
            "signature",
            "household",
            "phone",
            owner,
            listOf(signer),
            1001
        ) { _, _, _ ->
            valid
        }

    @Test fun acceptsOnlyBoundedTargetedOwnerSignedCommands() {
        assertEquals("ring", check(body()).action)
        assertThrows(IllegalArgumentException::class.java) { check(body().put("target", "other")) }
        assertThrows(IllegalArgumentException::class.java) { check(body().put("expires_at", 999)) }
        assertThrows(IllegalArgumentException::class.java) { check(body().put("expires_at", 1500)) }
        assertThrows(IllegalArgumentException::class.java) { check(body(), valid = false) }
        assertThrows(IllegalStateException::class.java) { check(body(), owner = "other") }
    }

    @Test fun ringCannotReplayAfterAnotherStopCommand() {
        val ring = FindPhoneCommand("ring", "ring", 1120)
        val stop = FindPhoneCommand("stop", "stop", 1130)
        val first = FindPhoneReplay.consume(JSONObject(), ring, 1000)!!
        val second = FindPhoneReplay.consume(first, stop, 1001)!!
        assertNull(FindPhoneReplay.consume(second, ring, 1002))
        assertEquals(
            1,
            FindPhoneReplay.consume(second, FindPhoneCommand("new", "ring", 1250), 1140)!!.length()
        )
    }
}
