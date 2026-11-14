package com.robiem.narahem.data.settings

/** Settings kept in memory for tests. */
class FakeAppSettings(
    override var serverUrl: String = "",
    override var mapConsent: Boolean = false,
    override var addressLookup: Boolean = false,
    override var mapCamera: MapCamera? = null,
    override var locationPrompted: Boolean = false
) : AppSettings
