package com.robiem.narahem.data.household

import org.json.JSONArray
import org.json.JSONObject

/**
 * This phone's household identity: signing and encryption keys, device credential, household ID and
 * the last verified roster revision. Stored encrypted by [SecureDeviceStore].
 */
internal data class DeviceVault(
    val id: String,
    val accountId: String,
    val household: String,
    val signingPublic: String,
    val signingPrivate: String,
    val boxPublic: String,
    val boxPrivate: String,
    var credential: String,
    var anchor: String = "",
    var revision: Int = 0,
    var chainHash: String = "",
    var sequence: Long = 0,
    var audienceIds: Set<String>? = null,
    var registrationPlatform: String? = null,
    /** Members this phone has already seen, so it can tell when someone new joins. */
    var knownMembers: Set<String>? = null
) {
    /** Returns this device's public roster entry: ID, account ID and public keys. */
    fun identity(): JSONObject = JSONObject()
        .put("id", id).put("account_id", accountId)
        .put("signing_key", signingPublic).put("box_key", boxPublic)

    /** Serializes every field, including private keys. Only ever stored encrypted. */
    fun toJson() = JSONObject()
        .put("id", id).put("accountId", accountId).put("household", household)
        .put("signingPublic", signingPublic).put("signingPrivate", signingPrivate)
        .put("boxPublic", boxPublic).put("boxPrivate", boxPrivate)
        .put("credential", credential).put("anchor", anchor)
        .put("revision", revision).put("chainHash", chainHash).put("sequence", sequence)
        .put("registrationPlatform", registrationPlatform ?: JSONObject.NULL)
        .put("audienceIds", idArray(audienceIds))
        .put("knownMembers", idArray(knownMembers))

    /** Parsing. */
    companion object {
        /** Rebuilds a vault from [toJson] output. */
        fun parse(j: JSONObject) = DeviceVault(
            j.getString("id"), j.getString("accountId"), j.getString("household"),
            j.getString("signingPublic"), j.getString("signingPrivate"),
            j.getString("boxPublic"), j.getString("boxPrivate"), j.getString("credential"),
            j.optString("anchor"),
            j.optInt("revision"), j.optString("chainHash"), j.optLong("sequence"),
            idSet(j.optJSONArray("audienceIds")),
            j.optString("registrationPlatform").takeIf { it == "android" },
            idSet(j.optJSONArray("knownMembers"))
        )

        /** Returns a sorted JSON array of IDs, or JSON null. */
        private fun idArray(ids: Set<String>?): Any =
            ids?.let { JSONArray().also { array -> it.sorted().forEach { id -> array.put(id) } } }
                ?: JSONObject.NULL

        /** Returns the IDs in a JSON array, or null when the array is missing. */
        private fun idSet(values: JSONArray?): Set<String>? =
            values?.let { (0 until it.length()).map { index -> it.getString(index) }.toSet() }
    }
}
