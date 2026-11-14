package com.robiem.narahem.tracking

import org.json.JSONObject

/** A record ready to publish from the queue: kind, entity ID and data. */
data class PendingTrackingPayload(val kind: String, val entityId: String, val data: JSONObject)
