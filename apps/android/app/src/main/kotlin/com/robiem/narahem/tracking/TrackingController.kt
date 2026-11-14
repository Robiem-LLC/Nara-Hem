package com.robiem.narahem.tracking

/** Controls the background location sharing service. */
interface TrackingController {
    /** Starts background location sharing. */
    fun startSharing()

    /** Stops background location sharing. */
    fun stopSharing()

    /** Stops a ringing Find My Phone alarm. */
    fun stopFindPhoneAlarm()

    /** Asks a running location service to send this phone's location now. */
    fun checkInNow()

    /** Reports this phone's permission state to the server. */
    suspend fun reportDevicePermissions()
}
