package com.robiem.narahem.tracking

/**
 * Chooses which row to drop when the offline queue is full. Removes GPS fixes where they are
 * densest, so a long drive without network keeps its whole route and its trip summary.
 */
object OutboxThinning {
    /**
     * Returns the index of the location row whose removal leaves the smallest time gap, never the
     * oldest (it may be uploading) or newest row. Returns null if no location row can be removed.
     */
    fun victim(kinds: List<String>, captured: List<Long>): Int? {
        var best: Int? = null
        require(kinds.size == captured.size)
        var bestGap = Long.MAX_VALUE
        for (index in 1 until kinds.size - 1) {
            if (kinds[index] != "location") continue
            val gap = captured[index + 1] - captured[index - 1]
            if (gap < bestGap) {
                bestGap = gap
                best = index
            }
        }
        return best
    }
}
