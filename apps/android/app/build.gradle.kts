import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.gms.google-services")
    id("org.jlleitschuh.gradle.ktlint")
}

ktlint {
    // Rules come from the repository's .editorconfig (Android Studio style, 100 columns).
    version.set("1.8.0")
}

val environment = Properties().apply {
    rootProject.file(".env").takeIf { it.exists() }?.reader()?.use { load(it) }
}
fun setting(name: String): String = (
    providers.environmentVariable(name).orNull
        ?: environment.getProperty(name, "")
    ).trim().removeSurrounding("\"").removeSurrounding("'")
fun literal(value: String) = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
val googleKey = setting("NARAHEM_GOOGLE_MAPS_ANDROID_API_KEY")
val googleEnabled = googleKey.isNotBlank()

// Release builds are signed with Robiem's permanent app-signing key. It is
// never in the repository: CI writes it from GitHub secrets for a release run. Without it, release
// builds stay unsigned, so they can't be mistaken for official ones.
val releaseKeystore = setting("NARAHEM_ANDROID_KEYSTORE")

android {
    namespace = "com.robiem.narahem"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.robiem.narahem"
        minSdk = 26
        targetSdk = 36
        // CI builds use the GitHub run number plus 1000, so the app's "Build" matches the APK file
        // name and every build installs as an update over the pre-release builds, which stayed
        // below 1000. Local builds stay at 17.
        versionCode = System.getenv("GITHUB_RUN_NUMBER")?.toIntOrNull()?.plus(1000) ?: 17
        versionName = setting("NARAHEM_VERSION").ifBlank { "0.6.11" }
        manifestPlaceholders["googleMapsKey"] = googleKey
        buildConfigField(
            "String",
            "MAP_PROVIDER",
            literal(if (googleEnabled) "google" else "openstreetmap")
        )
        buildConfigField(
            "String",
            "BUILD_UTC",
            literal(
                setting("NARAHEM_BUILD_UTC").ifBlank {
                    "Local build"
                }
            )
        )
        buildConfigField(
            "String",
            "BUILD_COMMIT",
            literal(
                setting("NARAHEM_BUILD_COMMIT").ifBlank {
                    "local"
                }
            )
        )
    }
    signingConfigs {
        if (releaseKeystore.isNotBlank()) {
            create("release") {
                storeFile = file(releaseKeystore)
                storePassword = setting("NARAHEM_ANDROID_KEYSTORE_PASSWORD")
                keyAlias = setting("NARAHEM_ANDROID_KEY_ALIAS").ifBlank { "narahem" }
                // A PKCS12 keystore has one password for the store and its key.
                keyPassword = setting("NARAHEM_ANDROID_KEYSTORE_PASSWORD")
            }
        }
    }
    buildTypes {
        getByName("release") {
            if (releaseKeystore.isNotBlank()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
    testOptions {
        // Compose UI tests run on the JVM with Robolectric, so they need the app's resources.
        unitTests.isIncludeAndroidResources = true
    }
    flavorDimensions += "maps"
    productFlavors {
        create("osm") { dimension = "maps" }
        create("google") { dimension = "maps" }
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
androidComponents {
    beforeVariants { variant ->
        variant.enable =
            variant.productFlavors.any { it.second == if (googleEnabled) "google" else "osm" }
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.11.01"))
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("androidx.compose.material:material-icons-extended:1.7.8")
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.1")
    implementation(platform("com.google.firebase:firebase-bom:35.0.2"))
    implementation("com.google.firebase:firebase-messaging")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.11.0")
    implementation("com.goterl:lazysodium-android:5.2.0@aar")
    implementation("net.java.dev.jna:jna:5.19.1@aar")
    "googleImplementation"("com.google.android.gms:play-services-maps:19.2.0")
    "osmImplementation"("org.maplibre.gl:android-sdk:11.13.5")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.17")
    testImplementation(platform("androidx.compose:compose-bom:2025.11.01"))
    testImplementation("androidx.compose.ui:ui-test-junit4")
    // Declares the empty activity createComposeRule() hosts screens in; debug builds only.
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    testImplementation("androidx.test.ext:junit:1.3.0")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.11.0")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.1")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.1")
    testImplementation("org.json:json:20240303")
    // Desktop libsodium and JNA, so the real encryption code runs in JVM tests (see DesktopSodium).
    testImplementation("com.goterl:lazysodium-java:5.2.0")
}

// Robolectric's Android system image is resolved and cached by Gradle like any other dependency,
// and Robolectric runs offline. Its own downloader has no retries, and CI keeps a Gradle cache.
val robolectricAndroid: Configuration by configurations.creating
dependencies {
    // The image Robolectric 4.17 uses for targetSdk 36; update both together.
    robolectricAndroid("org.robolectric:android-all-instrumented:16-robolectric-13921718-2-i7")
}
val robolectricJars = layout.buildDirectory.dir("robolectric-jars")
val copyRobolectricJars by tasks.registering(Copy::class) {
    from(robolectricAndroid)
    into(robolectricJars)
}
tasks.withType<Test>().configureEach {
    dependsOn(copyRobolectricJars)
    systemProperty("robolectric.offline", "true")
    systemProperty("robolectric.dependency.dir", robolectricJars.get().asFile.absolutePath)
    // Robolectric reaches into these JDK internals to emulate Android file descriptors.
    jvmArgs(
        "--add-exports=java.base/jdk.internal.access=ALL-UNNAMED",
        "--add-opens=java.base/java.io=ALL-UNNAMED"
    )
}
