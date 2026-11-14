package com.robiem.narahem.findphone

import org.json.JSONObject

/** Verifies Find My Phone commands from the server. */
object FindPhoneCommandValidator {
    /**
     * Returns the command if it is signed by an authorized admin device, addressed to this device
     * and household, and not expired. Otherwise returns null.
     */
    fun validate(
        body: JSONObject,
        signature: String,
        household: String,
        target: String,
        owner: String,
        signers: List<FindPhoneSigner>,
        now: Long,
        verify: (JSONObject, String, String) -> Boolean
    ): FindPhoneCommand {
        require(
            body.getString("domain") == "narahem.find-phone.v1" &&
                body.getString("household") == household && body.getString("target") == target
        )
        val signer =
            signers.firstOrNull { it.id == body.getString("issuer") && it.accountId == owner }
                ?: error("Alarm must be signed by an approved owner device")
        require(verify(body, signature, signer.key)) { "Invalid alarm signature" }
        val issued = body.getLong("issued_at")
        val expires = body.getLong("expires_at")
        require(
            issued <= now + 30 && issued >= now - 120 && expires > now &&
                expires - issued in 1L..120L
        )
        val id = body.getString("id")
        val action = body.getString("action")
        require(id.matches(Regex("[a-f0-9]{32}")) && action in listOf("ring", "stop"))
        return FindPhoneCommand(id, action, expires)
    }
}
