package com.robiem.narahem.tracking

import java.io.IOException
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class QueuedTrackingDeliveryTest {
    private fun item(id: String, at: Long = 1234) = JSONObject()
        .put("queue_id", id).put("captured", at).put("kind", "trip")

    @Test fun lostAcknowledgementAndRestartRetryExactEnvelopeWithOriginalTimestamp() = runTest {
        val q = Queue()
        var prepared = 0
        val sent = mutableListOf<String>()
        q.append(item("one"))
        val prepare: suspend (JSONObject) -> JSONObject = {
            prepared++
            JSONObject().put(
                "record_id",
                "unique-$prepared"
            ).put("captured", it.getLong("captured"))
        }
        val first = QueuedTrackingDelivery(q, { true }, prepare) {
            sent.add(it.toString())
            throw IOException("ack lost")
        }
        try {
            first.drain()
            fail("Must retain an unacknowledged item")
        } catch (_: IOException) {}
        assertEquals(1, q.size())
        assertTrue(q.peek()!!.has("envelope"))
        // A fresh drainer models a service/process restart using persisted queue data.
        QueuedTrackingDelivery(q, { true }, prepare) { sent.add(it.toString()) }.drain()
        assertEquals(1, prepared)
        assertEquals(sent[0], sent[1])
        assertEquals(1234L, JSONObject(sent[1]).getLong("captured"))
        assertEquals(0, q.size())
    }

    @Test fun membershipChangeRepreparesInsteadOfDroppingCapturedData() = runTest {
        val q = Queue()
        var revision = 0
        q.append(item("one"))
        val prepare: suspend (
            JSONObject
        ) -> JSONObject = { JSONObject().put("revision", ++revision) }
        QueuedTrackingDelivery(q, { true }, prepare) { throw ReprepareTrackingSample() }.drain()
        assertEquals(1, q.size())
        assertFalse(q.peek()!!.has("envelope"))
        QueuedTrackingDelivery(q, {
            true
        }, prepare) { assertEquals(2, it.getInt("revision")) }.drain()
        assertEquals(0, q.size())
    }

    @Test fun pauseWhilePreparingClearsQueueAndPreventsSending() = runTest {
        val q = Queue()
        var enabled = true
        var sends = 0
        q.append(item("one"))
        QueuedTrackingDelivery(q, { enabled }, {
            enabled = false
            q.clear()
            JSONObject()
        }) { sends++ }.drain()
        assertEquals(0, sends)
        assertEquals(0, q.size())
    }

    @Test fun expiredSamplesCannotBlockLaterRecordsAndBatchLimitBoundsReplay() = runTest {
        val q = Queue()
        val delivered = mutableListOf<String>()
        q.append(item("expired"))
        q.append(item("good"))
        q.append(item("later"))
        var expired = 0
        QueuedTrackingDelivery(q, {
            true
        }, { JSONObject().put("id", it.getString("queue_id")) }, onExpired = { expired++ }) {
            if (it.getString("id") == "expired") throw ExpiredTrackingSample()
            delivered.add(it.getString("id"))
        }.drain(limit = 2)
        assertEquals(listOf("good"), delivered)
        assertEquals(1, q.size())
        assertEquals(1, expired)
        assertEquals("later", q.peek()!!.getString("queue_id"))
    }

    @Test fun permanentRevocationClearsRemainingQueue() = runTest {
        val q = Queue()
        q.append(item("one"))
        q.append(item("two"))
        try {
            QueuedTrackingDelivery(q, {
                true
            }, { JSONObject() }) { throw TrackingDisabled() }.drain()
            fail("Revocation must stop delivery")
        } catch (_: TrackingDisabled) {}
        assertEquals(0, q.size())
    }

    private class Queue : PendingTrackingQueue {
        val rows = mutableListOf<JSONObject>()

        override fun peek() = rows.firstOrNull()?.let { JSONObject(it.toString()) }
        override fun remove(id: String): Boolean = rows.removeAll { it.getString("queue_id") == id }
        override fun size() = rows.size

        override fun append(value: JSONObject) {
            rows.add(JSONObject(value.toString()))
        }

        override fun replace(id: String, value: JSONObject): Boolean {
            val i = rows.indexOfFirst { it.getString("queue_id") == id }
            if (i < 0) return false
            rows[i] = JSONObject(value.toString())
            return true
        }

        override fun clear() {
            rows.clear()
        }
    }
}
