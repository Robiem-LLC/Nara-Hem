package com.robiem.narahem.ui.map

import android.os.Handler
import android.os.Looper
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
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
import com.google.android.gms.maps.CameraUpdateFactory
import com.google.android.gms.maps.GoogleMap
import com.google.android.gms.maps.MapView
import com.google.android.gms.maps.model.BitmapDescriptorFactory
import com.google.android.gms.maps.model.CircleOptions
import com.google.android.gms.maps.model.LatLng
import com.google.android.gms.maps.model.MarkerOptions
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.location.LocalFix
import com.robiem.narahem.data.trips.TripPoint
import com.robiem.narahem.ui.settings.ProfilePhotos
import com.robiem.narahem.ui.theme.NaraHemColors

/** Google map showing member avatars and saved place circles. */
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
    var followPaused by remember { mutableStateOf(false) }
    var appliedFocus by remember { mutableIntStateOf(-1) }
    var drawnSnapshot by remember {
        mutableStateOf<Triple<List<HouseholdPerson>, List<HouseholdPlace>, LocalFix?>?>(null)
    }
    val view = remember { MapView(context).apply { onCreate(null) } }
    DisposableEffect(view) {
        val handler = Handler(Looper.getMainLooper())
        val timeout =
            Runnable {
                latestError(
                    "Google Maps did not finish loading. Check your connection, API key and " +
                        "Play services."
                )
            }
        handler.postDelayed(timeout, 20_000)
        view.getMapAsync { map ->
            limitToOneWorld(view, map)
            map.setOnMarkerClickListener { marker ->
                map.animateCamera(CameraUpdateFactory.newLatLngZoom(marker.position, 17f))
                marker.showInfoWindow()
                true
            }
            map.setOnMapLoadedCallback { handler.removeCallbacks(timeout) }
            map.setOnCameraMoveStartedListener { reason ->
                if (reason == GoogleMap.OnCameraMoveStartedListener.REASON_GESTURE &&
                    latestPerson != null
                ) {
                    followPaused = true
                }
            }
            map.setOnCameraIdleListener {
                if (centered) {
                    val position = map.cameraPosition
                    latestViewport?.invoke(
                        position.target.latitude,
                        position.target.longitude,
                        position.zoom.toDouble()
                    )
                }
            }
        }
        onDispose { handler.removeCallbacks(timeout) }
    }
    /** Replaces the markers and circles with the latest data. */
    fun redraw(map: GoogleMap) {
        map.setPadding(0, 0, 0, bottomPixels)
        map.uiSettings.isMapToolbarEnabled = false
        map.uiSettings.isZoomControlsEnabled = false
        map.uiSettings.isCompassEnabled = false
        map.uiSettings.isRotateGesturesEnabled = false
        map.uiSettings.isTiltGesturesEnabled = false
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
                    marker.icon(BitmapDescriptorFactory.fromBitmap(photo))
                    map.addMarker(marker)
                }
            }
            for (place in latestPlaces) {
                map.addCircle(
                    CircleOptions().center(LatLng(place.latitude, place.longitude))
                        .radius(
                            place.radius
                        ).strokeWidth(3f).strokeColor(NaraHemColors.Place.toArgb())
                        .fillColor(NaraHemColors.Place.copy(alpha = 0.12f).toArgb())
                )
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
            followPaused = false
            val target = mapCameraTarget(latestFix, latestPeople, latestOwn, latestPerson)
            if (target != null) {
                val camera = CameraUpdateFactory.newLatLngZoom(
                    LatLng(target.first, target.second),
                    if (latestPerson == null) 15f else 17f
                )
                if (!centered) map.moveCamera(camera) else map.animateCamera(camera)
                centered = true
                appliedFocus = latestFocus
            }
        } else if (!followPaused && latestPerson != null) {
            val selected = latestPeople.firstOrNull { it.id == latestPerson }
            if (selected?.latitude != null && selected.longitude != null) {
                val position = LatLng(selected.latitude, selected.longitude)
                val distance = FloatArray(1)
                android.location.Location.distanceBetween(
                    map.cameraPosition.target.latitude,
                    map.cameraPosition.target.longitude,
                    position.latitude,
                    position.longitude,
                    distance
                )
                if (distance[0] > 12f) {
                    map.animateCamera(CameraUpdateFactory.newLatLng(position), 800, null)
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
        if (followPaused && focusPersonId != null) {
            Button(onClick = {
                followPaused = false
                appliedFocus = -1
                view.getMapAsync { redraw(it) }
            }, modifier = Modifier.align(Alignment.TopEnd).padding(12.dp)) {
                Text("Resume follow")
            }
        }
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
    }
}

/**
 * Google map for the place editor. The centre reticle stays fixed while the map pans; the map
 * centre is the place's position.
 */
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
    val view = remember { MapView(context).apply { onCreate(null) } }
    DisposableEffect(view) {
        view.getMapAsync { map ->
            limitToOneWorld(view, map)
            map.uiSettings.isZoomControlsEnabled = false
            map.uiSettings.isRotateGesturesEnabled = false
            map.uiSettings.isCompassEnabled = false
            map.uiSettings.isTiltGesturesEnabled = false
            map.moveCamera(
                CameraUpdateFactory.newLatLngZoom(
                    LatLng(latitude, longitude),
                    initialZoom.toFloat()
                )
            )
            map.setOnCameraIdleListener {
                val center = map.cameraPosition.target
                latestChanged(center.latitude, center.longitude)
            }
        }
        onDispose { view.getMapAsync { it.setOnCameraIdleListener(null) } }
    }
    MapLifecycle(view, view::onStart, view::onResume, view::onPause, view::onStop, view::onDestroy)
    LaunchedEffect(recenterKey) {
        if (recenterKey > 0) {
            view.getMapAsync { map ->
                map.animateCamera(
                    CameraUpdateFactory.newLatLngZoom(
                        LatLng(latitude, longitude),
                        initialZoom.toFloat()
                    )
                )
            }
        }
    }
    Box(modifier) {
        AndroidView(factory = { view }, modifier = Modifier.fillMaxSize(), update = {
            it.getMapAsync { map ->
                map.clear()
                map.addCircle(
                    CircleOptions().center(LatLng(latitude, longitude))
                        .radius(radiusMeters)
                        .strokeWidth(3f).strokeColor(NaraHemColors.Place.toArgb())
                        .fillColor(NaraHemColors.Place.copy(alpha = 0.12f).toArgb())
                )
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

/** Google map showing a trip's route with start and end markers. In lite mode for list previews. */
@Composable
fun TripRouteMap(
    segments: List<List<com.robiem.narahem.data.trips.TripPoint>>,
    modifier: Modifier = Modifier,
    onOpen: (() -> Unit)? = null
) {
    val context = LocalContext.current
    val latest by rememberUpdatedState(segments)
    val open by rememberUpdatedState(onOpen)
    val view =
        remember {
            MapView(
                context,
                com.google.android.gms.maps.GoogleMapOptions().liteMode(onOpen != null)
            ).apply {
                onCreate(null)
            }
        }
    val drawn = remember { arrayOfNulls<List<List<com.robiem.narahem.data.trips.TripPoint>>>(1) }

    /** Draws the route and fits the camera to it. */
    fun draw(map: GoogleMap) {
        if (drawn[0] == latest) return
        drawn[0] = latest
        map.clear()
        map.uiSettings.isMapToolbarEnabled = false
        map.setMapStyle(com.google.android.gms.maps.model.MapStyleOptions(DARK_MAP_STYLE))
        if (open != null) map.setOnMapClickListener { open?.invoke() }
        latest.filter { it.size >= 2 }.forEach { line ->
            map.addPolyline(
                com.google.android.gms.maps.model.PolylineOptions()
                    .addAll(
                        line.map {
                            LatLng(it.latitude, it.longitude)
                        }
                    ).color(NaraHemColors.Route.toArgb()).width(7f)
            )
        }
        val points = latest.flatten()
        for ((point, label, hue) in listOf(
            Triple(points.firstOrNull(), "Start", BitmapDescriptorFactory.HUE_GREEN),
            Triple(points.lastOrNull(), "End", BitmapDescriptorFactory.HUE_RED)
        )) {
            point?.let {
                map.addMarker(
                    MarkerOptions().position(LatLng(it.latitude, it.longitude)).title(label)
                        .icon(BitmapDescriptorFactory.defaultMarker(hue))
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
                                16f
                            )
                        )
                    } else {
                        val bounds = com.google.android.gms.maps.model.LatLngBounds.Builder()
                        points.forEach { bounds.include(LatLng(it.latitude, it.longitude)) }
                        map.moveCamera(CameraUpdateFactory.newLatLngBounds(bounds.build(), 40))
                    }
                } else {
                    drawn[0] = null // not laid out yet: frame it on the next pass
                }
            }
        }
    }
    MapLifecycle(view, view::onStart, view::onResume, view::onPause, view::onStop, view::onDestroy)
    AndroidView(factory = {
        view
    }, modifier = modifier, update = { it.getMapAsync { map -> draw(map) } })
}

/** Stops the map zooming out so far that the world repeats side by side. */
private fun limitToOneWorld(view: MapView, map: GoogleMap) {
    map.setLatLngBoundsForCameraTarget(
        com.google.android.gms.maps.model.LatLngBounds(
            LatLng(-WORLD_LATITUDE, -WORLD_LONGITUDE),
            LatLng(WORLD_LATITUDE, WORLD_LONGITUDE)
        )
    )
    val apply = {
        if (view.width > 0) {
            map.setMinZoomPreference(
                worldMinZoom(view.width / view.resources.displayMetrics.density, 256f)
            )
        }
    }
    apply()
    view.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> apply() }
}
