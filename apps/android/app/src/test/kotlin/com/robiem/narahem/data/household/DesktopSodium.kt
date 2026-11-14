package com.robiem.narahem.data.household

import java.io.File
import java.nio.file.Files

/**
 * Makes the app's `SodiumAndroid()` work in JVM tests by pointing JNA at the desktop libsodium that
 * lazysodium-java bundles for this machine's OS and CPU.
 */
internal object DesktopSodium {
    private val installed by lazy {
        val os = System.getProperty("os.name").lowercase()
        val arm = System.getProperty("os.arch").let { it == "aarch64" || it == "arm64" }
        val resource = when {
            "mac" in os -> if (arm) "mac_arm/libsodium.dylib" else "mac/libsodium.dylib"
            "win" in os -> "windows64/libsodium.dll"
            else -> if (arm) "arm64/libsodium.so" else "linux64/libsodium.so"
        }
        val folder = Files.createTempDirectory("sodium").toFile().apply { deleteOnExit() }
        val target = File(folder, resource.substringAfter('/')).apply { deleteOnExit() }
        val stream = checkNotNull(javaClass.classLoader?.getResourceAsStream(resource)) {
            "lazysodium-java has no libsodium for $os"
        }
        stream.use { input -> target.outputStream().use { input.copyTo(it) } }
        System.setProperty("jna.library.path", folder.absolutePath)
    }

    /** Extracts libsodium once per test run; call before the first encryption call. */
    fun install() = installed
}
