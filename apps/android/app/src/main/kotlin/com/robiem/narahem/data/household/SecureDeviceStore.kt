package com.robiem.narahem.data.household

import android.content.Context
import com.robiem.narahem.data.KeystoreBox
import org.json.JSONObject

/** Stores this phone's [DeviceVault] encrypted with its own Keystore key, excluded from backups. */
internal class SecureDeviceStore(context: Context) {
    private val prefs = context.getSharedPreferences("device.v1", Context.MODE_PRIVATE)
    private val box = KeystoreBox("narahem.native.device.v1")

    /** Returns the server this device is registered with. */
    fun server(): String? = prefs.getString("server", null)

    /** Returns the stored device, decrypted. */
    fun read(): DeviceVault? {
        val value = prefs.getString("wrapped", null) ?: return null
        return DeviceVault.parse(JSONObject(String(box.open(value), Charsets.UTF_8)))
    }

    /**
     * Encrypts and stores the device. The server address is kept readable so the background service
     * can reconnect.
     */
    fun write(vault: DeviceVault, server: String) {
        val sealed = box.seal(HouseholdCrypto.bytes(vault.toJson().toString()))
        prefs.edit().putString("wrapped", sealed).putString("server", server).apply()
    }

    /** Deletes the stored device. */
    fun clear() {
        prefs.edit().clear().apply()
    }
}
