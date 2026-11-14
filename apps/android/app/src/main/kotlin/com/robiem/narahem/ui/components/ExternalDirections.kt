package com.robiem.narahem.ui.components

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import java.util.Locale

/** Opens directions in another app. The household server never receives the destination. */
internal object ExternalDirections {
    /** Returns "lat,lon" for a maps link, or null if the coordinates are invalid. */
    fun coordinates(latitude: Double, longitude: Double): String? {
        if (!latitude.isFinite() || !longitude.isFinite() ||
            latitude !in -90.0..90.0 || longitude !in -180.0..180.0
        ) {
            return null
        }
        return String.format(Locale.US, "%.7f,%.7f", latitude, longitude)
    }

    /**
     * Opens a geo: intent for the coordinates, or Google Maps in the browser if no app handles it.
     */
    fun open(context: Context, latitude: Double, longitude: Double) {
        val destination = coordinates(latitude, longitude) ?: return
        val native = Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0?q=" + Uri.encode(destination)))
        try {
            context.startActivity(native)
        } catch (_: ActivityNotFoundException) {
            fallback(context, destination)
        } catch (_: SecurityException) {
            fallback(context, destination)
        }
    }

    /** Opens Google Maps directions in the browser. */
    private fun fallback(context: Context, destination: String) {
        try {
            context.startActivity(
                Intent(
                    Intent.ACTION_VIEW,
                    Uri.parse(
                        "https://www.google.com/maps/dir/?api=1&destination=" +
                            Uri.encode(destination) + "&dir_action=navigate"
                    )
                )
            )
        } catch (_: Exception) {
            Toast.makeText(
                context,
                "No mapping app or browser is available for directions.",
                Toast.LENGTH_LONG
            ).show()
        }
    }
}
