package com.robiem.narahem.data.settings

import android.content.Context

/** [AppSettings] stored in SharedPreferences, using the keys from earlier app versions. */
class PhoneAppSettings(context: Context) : AppSettings {
    private val prefs = context.getSharedPreferences("server", Context.MODE_PRIVATE)

    override var serverUrl: String
        get() = prefs.getString("url", "").orEmpty()
        set(value) = prefs.edit().putString("url", value).apply()

    override var mapConsent: Boolean
        get() = prefs.getBoolean("map-consent", false)
        set(value) = prefs.edit().putBoolean("map-consent", value).apply()

    // Street addresses are always looked up; there is no setting any more.
    override var addressLookup: Boolean
        get() = true
        set(@Suppress("UNUSED_PARAMETER") value) {}

    /** Stored as separate keys; returns null if any are missing. */
    override var mapCamera: MapCamera?
        get() {
            val latitude = prefs.getString("map_lat", null)?.toDoubleOrNull() ?: return null
            val longitude = prefs.getString("map_lon", null)?.toDoubleOrNull() ?: return null
            val zoom = prefs.getString("map_zoom", null)?.toDoubleOrNull() ?: DEFAULT_ZOOM
            return MapCamera(latitude, longitude, zoom)
        }
        set(value) {
            val edit = prefs.edit()
            if (value == null) {
                edit.remove("map_lat").remove("map_lon").remove("map_zoom")
            } else {
                edit.putString("map_lat", value.latitude.toString())
                    .putString("map_lon", value.longitude.toString())
                    .putString("map_zoom", value.zoom.toString())
            }
            edit.apply()
        }

    override var locationPrompted: Boolean
        get() = prefs.getBoolean("location.initial.prompted", false)
        set(value) = prefs.edit().putBoolean("location.initial.prompted", value).apply()

    /** Defaults. */
    companion object {
        const val DEFAULT_ZOOM = 15.0
    }
}
