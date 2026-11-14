package com.robiem.narahem.ui.map

import android.os.SystemClock
import android.view.Choreographer

/** Calls [onFrame] with the time in uptime milliseconds on every display frame while it returns true. */
class MarkerFrames(private val onFrame: (Long) -> Boolean) : Choreographer.FrameCallback {
    private var running = false

    /** Starts calling back on each frame, if it isn't already. */
    fun start() {
        if (running) return
        running = true
        Choreographer.getInstance().postFrameCallback(this)
    }

    /** Stops calling back. */
    fun stop() {
        running = false
        Choreographer.getInstance().removeFrameCallback(this)
    }

    /** Runs one frame and asks for the next while there is more to do. */
    override fun doFrame(frameTimeNanos: Long) {
        if (!running) return
        if (onFrame(SystemClock.uptimeMillis())) {
            Choreographer.getInstance().postFrameCallback(this)
        } else {
            running = false
        }
    }
}
