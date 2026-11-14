package com.robiem.narahem.ui.map

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import androidx.compose.ui.graphics.toArgb
import com.robiem.narahem.ui.theme.NaraHemColors

/** Trip start and end markers: green for the start, red for the end. */
internal object TripMarkers {
    /** Start marker colour. */
    val START = NaraHemColors.TripStart.toArgb()

    /** End marker colour. */
    val END = NaraHemColors.TripEnd.toArgb()

    /** Draws a coloured dot with a white ring, for maps without coloured pins. */
    fun dot(color: Int, pixels: Int = 42): Bitmap {
        val bitmap = Bitmap.createBitmap(pixels, pixels, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        val r = pixels / 2f
        paint.color = NaraHemColors.White.toArgb()
        canvas.drawCircle(r, r, r, paint)
        paint.color = color
        canvas.drawCircle(r, r, r * 0.72f, paint)
        return bitmap
    }
}
