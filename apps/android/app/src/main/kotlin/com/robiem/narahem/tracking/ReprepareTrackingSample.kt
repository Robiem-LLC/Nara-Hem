package com.robiem.narahem.tracking

/**
 * Thrown when a prepared record is stale (the roster changed) and must be rebuilt before retrying.
 */
class ReprepareTrackingSample : Exception()
