package com.robiem.narahem.tracking

/**
 * Thrown when a queued location is older than the server's retention window and must be dropped.
 */
class ExpiredTrackingSample : Exception()
