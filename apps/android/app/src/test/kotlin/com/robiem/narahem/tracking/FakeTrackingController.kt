package com.robiem.narahem.tracking

/** Records what the screens asked of the background service. */
class FakeTrackingController : TrackingController {
    var sharing = false
    var alarmStops = 0
    var permissionReports = 0
    var checkIns = 0

    override fun startSharing() {
        sharing = true
    }

    override fun stopSharing() {
        sharing = false
    }

    override fun checkInNow() {
        checkIns++
    }

    override fun stopFindPhoneAlarm() {
        alarmStops++
    }

    override suspend fun reportDevicePermissions() {
        permissionReports++
    }
}
