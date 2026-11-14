package com.robiem.narahem.data

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject

/**
 * Encrypts small secrets with an AES-GCM key held in the Android Keystore. Each alias has its own
 * key and is used as additional authenticated data, so data sealed under one alias can't be opened
 * under another.
 */
internal class KeystoreBox(private val alias: String) {
    /** Encodes bytes as base64 without line breaks. */
    private fun encode(raw: ByteArray) = Base64.encodeToString(raw, Base64.NO_WRAP)

    /** Decodes base64 to bytes. */
    private fun decode(raw: String) = Base64.decode(raw, Base64.DEFAULT)

    /**
     * Encrypts the bytes and returns JSON containing the base64 nonce ("iv") and ciphertext
     * ("box").
     */
    fun seal(plain: ByteArray): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD(alias.toByteArray(Charsets.UTF_8))
        return JSONObject()
            .put("iv", encode(cipher.iv))
            .put("box", encode(cipher.doFinal(plain)))
            .toString()
    }

    /**
     * Decrypts data produced by [seal]. Throws if the key no longer exists or the data was
     * modified.
     */
    fun open(sealed: String): ByteArray {
        val parts = JSONObject(sealed)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(
            Cipher.DECRYPT_MODE,
            key(),
            GCMParameterSpec(128, decode(parts.getString("iv")))
        )
        cipher.updateAAD(alias.toByteArray(Charsets.UTF_8))
        return cipher.doFinal(decode(parts.getString("box")))
    }

    /** Returns the Keystore key for this alias, creating it on first use. */
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                alias,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return generator.generateKey()
    }

    /** Cipher settings. */
    private companion object {
        const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}
