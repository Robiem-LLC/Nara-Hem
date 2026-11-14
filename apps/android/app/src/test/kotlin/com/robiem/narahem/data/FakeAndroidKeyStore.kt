package com.robiem.narahem.data

import java.io.InputStream
import java.io.OutputStream
import java.security.Key
import java.security.KeyStoreSpi
import java.security.Provider
import java.security.SecureRandom
import java.security.Security
import java.security.cert.Certificate
import java.security.spec.AlgorithmParameterSpec
import java.util.Collections
import java.util.Date
import java.util.Enumeration
import java.util.concurrent.ConcurrentHashMap
import javax.crypto.KeyGeneratorSpi
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

/**
 * An in-memory stand-in for the "AndroidKeyStore" provider, which Robolectric doesn't have. It
 * holds AES keys by alias, so [KeystoreBox] works in JVM tests.
 */
object FakeAndroidKeyStore {
    /** Keys by alias. Tests clear it to simulate a wiped Keystore. */
    val keys = ConcurrentHashMap<String, SecretKey>()

    /** Registers the provider once and starts with no keys. */
    fun install() {
        if (Security.getProvider("AndroidKeyStore") == null) Security.addProvider(Fake())
        keys.clear()
    }

    /** The provider, mapping the Keystore and AES key generator to the classes below. */
    @Suppress("DEPRECATION")
    private class Fake : Provider("AndroidKeyStore", 1.0, "In-memory test Keystore") {
        init {
            put("KeyStore.AndroidKeyStore", Store::class.java.name)
            put("KeyGenerator.AES", Generator::class.java.name)
        }
    }

    /** Reads keys from [keys]; only key lookup is supported. */
    class Store : KeyStoreSpi() {
        override fun engineGetKey(alias: String, password: CharArray?): Key? = keys[alias]
        override fun engineContainsAlias(alias: String) = keys.containsKey(alias)
        override fun engineAliases(): Enumeration<String> = Collections.enumeration(keys.keys)
        override fun engineSize() = keys.size
        override fun engineIsKeyEntry(alias: String) = keys.containsKey(alias)
        override fun engineLoad(stream: InputStream?, password: CharArray?) {}
        override fun engineGetCertificateChain(alias: String): Array<Certificate>? = null
        override fun engineGetCertificate(alias: String): Certificate? = null
        override fun engineGetCreationDate(alias: String): Date? = null
        override fun engineIsCertificateEntry(alias: String) = false
        override fun engineGetCertificateAlias(cert: Certificate): String? = null
        override fun engineStore(stream: OutputStream?, password: CharArray?) {}

        override fun engineDeleteEntry(alias: String) {
            keys.remove(alias)
        }

        override fun engineSetCertificateEntry(alias: String, cert: Certificate) =
            throw UnsupportedOperationException()

        override fun engineSetKeyEntry(
            alias: String,
            key: Key,
            password: CharArray?,
            chain: Array<out Certificate>?
        ) = throw UnsupportedOperationException()

        override fun engineSetKeyEntry(
            alias: String,
            key: ByteArray,
            chain: Array<out Certificate>?
        ) = throw UnsupportedOperationException()
    }

    /** Creates a random 256-bit AES key under the alias named in the KeyGenParameterSpec. */
    class Generator : KeyGeneratorSpi() {
        private var alias = ""

        override fun engineInit(random: SecureRandom?) = throw UnsupportedOperationException()

        override fun engineInit(params: AlgorithmParameterSpec, random: SecureRandom?) {
            alias = params.javaClass.getMethod("getKeystoreAlias").invoke(params) as String
        }

        override fun engineInit(keysize: Int, random: SecureRandom?) =
            throw UnsupportedOperationException()

        override fun engineGenerateKey(): SecretKey {
            val key = SecretKeySpec(ByteArray(32).also { SecureRandom().nextBytes(it) }, "AES")
            keys[alias] = key
            return key
        }
    }
}
