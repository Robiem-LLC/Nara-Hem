package com.robiem.narahem.data.account

import android.content.Context
import com.robiem.narahem.data.KeystoreBox
import org.json.JSONObject

/** Stores the [RememberedSession] in SharedPreferences, encrypted with its own Keystore key. */
internal class RememberedSessionStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(
        "session.v1",
        Context.MODE_PRIVATE
    )

    private val box = KeystoreBox("narahem.native.session.v1")

    /** Returns the stored session, or null if there is none or it can no longer be decrypted. */
    fun read(): RememberedSession? {
        val wrapped = prefs.getString("wrapped", null) ?: return null
        return try {
            val payload = JSONObject(String(box.open(wrapped), Charsets.UTF_8))
            RememberedSession(payload.getString("server"), payload.getString("refresh_token"))
        } catch (_: Exception) {
            clear()
            null
        }
    }

    /**
     * Encrypts and stores the session. Uses commit() so a rotated refresh token isn't lost if the
     * process dies.
     */
    fun write(session: RememberedSession) {
        val payload = JSONObject().put("server", session.server)
            .put("refresh_token", session.refreshToken)
        val sealed = box.seal(payload.toString().toByteArray(Charsets.UTF_8))
        // commit(), not apply(): a rotated refresh token must not be lost if the process dies.
        check(prefs.edit().putString("wrapped", sealed).commit()) {
            "Unable to remember sign-in securely"
        }
    }

    /** Deletes the stored session. */
    fun clear() {
        prefs.edit().clear().commit()
    }
}
