package com.robiem.narahem.data.location

/** Reads this phone's location. */
interface LocationRepository {
    /** Requests a fresh location, waiting up to 20 seconds. */
    suspend fun current(): LocalFix

    /** Returns the most recent location Android has cached, which may be old. */
    fun lastKnown(): LocalFix? = null
}
