package com.robiem.narahem.data

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.account.RememberedSession
import com.robiem.narahem.data.account.RememberedSessionStore
import com.robiem.narahem.data.settings.MapCamera
import com.robiem.narahem.data.settings.PhoneAppSettings
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/** Keystore-sealed storage and plain phone settings. */
@RunWith(AndroidJUnit4::class)
class PhoneStorageTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()

    @Before fun setUp() = FakeAndroidKeyStore.install()

    @Test fun sealedDataOpensOnlyUnderItsOwnAliasAndKey() {
        val box = KeystoreBox("test.alias")
        val sealed = box.seal("secret".toByteArray())
        assertFalse(sealed.contains("secret"))
        assertArrayEquals("secret".toByteArray(), box.open(sealed))
        assertTrue(box.seal("secret".toByteArray()) != sealed)
        assertThrows(Exception::class.java) { KeystoreBox("other.alias").open(sealed) }
        FakeAndroidKeyStore.keys.clear()
        assertThrows(Exception::class.java) { box.open(sealed) }
    }

    @Test fun rememberedSessionSurvivesUntilClearedOrUnreadable() {
        val store = RememberedSessionStore(context)
        assertNull(store.read())
        store.write(RememberedSession("https://family.example", "refresh-token"))
        assertEquals(RememberedSession("https://family.example", "refresh-token"), store.read())
        store.clear()
        assertNull(store.read())
        store.write(RememberedSession("https://family.example", "refresh-token"))
        FakeAndroidKeyStore.keys.clear()
        assertNull(store.read())
        assertFalse(
            context.getSharedPreferences("session.v1", Context.MODE_PRIVATE).contains("wrapped")
        )
    }

    @Test fun phoneSettingsAreStoredUnderTheirOriginalKeys() {
        val settings = PhoneAppSettings(context)
        assertEquals("", settings.serverUrl)
        assertNull(settings.mapCamera)
        settings.serverUrl = "https://family.example"
        settings.mapConsent = true
        settings.addressLookup = false // there's no setting any more: addresses are always on
        settings.locationPrompted = true
        settings.mapCamera = MapCamera(1.5, 2.5, 12.0)
        val again = PhoneAppSettings(context)
        assertEquals("https://family.example", again.serverUrl)
        assertTrue(again.mapConsent && again.addressLookup && again.locationPrompted)
        assertEquals(MapCamera(1.5, 2.5, 12.0), again.mapCamera)
        val prefs = context.getSharedPreferences("server", Context.MODE_PRIVATE)
        assertEquals("https://family.example", prefs.getString("url", null))
        prefs.edit().remove("map_zoom").commit()
        assertEquals(PhoneAppSettings.DEFAULT_ZOOM, again.mapCamera!!.zoom, 0.0)
        again.mapCamera = null
        assertNull(again.mapCamera)
    }
}
