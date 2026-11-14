package com.robiem.narahem.ui.trips

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Map
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.HouseholdTrip
import com.robiem.narahem.data.trips.TripStop
import com.robiem.narahem.data.trips.TripTimeline
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.map.TripRouteMap
import com.robiem.narahem.ui.places.PlaceGeometry
import com.robiem.narahem.ui.theme.cardBorder
import java.text.DateFormat
import java.util.Date

/** Looks up a street address near a point. Returns null when address lookups are disabled. */
typealias AddressNear = suspend (latitude: Double, longitude: Double) -> String?

/** Formats a time of day. */
private fun time(value: Long) = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(value))

/** Formats a date. */
private fun date(value: Long) = DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(value))

/** Formats a duration as "12 min" or "1 hr 5 min". */
private fun duration(ms: Long): String {
    val minutes = (ms / 60000).coerceAtLeast(0)
    return if (minutes >= 60) "${minutes / 60} hr ${minutes % 60} min" else "$minutes min"
}

/**
 * Shows the name for a trip end or stop: the server's label, a saved place, a street address or the
 * coordinates.
 */
@Composable
private fun Endpoint(
    latitude: Double?,
    longitude: Double?,
    places: List<HouseholdPlace>,
    addressNear: AddressNear?,
    known: String? = null
) {
    if (known != null) {
        Text(known)
        return
    }
    val place = if (latitude != null && longitude != null) {
        PlaceGeometry.matchingPlace(latitude, longitude, places)
    } else {
        null
    }
    var address by remember(latitude, longitude, addressNear) { mutableStateOf<String?>(null) }
    LaunchedEffect(latitude, longitude, addressNear, place) {
        address =
            if (addressNear != null && place == null && latitude != null && longitude != null) {
                addressNear(latitude, longitude)
            } else {
                null
            }
    }
    Text(
        place?.name ?: address
            ?: if (latitude != null && longitude != null) {
                "%.5f, %.5f".format(latitude, longitude)
            } else {
                "Location unavailable"
            }
    )
}

/** Trips list: range picker, day headings, trip and stop cards, and their dialogs. */
@Composable
fun TripTimelineCards(
    state: AppState,
    mapsEnabled: Boolean,
    addressNear: AddressNear?,
    onDays: (Int) -> Unit,
    onSavePlace: (String, Double, Double) -> Unit
) {
    var selected by remember { mutableStateOf<HouseholdTrip?>(null) }
    var saving by remember { mutableStateOf<TripStop?>(null) }
    var lastDay = ""
    DayChips(state.tripDays) { days ->
        selected = null
        onDays(days)
    }
    if (state.tripHistoryPartial) {
        Text(
            "Earlier route history exceeds this view's limit. Choose a shorter range. Routes " +
                "and stops may be incomplete."
        )
    }
    if (!state.tripsLoading && state.tripsError.isBlank() && state.trips.isEmpty()) {
        Text(
            "No trips",
            Modifier.padding(vertical = 16.dp),
            style = MaterialTheme.typography.bodyMedium
        )
        return
    }
    val entries = remember(state.trips, state.tripPoints, state.places) { timelineEntries(state) }
    for ((start, trip, stop) in entries) {
        val day = date(start)
        if (day != lastDay) {
            Text(
                day,
                Modifier.padding(top = 16.dp, bottom = 8.dp),
                style = MaterialTheme.typography.titleMedium
            )
            lastDay = day
        }
        key(trip?.id ?: stop!!.id) {
            ElevatedCard(
                Modifier.fillMaxWidth().padding(vertical = 6.dp).cardBorder()
                    .then(if (trip != null) Modifier.clickable { selected = trip } else Modifier)
            ) {
                if (trip != null) {
                    TripCard(trip, state, mapsEnabled, addressNear) { selected = trip }
                } else if (stop != null) {
                    StopCard(stop, state.places, addressNear) { saving = stop }
                }
            }
        }
    }
    Text(
        "Stops show observed stationary time. Distances and top speeds are GPS estimates. " +
            "Missing history cannot be reconstructed.",
        Modifier.padding(vertical = 12.dp),
        style = MaterialTheme.typography.bodySmall
    )
    selected?.let { chosen -> state.trips.firstOrNull { it.id == chosen.id } }?.let { trip ->
        TripDetailsDialog(trip, state, mapsEnabled, addressNear) { selected = null }
    }
    saving?.let { stop ->
        SavePlaceDialog(
            onSave = { name -> onSavePlace(name, stop.latitude, stop.longitude) },
            onDismiss = { saving = null }
        )
    }
}

/** Returns the trips and stops to show, newest first. Each entry has either a trip or a stop. */
private fun timelineEntries(state: AppState): List<Triple<Long, HouseholdTrip?, TripStop?>> {
    val displayed = state.trips.filter {
        !TripTimeline.isStationary(it, state.tripPoints) &&
            !TripTimeline.isInconsequential(it, state.tripPoints, state.places)
    }
    val trips = displayed.map { Triple(it.startedAt, it, null as TripStop?) }
    val stops = TripTimeline.stops(state.tripPoints, displayed, state.places).map {
        Triple(it.startedAt, null as HouseholdTrip?, it)
    }
    return (trips + stops).sortedByDescending { it.first }
}

/** Chips for choosing 1, 7 or 14 days. */
@Composable
private fun DayChips(current: Int, onDays: (Int) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        for (days in listOf(1, 7, 14)) {
            FilterChip(
                selected = current == days,
                onClick = { onDays(days) },
                label = { Text(if (days == 1) "Day" else "$days days") }
            )
        }
    }
}

/** Trip card: route preview, endpoints, times, distance and top speed. */
@Composable
private fun TripCard(
    trip: HouseholdTrip,
    state: AppState,
    mapsEnabled: Boolean,
    addressNear: AddressNear?,
    onOpen: () -> Unit
) {
    val points = TripTimeline.forTrip(trip, state.tripPoints)
    val segments = remember(points) { TripTimeline.route(points) }
    val usable = segments.flatten()
    if (mapsEnabled && usable.isNotEmpty()) {
        TripRouteMap(segments, Modifier.fillMaxWidth().height(180.dp), onOpen = onOpen)
    } else {
        Text(
            if (usable.isEmpty()) "Route unavailable" else "Enable maps to see the route",
            Modifier.padding(16.dp)
        )
    }
    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Endpoint(
            usable.firstOrNull()?.latitude,
            usable.firstOrNull()?.longitude,
            state.places,
            addressNear,
            trip.startLabel
        )
        Text("↓")
        Endpoint(
            usable.lastOrNull()?.latitude,
            usable.lastOrNull()?.longitude,
            state.places,
            addressNear,
            trip.endLabel
        )
        Text("${time(trip.startedAt)} – ${time(trip.endedAt)}")
        Text(sourceLabel(trip), style = MaterialTheme.typography.labelMedium)
        if (trip.partial) {
            Text("Partial GPS observations", style = MaterialTheme.typography.bodySmall)
        }
        Text(
            "%.2f mi · %s · Top speed %.0f mph".format(
                trip.distanceMeters / 1609.344,
                duration(trip.endedAt - trip.startedAt),
                trip.maxSpeedMps * 2.236936
            )
        )
        Text(
            "${points.size} GPS points matched to this trip · " +
                "${trip.samples} moving observations in the summary.",
            style = MaterialTheme.typography.bodySmall
        )
        if (routeHasGaps(trip, usable.map { it.capturedAt }, segments.size)) {
            Text(
                if (usable.size < 2) {
                    "Route points unavailable or still synchronizing. Reopen trips after sync " +
                        "completes."
                } else {
                    "Route is incomplete. Only recorded sections are shown."
                },
                style = MaterialTheme.typography.bodySmall
            )
        }
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Icon(
                Icons.Outlined.Map,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(18.dp)
            )
            Text(
                "Tap preview to open interactive map",
                color = MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.labelLarge
            )
        }
    }
}

/** Returns how the route was produced: recorded GPS, normalized GPS or road matched. */
private fun sourceLabel(trip: HouseholdTrip) = when {
    trip.matched -> "Road matched"
    trip.normalized && trip.processing -> "GPS normalized · Road matching pending"
    trip.normalized -> "GPS normalized"
    else -> "Recorded GPS"
}

/**
 * Returns true if the route has too few points, is split into segments, or starts or ends more than
 * two minutes from the trip times.
 */
private fun routeHasGaps(trip: HouseholdTrip, times: List<Long>, segmentCount: Int): Boolean {
    if (times.size < 2 || segmentCount > 1) return true
    return times.first() - trip.startedAt > 120000 || trip.endedAt - times.last() > 120000
}

/** Stop card: place, times, duration, and a Save Place button if it isn't a saved place. */
@Composable
private fun StopCard(
    stop: TripStop,
    places: List<HouseholdPlace>,
    addressNear: AddressNear?,
    onSave: () -> Unit
) {
    val overnight = date(stop.startedAt) != date(stop.endedAt)
    val from = (if (overnight) date(stop.startedAt) + " " else "") + time(stop.startedAt)
    val to = (if (overnight) date(stop.endedAt) + " " else "") + time(stop.endedAt)
    val span = if (stop.gapMillis > 0) " span" else ""
    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("At", style = MaterialTheme.typography.titleSmall)
        Endpoint(stop.latitude, stop.longitude, places, addressNear)
        Text("$from – $to · ${duration(stop.endedAt - stop.startedAt)}$span")
        if (stop.gapMillis > 0) {
            Text(
                "${duration(
                    stop.gapMillis
                )} without observations; location during those gaps is unknown.",
                style = MaterialTheme.typography.bodySmall
            )
        }
        if (PlaceGeometry.matchingPlace(stop.latitude, stop.longitude, places) == null) {
            TextButton(onClick = onSave) { Text("Save Place") }
        }
    }
}

/** Full-screen trip view with an interactive route map. */
@Composable
private fun TripDetailsDialog(
    trip: HouseholdTrip,
    state: AppState,
    mapsEnabled: Boolean,
    addressNear: AddressNear?,
    onClose: () -> Unit
) {
    Dialog(
        onDismissRequest = onClose,
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        Surface(
            Modifier.fillMaxWidth().fillMaxHeight(0.92f).padding(12.dp),
            shape = MaterialTheme.shapes.large
        ) {
            Column(
                Modifier.padding(12.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                val segments = TripTimeline.route(TripTimeline.forTrip(trip, state.tripPoints))
                val route = segments.flatten()
                TextButton(onClick = onClose) { Text("Close") }
                Text(date(trip.startedAt), style = MaterialTheme.typography.titleLarge)
                if (mapsEnabled && segments.isNotEmpty()) {
                    TripRouteMap(segments, Modifier.fillMaxWidth().height(380.dp))
                }
                Endpoint(
                    route.firstOrNull()?.latitude,
                    route.firstOrNull()?.longitude,
                    state.places,
                    addressNear,
                    trip.startLabel
                )
                Text("↓")
                Endpoint(
                    route.lastOrNull()?.latitude,
                    route.lastOrNull()?.longitude,
                    state.places,
                    addressNear,
                    trip.endLabel
                )
                Text(
                    "${time(
                        trip.startedAt
                    )} – ${time(trip.endedAt)} · ${duration(trip.endedAt - trip.startedAt)}"
                )
                Text(
                    "%.2f mi · Top speed %.0f mph".format(
                        trip.distanceMeters / 1609.344,
                        trip.maxSpeedMps * 2.236936
                    )
                )
                Text("Only available recorded sections are shown; gaps are not connected.")
            }
        }
    }
}

/** Asks for a name and saves a stop as a new place. */
@Composable
private fun SavePlaceDialog(onSave: (String) -> Unit, onDismiss: () -> Unit) {
    var placeName by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Save Place") },
        text = {
            OutlinedTextField(placeName, {
                placeName = it.take(80)
            }, label = { Text("Place name") })
        },
        confirmButton = {
            TextButton(enabled = placeName.isNotBlank(), onClick = {
                onSave(placeName.trim())
                onDismiss()
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } }
    )
}
