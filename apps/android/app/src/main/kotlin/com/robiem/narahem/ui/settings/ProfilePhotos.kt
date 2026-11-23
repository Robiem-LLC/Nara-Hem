package com.robiem.narahem.ui.settings

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.net.Uri
import android.util.Base64
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.robiem.narahem.ui.components.initials
import com.robiem.narahem.ui.map.AvatarFan
import com.robiem.narahem.ui.theme.NaraHemColors
import java.io.ByteArrayOutputStream

/**
 * Creates, decodes and draws profile photos. Photos are small, square JPEGs cropped on the device
 * and shared as data URIs inside encrypted profile records.
 */
object ProfilePhotos {
    /** Data URI prefix for profile photos. */
    private const val PREFIX = "data:image/jpeg;base64,"

    /** Maximum size of a photo this app publishes. */
    private const val MAX_JPEG_BYTES = 8_500

    /** Maximum size of a received photo; larger ones are ignored. */
    private const val MAX_RECEIVED_JPEG_BYTES = 11_000

    /** Width and height of profile photos and map markers. */
    const val MARKER_PIXELS = 96

    /** Loads an image from [uri], crops and scales it, and returns a JPEG data URI. */
    fun fromGallery(context: Context, uri: Uri): String {
        val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        val probe =
            context.contentResolver.openInputStream(uri) ?: error("Unable to open selected image")
        probe.use { BitmapFactory.decodeStream(it, null, options) }
        require(options.outWidth > 0 && options.outHeight > 0) { "Not a readable image" }
        val max = maxOf(options.outHeight, options.outWidth)
        var sample = 1
        while (max / sample > 512) sample *= 2
        val decoded = context.contentResolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(
                it,
                null,
                BitmapFactory.Options().apply {
                    inSampleSize = sample
                }
            )
        } ?: error("Unable to open the selected photo")
        return encode(decoded)
    }

    /**
     * Crops a bitmap to a centred square, scales it and compresses it to a JPEG data URI under
     * [MAX_JPEG_BYTES].
     */
    fun encode(source: Bitmap): String {
        val square = minOf(source.width, source.height)
        require(square > 0) { "Empty photo" }
        for (side in listOf(128, 112, 96, 80)) {
            val scaled = Bitmap.createBitmap(side, side, Bitmap.Config.ARGB_8888)
            Canvas(scaled).drawBitmap(
                source,
                Rect(
                    (source.width - square) / 2,
                    (source.height - square) / 2,
                    (source.width + square) / 2,
                    (source.height + square) / 2
                ),
                Rect(0, 0, side, side),
                Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
            )
            for (quality in listOf(82, 70, 58, 45)) {
                val stream = ByteArrayOutputStream()
                check(scaled.compress(Bitmap.CompressFormat.JPEG, quality, stream)) {
                    "Cannot save profile photo"
                }
                val bytes = stream.toByteArray()
                if (bytes.size <= MAX_JPEG_BYTES) {
                    return PREFIX + Base64.encodeToString(bytes, Base64.NO_WRAP)
                }
            }
        }
        error("This image cannot be compressed safely; please select another.")
    }

    /** Decodes a profile photo data URI. Returns null if it is missing, too large or invalid. */
    fun bitmap(dataUri: String?): Bitmap? {
        if (dataUri == null || !dataUri.startsWith(PREFIX) || dataUri.length > 14500) return null
        return try {
            val raw = Base64.decode(dataUri.removePrefix(PREFIX), Base64.NO_WRAP)
            if (raw.size > MAX_RECEIVED_JPEG_BYTES) {
                null
            } else {
                BitmapFactory.decodeByteArray(raw, 0, raw.size)
            }
        } catch (_: Exception) {
            null
        }
    }

    /** Draws a round marker with the member's initials, for members without a photo. */
    fun initialsMarker(name: String, pixels: Int = MARKER_PIXELS, stale: Boolean = false): Bitmap {
        val output = Bitmap.createBitmap(pixels, pixels, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(output)
        val center = pixels / 2f
        canvas.drawCircle(
            center,
            center,
            center,
            Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color =
                    if (stale) NaraHemColors.Danger.toArgb() else NaraHemColors.White.toArgb()
            }
        )
        canvas.drawCircle(
            center,
            center,
            center - pixels * .09f,
            Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = NaraHemColors.PanelRaised.toArgb()
            }
        )
        val letters = initials(name)
        val text = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = NaraHemColors.White.toArgb()
            textSize = pixels * if (letters.length > 1) .36f else .44f
            textAlign = Paint.Align.CENTER
            typeface = android.graphics.Typeface.DEFAULT_BOLD
        }
        canvas.drawText(letters, center, center - (text.ascent() + text.descent()) / 2, text)
        return output
    }

    /**
     * Places a marker inside a larger transparent bitmap, shifted by the fan offset. Both map
     * providers anchor markers at the bottom centre, so the marked location doesn't move.
     */
    fun fanned(marker: Bitmap, offset: AvatarFan.Offset?): Bitmap {
        if (offset == null || (offset.dx == 0 && offset.dy == 0)) return marker
        val padX = kotlin.math.abs(offset.dx)
        val rise = -minOf(0, offset.dy)
        val output = Bitmap.createBitmap(
            marker.width + 2 * padX,
            marker.height + rise,
            Bitmap.Config.ARGB_8888
        )
        Canvas(output).drawBitmap(marker, (padX + offset.dx).toFloat(), 0f, null)
        return output
    }

    /** Draws a round avatar marker from a photo or initial, for either map provider. */
    fun roundMarker(
        dataUri: String?,
        pixels: Int = MARKER_PIXELS,
        stale: Boolean = false
    ): Bitmap? {
        val photo = bitmap(dataUri) ?: return null
        val output = Bitmap.createBitmap(pixels, pixels, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(output)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
        val border = pixels * .06f
        val diameter = pixels.toFloat()
        canvas.drawCircle(
            diameter / 2,
            diameter / 2,
            diameter / 2,
            Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color =
                    if (stale) NaraHemColors.Danger.toArgb() else NaraHemColors.White.toArgb()
            }
        )
        canvas.save()
        val margin = border * 1.5f
        val crop = minOf(photo.width, photo.height)
        val left = (photo.width - crop) / 2
        val top = (photo.height - crop) / 2
        val dest = RectF(margin, margin, diameter - margin, diameter - margin)
        val clip = android.graphics.Path().apply {
            addOval(dest, android.graphics.Path.Direction.CW)
        }
        canvas.clipPath(clip)
        canvas.drawBitmap(photo, Rect(left, top, left + crop, top + crop), dest, paint)
        canvas.restore()
        return output
    }
}

/** Shows a member's photo in a circle, or their initials if they have no photo. */
@Composable
fun RoundProfilePhoto(photo: String?, name: String, size: Dp = 46.dp) {
    val bitmap = remember(photo) { ProfilePhotos.bitmap(photo)?.asImageBitmap() }
    if (bitmap == null) {
        Box(
            Modifier.size(
                size
            ).clip(CircleShape).background(MaterialTheme.colorScheme.primaryContainer),
            contentAlignment = Alignment.Center
        ) {
            Text(initials(name))
        }
    } else {
        Image(
            bitmap,
            contentDescription = "Photo of $name",
            modifier = Modifier.size(size).clip(CircleShape),
            contentScale = ContentScale.Crop
        )
    }
}
