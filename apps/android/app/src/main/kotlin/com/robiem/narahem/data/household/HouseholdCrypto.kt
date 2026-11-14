package com.robiem.narahem.data.household

import android.util.Base64
import com.goterl.lazysodium.SodiumAndroid
import java.security.MessageDigest
import java.security.SecureRandom
import org.json.JSONObject

/**
 * Libsodium operations used by the household protocol: Ed25519 signatures, sealed boxes, SHA-256
 * and random IDs.
 */
internal object HouseholdCrypto {
    private val sodium by lazy { SodiumAndroid() }

    /** Returns the UTF-8 bytes of a string. */
    fun bytes(text: String) = text.toByteArray(Charsets.UTF_8)

    /** Encodes bytes as standard base64. */
    fun b64(data: ByteArray): String = Base64.encodeToString(data, Base64.NO_WRAP)

    /** Decodes standard base64. */
    fun unb64(data: String): ByteArray = Base64.decode(data, Base64.DEFAULT)

    /** Encodes bytes as lowercase hex. */
    fun hex(data: ByteArray): String = data.joinToString("") { "%02x".format(it.toInt() and 255) }

    /** Returns a random 128-bit ID as 32 hex characters. */
    fun randomId(): String = ByteArray(16).also { SecureRandom().nextBytes(it) }.let(::hex)

    /** Returns the SHA-256 digest as hex. */
    fun sha(data: ByteArray): String = hex(MessageDigest.getInstance("SHA-256").digest(data))

    /** Returns the SHA-256 digest of a string's UTF-8 bytes as hex. */
    fun hashString(text: String) = sha(bytes(text))

    /** Serializes a value as canonical JSON; see [CanonicalJson]. */
    fun canonical(value: Any?): String = CanonicalJson.canonical(value)

    /** Throws if a libsodium call returned a non-zero status. */
    private fun check(code: Int) {
        if (code != 0) throw SecurityException("Native encryption operation failed")
    }

    /** Generates an Ed25519 signing key pair. */
    fun signingKeys(): KeyPair {
        val public = ByteArray(32)
        val private = ByteArray(64)
        check(sodium.crypto_sign_keypair(public, private))
        return KeyPair(b64(public), b64(private))
    }

    /** Generates an X25519 key pair for sealed boxes. */
    fun boxKeys(): KeyPair {
        val public = ByteArray(32)
        val private = ByteArray(32)
        check(sodium.crypto_box_keypair(public, private))
        return KeyPair(b64(public), b64(private))
    }

    /** Returns a detached Ed25519 signature over the canonical JSON of [body]. */
    fun sign(body: JSONObject, privateKey: String): String {
        val msg = bytes(canonical(body))
        val signature = ByteArray(64)
        check(
            sodium.crypto_sign_detached(signature, null, msg, msg.size.toLong(), unb64(privateKey))
        )
        return b64(signature)
    }

    /**
     * Verifies a detached signature over the canonical JSON of [body]. Returns false on any error
     * instead of throwing.
     */
    fun verify(body: JSONObject, signature: String, publicKey: String): Boolean {
        val msg = bytes(canonical(body))
        return try {
            sodium.crypto_sign_verify_detached(
                unb64(signature),
                msg,
                msg.size.toLong(),
                unb64(publicKey)
            ) ==
                0
        } catch (_: Exception) {
            false
        }
    }

    /** Encrypts the canonical JSON of [body] as a sealed box for the given public key. */
    fun seal(body: JSONObject, publicKey: String): String {
        val msg = bytes(canonical(body))
        val sealed = ByteArray(msg.size + 48)
        check(sodium.crypto_box_seal(sealed, msg, msg.size.toLong(), unb64(publicKey)))
        return b64(sealed)
    }

    /** Decrypts a sealed box addressed to this key pair and parses the JSON inside. */
    fun open(ciphertext: String, publicKey: String, privateKey: String): JSONObject {
        val sealed = unb64(ciphertext)
        require(sealed.size >= 48) { "Invalid encrypted record" }
        val plain = ByteArray(sealed.size - 48)
        check(
            sodium.crypto_box_seal_open(
                plain,
                sealed,
                sealed.size.toLong(),
                unb64(publicKey),
                unb64(privateKey)
            )
        )
        return JSONObject(String(plain, Charsets.UTF_8))
    }

    /** A public and private key, both base64. */
    data class KeyPair(val publicKey: String, val privateKey: String)
}
