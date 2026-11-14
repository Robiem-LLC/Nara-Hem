package com.robiem.narahem.ui.settings

import android.app.Application
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.ui.map.AvatarFan
import java.io.File
import kotlin.random.Random
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.GraphicsMode

/** Profile photo encoding and the round map markers, using Robolectric's real graphics. */
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ProfilePhotosTest {
    private val context: Application get() = ApplicationProvider.getApplicationContext()

    /** A wide photo full of noise, which compresses badly, like a real camera picture. */
    private fun noisyPhoto(width: Int = 400, height: Int = 300): Bitmap {
        val random = Random(7)
        val pixels =
            IntArray(width * height) {
                Color.rgb(random.nextInt(256), random.nextInt(256), random.nextInt(256))
            }
        return Bitmap.createBitmap(pixels, width, height, Bitmap.Config.ARGB_8888)
    }

    @Test fun photosAreCroppedSquareAndKeptSmall() {
        val uri = ProfilePhotos.encode(noisyPhoto())
        assertTrue(uri.startsWith("data:image/jpeg;base64,"))
        assertTrue(uri.length <= 14_500)
        val decoded = ProfilePhotos.bitmap(uri)!!
        assertEquals(decoded.width, decoded.height)
        assertTrue(decoded.width in 80..128)
    }

    @Test fun galleryImagesAreReadThroughTheContentResolver() {
        val file = File(context.cacheDir, "picked.jpg")
        file.outputStream().use {
            noisyPhoto(1200, 900).compress(Bitmap.CompressFormat.JPEG, 90, it)
        }
        val uri = ProfilePhotos.fromGallery(context, Uri.fromFile(file))
        assertTrue(ProfilePhotos.bitmap(uri) != null)
        val text = File(context.cacheDir, "notes.txt").apply { writeText("not an image") }
        assertThrows(IllegalArgumentException::class.java) {
            ProfilePhotos.fromGallery(context, Uri.fromFile(text))
        }
    }

    @Test fun receivedPhotosThatAreWrongOrTooLargeAreIgnored() {
        assertNull(ProfilePhotos.bitmap(null))
        assertNull(ProfilePhotos.bitmap("data:image/png;base64,AAAA"))
        assertNull(ProfilePhotos.bitmap("data:image/jpeg;base64," + "A".repeat(15_000)))
        assertNull(ProfilePhotos.bitmap("data:image/jpeg;base64,***"))
    }

    @Test fun markersAreRoundWithAnInitialOrThePhoto() {
        val marker = ProfilePhotos.initialsMarker(" kim ")
        assertEquals(ProfilePhotos.MARKER_PIXELS, marker.width)
        assertEquals(Color.TRANSPARENT, marker.getPixel(0, 0))
        assertNotEquals(Color.TRANSPARENT, marker.getPixel(48, 4))
        val stale = ProfilePhotos.initialsMarker("", stale = true)
        assertNotEquals(marker.getPixel(48, 2), stale.getPixel(48, 2))
        assertNull(ProfilePhotos.roundMarker(null))
        val photo = ProfilePhotos.roundMarker(
            ProfilePhotos.encode(noisyPhoto()),
            64,
            stale = true
        )!!
        assertEquals(64, photo.width)
        assertEquals(Color.TRANSPARENT, photo.getPixel(0, 0))
    }

    @Test fun fannedMarkersGrowToKeepTheirAnchor() {
        val marker = ProfilePhotos.initialsMarker("A")
        assertSame(marker, ProfilePhotos.fanned(marker, null))
        assertSame(marker, ProfilePhotos.fanned(marker, AvatarFan.Offset(0, 0)))
        val moved = ProfilePhotos.fanned(marker, AvatarFan.Offset(-10, -20))
        assertEquals(marker.width + 20, moved.width)
        assertEquals(marker.height + 20, moved.height)
    }
}
