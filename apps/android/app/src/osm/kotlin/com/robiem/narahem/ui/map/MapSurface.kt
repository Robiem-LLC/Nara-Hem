package com.robiem.narahem.ui.map

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.robiem.narahem.BuildConfig
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.location.LocalFix
import com.robiem.narahem.data.trips.TripPoint
import com.robiem.narahem.ui.places.PlaceGeometry
import com.robiem.narahem.ui.settings.ProfilePhotos
import com.robiem.narahem.ui.theme.NaraHemColors
import java.io.File
import okhttp3.Cache
import okhttp3.OkHttpClient
import org.maplibre.android.MapLibre
import org.maplibre.android.annotations.IconFactory
import org.maplibre.android.annotations.MarkerOptions
import org.maplibre.android.annotations.PolygonOptions
import org.maplibre.android.annotations.PolylineOptions
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.Style
import org.maplibre.android.module.http.HttpRequestUtil

/** MapLibre style that shows OpenStreetMap raster tiles. */
private const val OSM_STYLE = """{
  "version": 8,
  "sources": {
    "osm": {
      "type": "raster",
      "tiles": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      "tileSize": 256,
      "maxzoom": 19,
      "attribution": "© OpenStreetMap contributors"
    }
  },
  "layers": [{"id": "osm", "type": "raster", "source": "osm"}]
}"""

private var tileHttp: OkHttpClient? = null

/** OpenStreetMap map (MapLibre) showing member avatars and saved place circles. */
@Suppress("DEPRECATION")
@Composable
fun MapSurface(
    fix: LocalFix?,
    modifier: Modifier = Modifier,
    focusKey: Int = 0,
    onError: (String) -> Unit,
    members: List<HouseholdPerson> = emptyList(),
    focusPersonId: String? = null,
    ownPersonId: String? = null,
    places: List<HouseholdPlace> = emptyList(),
    occludedBottom: Dp = 0.dp,
    onViewportChanged: ((Double, Double, Double) -> Unit)? = null
) {
    val context = LocalContext.current
    val bottomPixels = with(LocalDensity.current) { occludedBottom.roundToPx().coerceAtLeast(0) }
    val latestFix by rememberUpdatedState(fix)
    val latestPeople by rememberUpdatedState(members)
    val latestPlaces by rememberUpdatedState(places)
    val latestPerson by rememberUpdatedState(focusPersonId)
    val latestOwn by rememberUpdatedState(ownPersonId)
    val latestError by rememberUpdatedState(onError)
    val latestFocus by rememberUpdatedState(focusKey)
    val latestViewport by rememberUpdatedState(onViewportChanged)
    var centered by remember { mutableStateOf(false) }
    var appliedFocus by remember { mutableIntStateOf(-1) }
    var drawnSnapshot by remember {
        mutableStateOf<Triple<List<HouseholdPerson>, List<HouseholdPlace>, LocalFix?>?>(null)
    }

    /** Replaces the markers and circles with the latest data. */
    fun redraw(map: MapLibreMap) {
        @Suppress("DEPRECATION")
        map.setPadding(0, 0, 0, bottomPixels)
        map.uiSettings.isRotateGesturesEnabled = false
        map.uiSettings.isCompassEnabled = false
        map.uiSettings.isTiltGesturesEnabled = false
        if (map.style?.isFullyLoaded != true) return
        val currentSnapshot = Triple(latestPeople, latestPlaces, latestFix)
        if (currentSnapshot != drawnSnapshot) {
            map.clear()
            val fan = AvatarFan.layout(latestPeople, latestPlaces, ProfilePhotos.MARKER_PIXELS)
            for (person in latestPeople) {
                if (person.latitude != null && person.longitude != null) {
                    val freshness = LocationFreshness.of(person)
                    val stale = freshness.alarming
                    val marker = MarkerOptions().position(LatLng(person.latitude, person.longitude))
                        .title(person.name + freshness.suffix)
                    val photo = ProfilePhotos.fanned(
                        ProfilePhotos.roundMarker(person.photo, stale = stale)
                            ?: ProfilePhotos.initialsMarker(person.name, stale = stale),
                        fan[person.id]
                    )
                    marker.icon(IconFactory.getInstance(context).fromBitmap(photo))
                    map.addMarker(marker)
                }
            }
            for (place in latestPlaces) {
                drawPlaceBoundary(map, place.latitude, place.longitude, place.radius)
            }
            if (latestPeople.none {
                    it.id == latestOwn && it.latitude != null && it.longitude != null
                }
            ) {
                latestFix?.let {
                    map.addMarker(
                        MarkerOptions().position(
                            LatLng(it.latitude, it.longitude)
                        ).title("This phone")
                    )
                }
            }
            drawnSnapshot = currentSnapshot
        }
        if (!centered || appliedFocus != latestFocus) {
            val target = mapCameraTarget(latestFix, latestPeople, latestOwn, latestPerson)
            if (target != null) {
                val camera = CameraUpdateFactory.newLatLngZoom(
                    LatLng(target.first, target.second),
                    if (latestPerson == null) 15.0 else 17.0
                )
                if (!centered) map.moveCamera(camera) else map.animateCamera(camera)
                centered = true
                appliedFocus = latestFocus
            }
        }
    }

    val view = remember {
        MapLibre.getInstance(context)
        HttpRequestUtil.setLogEnabled(false)
        HttpRequestUtil.setOkHttpClient(
            tileHttp ?: OkHttpClient.Builder()
                .cache(Cache(File(context.cacheDir, "map-tiles"), 32L * 1024 * 1024))
                .addInterceptor { chain ->
                    chain.proceed(
                        chain.request().newBuilder()
                            .header(
                                "User-Agent",
                                "NaraHemAndroid/" + BuildConfig.VERSION_NAME +
                                    " (" + BuildConfig.APPLICATION_ID + ")"
                            )
                            .build()
                    )
                }.build().also { tileHttp = it }
        )
        MapView(context).apply {
            onCreate(null)
            addOnDidFailLoadingMapListener {
                latestError("OpenStreetMap could not load. Check your connection and retry.")
            }
            getMapAsync { map ->
                limitToOneWorld(this, map)
                map.setOnMarkerClickListener { marker ->
                    map.animateCamera(CameraUpdateFactory.newLatLngZoom(marker.position, 17.0))
                    true
                }
                map.setStyle(Style.Builder().fromJson(OSM_STYLE)) { redraw(map) }
                map.addOnCameraIdleListener {
                    if (centered) {
                        val position = map.cameraPosition
                        position.target?.let { center ->
                            latestViewport?.invoke(center.latitude, center.longitude, position.zoom)
                        }
                    }
                }
            }
        }
    }
    LaunchedEffect(fix, members, places, focusKey, focusPersonId, ownPersonId, bottomPixels) {
        view.getMapAsync { redraw(it) }
    }
    MapLifecycle(view, view::onStart, view::onResume, view::onPause, view::onStop, view::onDestroy)
    Box(modifier) {
        AndroidView(
            factory = { view },
            modifier = Modifier.fillMaxSize(),
            update = { target -> target.getMapAsync { redraw(it) } }
        )
        if (!centered) {
            Surface(Modifier.fillMaxSize()) {
                Column(
                    Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    CircularProgressIndicator()
                    Text("Finding your location…", Modifier.padding(16.dp))
                }
            }
        }
        Text(
            "© OpenStreetMap contributors",
            Modifier.align(Alignment.BottomStart).padding(6.dp),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall
        )
    }
}

/**
 * OpenStreetMap map for the place editor. The centre reticle stays fixed while the map pans; the
 * map centre is the place's position.
 */
@Suppress("DEPRECATION")
@Composable
fun PlacePickerMap(
    latitude: Double,
    longitude: Double,
    radiusMeters: Double,
    initialZoom: Double = 15.0,
    recenterKey: Int = 0,
    onCenterChanged: (Double, Double) -> Unit,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val latestChanged by rememberUpdatedState(onCenterChanged)
    val view = remember {
        MapLibre.getInstance(context)
        MapView(context).apply {
            onCreate(null)
            getMapAsync { map ->
                limitToOneWorld(this, map)
                map.uiSettings.isRotateGesturesEnabled = false
                map.uiSettings.isCompassEnabled = false
                map.uiSettings.isTiltGesturesEnabled = false
                map.setStyle(Style.Builder().fromJson(OSM_STYLE)) {
                    map.moveCamera(
                        CameraUpdateFactory.newLatLngZoom(LatLng(latitude, longitude), initialZoom)
                    )
                    map.addOnCameraIdleListener {
                        val center = map.cameraPosition.target
                        center?.let { latestChanged(it.latitude, it.longitude) }
                    }
                }
            }
        }
    }
    MapLifecycle(view, view::onStart, view::onResume, view::onPause, view::onStop, view::onDestroy)
    LaunchedEffect(recenterKey) {
        if (recenterKey > 0) {
            view.getMapAsync { map ->
                map.animateCamera(
                    CameraUpdateFactory.newLatLngZoom(LatLng(latitude, longitude), initialZoom)
                )
            }
        }
    }
    Box(modifier) {
        AndroidView(factory = { view }, modifier = Modifier.fillMaxSize(), update = {
            it.getMapAsync { map ->
                if (map.style?.isFullyLoaded != true) return@getMapAsync
                map.clear()
                drawPlaceBoundary(map, latitude, longitude, radiusMeters)
            }
        })
        Text(
            "＋",
            modifier = Modifier.align(Alignment.Center),
            style = MaterialTheme.typography.headlineLarge,
            color = MaterialTheme.colorScheme.primary
        )
    }
}

/** Draws a saved place's circle as a filled polygon. */
@Suppress("DEPRECATION")
private fun drawPlaceBoundary(
    map: MapLibreMap,
    latitude: Double,
    longitude: Double,
    radius: Double
) {
    val vertices = PlaceGeometry.circle(latitude, longitude, radius)
        .map { LatLng(it.first, it.second) }
    // MapLibre annotations don't reliably keep ARGB alpha, so opacity is set separately.
    map.addPolygon(
        PolygonOptions().addAll(vertices)
            .fillColor(NaraHemColors.Place.toArgb()).alpha(0.12f)
    )
    map.addPolyline(
        PolylineOptions().addAll(vertices + vertices.first())
            .color(NaraHemColors.Place.toArgb()).width(2f)
    )
}

/** OpenStreetMap map showing a trip's route with start and end markers. */
@Suppress("DEPRECATION")
@Composable
fun TripRouteMap(
    segments: List<List<com.robiem.narahem.data.trips.TripPoint>>,
    modifier: Modifier = Modifier,
    onOpen: (() -> Unit)? = null
) {
    val context = LocalContext.current
    val latest by rememberUpdatedState(segments)
    val open by rememberUpdatedState(onOpen)
    val drawn = remember { arrayOfNulls<List<List<com.robiem.narahem.data.trips.TripPoint>>>(1) }
    var failed by remember { mutableStateOf(false) }
    val view = remember {
        MapLibre.getInstance(context)
        MapView(context).apply { onCreate(null) }
    }

    /** Draws the route and fits the camera to it. */
    fun draw(map: MapLibreMap) {
        if (map.style?.isFullyLoaded != true || drawn[0] == latest) return
        drawn[0] = latest
        map.clear()
        latest.filter { it.size >= 2 }.forEach { line ->
            map.addPolyline(
                PolylineOptions()
                    .addAll(
                        line.map {
                            LatLng(it.latitude, it.longitude)
                        }
                    ).color(NaraHemColors.Route.toArgb()).width(4f)
            )
        }
        val points = latest.flatten()
        val icons = org.maplibre.android.annotations.IconFactory.getInstance(context)
        for ((point, label, color) in listOf(
            Triple(points.firstOrNull(), "Start", TripMarkers.START),
            Triple(points.lastOrNull(), "End", TripMarkers.END)
        )) {
            point?.let {
                map.addMarker(
                    MarkerOptions().position(LatLng(it.latitude, it.longitude)).title(label)
                        .icon(icons.fromBitmap(TripMarkers.dot(color)))
                )
            }
        }
        if (points.isNotEmpty()) {
            view.post {
                if (view.width > 0 && view.height > 0) {
                    if (points.all {
                            it.latitude == points.first().latitude &&
                                it.longitude == points.first().longitude
                        }
                    ) {
                        map.moveCamera(
                            CameraUpdateFactory.newLatLngZoom(
                                LatLng(points.first().latitude, points.first().longitude),
                                16.0
                            )
                        )
                    } else {
                        map.moveCamera(
                            CameraUpdateFactory.newLatLngBounds(
                                org.maplibre.android.geometry.LatLngBounds.Builder()
                                    .includes(
                                        points.map {
                                            LatLng(it.latitude, it.longitude)
                                        }
                                    ).build(),
                                40
                            )
                        )
                    }
                } else {
                    drawn[0] = null // not laid out yet: frame it on the next pass
                }
            }
        }
    }
    DisposableEffect(view) {
        view.addOnDidFailLoadingMapListener { failed = true }
        view.getMapAsync { map ->
            map.uiSettings.isRotateGesturesEnabled = false
            if (open != null) {
                map.uiSettings.setAllGesturesEnabled(false)
                map.addOnMapClickListener {
                    open?.invoke()
                    true
                }
            }
            map.setStyle(Style.Builder().fromJson(OSM_STYLE)) { draw(map) }
        }
        onDispose { }
    }
    MapLifecycle(view, view::onStart, view::onResume, view::onPause, view::onStop, view::onDestroy)
    Box(modifier) {
        AndroidView(factory = {
            view
        }, modifier = Modifier.fillMaxSize(), update = { it.getMapAsync { map -> draw(map) } })
        Text(
            if (failed) "Map unavailable" else "© OpenStreetMap contributors",
            Modifier.align(Alignment.BottomStart).padding(4.dp),
            style = MaterialTheme.typography.labelSmall
        )
    }
}

/** Stops the map zooming out so far that the world repeats side by side. */
private fun limitToOneWorld(view: MapView, map: MapLibreMap) {
    map.setLatLngBoundsForCameraTarget(
        org.maplibre.android.geometry.LatLngBounds.from(
            WORLD_LATITUDE,
            WORLD_LONGITUDE,
            -WORLD_LATITUDE,
            -WORLD_LONGITUDE
        )
    )
    val apply = {
        if (view.width > 0) {
            map.setMinZoomPreference(
                worldMinZoom(view.width / view.resources.displayMetrics.density, 512f).toDouble()
            )
        }
    }
    apply()
    view.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> apply() }
}
