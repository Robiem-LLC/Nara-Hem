package com.robiem.narahem.ui.map

import kotlin.math.ceil
import kotlin.math.log2

/** Map coordinates stop at about 85° north and south. */
internal const val WORLD_LATITUDE = 85.0

/**
 * The world's east and west edge for camera limits. Not 180: Google Maps turns 180° into -180°,
 * which made the limits a strip in the Pacific and kept the map over the ocean.
 */
internal const val WORLD_LONGITUDE = 179.99999

/**
 * Returns the smallest zoom at which one copy of the world fills a map [widthDp] wide, for a map
 * whose whole world is [tileDp] wide at zoom 0 (256 for Google Maps, 512 for MapLibre).
 */
internal fun worldMinZoom(widthDp: Float, tileDp: Float): Float =
    if (widthDp > tileDp) ceil(log2(widthDp / tileDp)) else 0f
