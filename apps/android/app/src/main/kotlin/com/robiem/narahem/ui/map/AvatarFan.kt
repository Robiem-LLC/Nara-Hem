package com.robiem.narahem.ui.map

import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.PlaceMatching
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Spreads out member avatars that overlap on the map, in screen pixels only. Members within 35 m,
 * or within 100 m in the same saved place, form a group drawn as a row of slightly overlapping
 * avatars. Same rules as the web map.
 */
object AvatarFan {
    /** Returns each member's pixel offset for avatars [size] pixels wide. */
    fun layout(
        people: List<HouseholdPerson>,
        places: List<HouseholdPlace>,
        size: Int
    ): Map<String, Offset> {
        val members = people.filter { it.latitude != null && it.longitude != null }
        val place = members.map {
            PlaceMatching.match(it.latitude!!, it.longitude!!, places, it.accuracy ?: 25.0)?.id
        }
        val parent = IntArray(members.size) { it }

        /** Returns the group representative for member [i] (union-find with path compression). */
        fun root(i: Int): Int {
            var x = i
            while (parent[x] != x) {
                parent[x] = parent[parent[x]]
                x = parent[x]
            }
            return x
        }
        for (i in members.indices) {
            for (j in i + 1 until members.size) {
                val a = members[i]
                val b = members[j]
                val north = (a.latitude!! - b.latitude!!) * 111_320
                val east =
                    (a.longitude!! - b.longitude!!) * 111_320 *
                        cos((a.latitude + b.latitude) / 2 * PI / 180)
                val distance = hypot(north, east)
                if (distance <= 35 ||
                    (place[i] != null && place[i] == place[j] && distance <= 100)
                ) {
                    parent[root(j)] = root(i)
                }
            }
        }
        val offsets = mutableMapOf<String, Offset>()
        val step = size * 42.0 / 46
        val rise = size * 36.0 / 46
        members.indices.groupBy { root(it) }.values.filter { it.size > 1 }.forEach { group ->
            val ordered = group.sortedBy { members[it].id }
            val cols = min(4, ordered.size)
            ordered.forEachIndexed { slot, index ->
                val row = slot / cols
                val inRow = slot % cols
                val count = min(cols, ordered.size - row * cols)
                offsets[members[index].id] =
                    Offset(
                        (((inRow - (count - 1) / 2.0) * step)).roundToInt(),
                        -(row * rise).roundToInt(),
                        ordered.size
                    )
            }
        }
        return offsets
    }

    /** Pixel offset for one avatar and the size of its group. */
    data class Offset(val dx: Int = 0, val dy: Int = 0, val groupSize: Int = 1)
}
