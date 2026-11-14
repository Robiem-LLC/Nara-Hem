package com.robiem.narahem.data.settings

/** Non-secret settings stored on this phone. */
interface AppSettings {
    /** Server used for the last sign-in. */
    var serverUrl: String

    /** Whether the user agreed to location sharing and loading map tiles. */
    var mapConsent: Boolean

    /**
     * Whether street addresses are looked up for locations. Lookups send coordinates to the map
     * provider.
     */
    var addressLookup: Boolean

    /** Last map position. */
    var mapCamera: MapCamera?

    /** Whether the first-launch location permission prompt has been shown. */
    var locationPrompted: Boolean
}
