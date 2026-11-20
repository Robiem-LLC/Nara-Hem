package com.robiem.narahem.ui.map

import android.content.Context
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.filled.Map
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.robiem.narahem.MemberDetailRow
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.data.settings.MapCamera
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.ZoneTimes
import com.robiem.narahem.ui.components.ExternalDirections
import com.robiem.narahem.ui.components.messageColor
import com.robiem.narahem.ui.places.PlaceGeometry
import com.robiem.narahem.ui.settings.RoundProfilePhoto
import com.robiem.narahem.ui.theme.NaraHemTheme

/** Map tab connected to [MapViewModel]. */
@Composable
internal fun BoxScope.MapTab(
    state: AppState,
    screen: MapScreenState,
    loadMap: Boolean,
    nearbyAddresses: Map<String, String>,
    selectedMemberId: String?,
    landscape: Boolean,
    sidePanel: Dp,
    model: MapViewModel,
    onSelectMember: (String?) -> Unit,
    onAskConsent: () -> Unit,
    onOpenTab: (String) -> Unit,
    onViewTrips: (memberId: String) -> Unit,
    onClearTrips: () -> Unit,
    hasLocation: () -> Boolean
) = MapContent(
    state, screen, loadMap, nearbyAddresses, selectedMemberId, landscape, sidePanel,
    onSelectMember = onSelectMember,
    onAskConsent = onAskConsent,
    onOpenTab = onOpenTab,
    onViewTrips = onViewTrips,
    onClearTrips = onClearTrips,
    onCenterOnPhone = { if (hasLocation()) model.centerMapOnPhone(force = true) },
    onCameraMoved = model::rememberMapCamera
)

/** Map tab UI: the map, status card and member drawer. Stateless; every action is a callback. */
@Composable
internal fun BoxScope.MapContent(
    state: AppState,
    screen: MapScreenState,
    loadMap: Boolean,
    nearbyAddresses: Map<String, String>,
    selectedMemberId: String?,
    landscape: Boolean,
    sidePanel: Dp,
    onSelectMember: (String?) -> Unit,
    onAskConsent: () -> Unit,
    onOpenTab: (String) -> Unit,
    onViewTrips: (memberId: String) -> Unit,
    onClearTrips: () -> Unit,
    onCenterOnPhone: () -> Unit,
    onCameraMoved: (MapCamera) -> Unit
) {
    val context = LocalContext.current
    if (loadMap) {
        MapSurface(
            state.fix,
            Modifier.fillMaxSize().padding(end = if (landscape) sidePanel else 0.dp),
            focusKey = screen.focusKey,
            onError = {
                screen.mapError = it
            },
            members = state.people,
            ownPersonId = state.account?.id,
            focusPersonId = screen.focusMember,
            places = state.places,
            occludedBottom = if (landscape) 0.dp else screen.drawerHeightDp.dp,
            onViewportChanged = { lat, lon, zoom -> onCameraMoved(MapCamera(lat, lon, zoom)) }
        )
    } else {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Button(onClick = onAskConsent) { Text("Open household map") }
        }
    }
    MapStatusCard(state, screen, landscape, sidePanel, onOpenTab)
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val chosenPerson = state.people.firstOrNull {
            it.id ==
                selectedMemberId
        }
        val lowerBound = 104.dp
        val upperBound = (maxHeight - 112.dp).coerceAtLeast(lowerBound)
        val sheetHeight = screen.drawerHeightDp.dp.coerceIn(lowerBound, upperBound)
        val density = LocalDensity.current
        Surface(
            modifier = if (landscape) {
                Modifier.align(Alignment.CenterEnd).width(sidePanel).fillMaxHeight()
            } else {
                Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(sheetHeight)
            },
            shape = if (landscape) {
                RoundedCornerShape(topStart = 22.dp, bottomStart = 22.dp)
            } else {
                RoundedCornerShape(topStart = 22.dp, topEnd = 22.dp)
            },
            color = MaterialTheme.colorScheme.background,
            tonalElevation = 0.dp
        ) {
            Column(Modifier.fillMaxSize().padding(horizontal = 16.dp, vertical = 8.dp)) {
                DrawerHeader(
                    state,
                    screen,
                    landscape,
                    onSelectMember,
                    onClearTrips,
                    chosenPerson,
                    lowerBound,
                    upperBound,
                    density
                )
                Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState())) {
                    if (chosenPerson != null) {
                        MemberDetails(state, nearbyAddresses, onViewTrips, context, chosenPerson)
                    } else {
                        MemberList(
                            state,
                            screen,
                            nearbyAddresses,
                            landscape,
                            onSelectMember,
                            onCenterOnPhone
                        )
                    }
                }
            }
        }
    }
}

/** Card over the map for setup steps, map errors and messages. */
@Composable
private fun BoxScope.MapStatusCard(
    state: AppState,
    screen: MapScreenState,
    landscape: Boolean,
    sidePanel: Dp,
    onOpenTab: (String) -> Unit
) {
    Column(
        Modifier.align(Alignment.TopCenter).fillMaxWidth()
            .padding(end = if (landscape) sidePanel else 0.dp).padding(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        if (state.deviceStatus != "ready" ||
            state.message.isNotBlank() || screen.mapError.isNotBlank()
        ) {
            Surface(shape = RoundedCornerShape(12.dp), tonalElevation = 4.dp) {
                Column(
                    Modifier.fillMaxWidth().padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    if (state.deviceStatus != "ready") {
                        Text(
                            "Location setup: " + state.deviceStatus.replace('-', ' '),
                            style = MaterialTheme.typography.titleMedium
                        )
                        Text(
                            "Everyone in the household " +
                                "stays listed while a " + "device is awaiting " + "approval.",
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                    if (screen.mapError.isNotBlank()) {
                        Text(screen.mapError, color = MaterialTheme.colorScheme.error)
                    }
                    if (state.message.isNotBlank()) {
                        Text(
                            state.message,
                            color = messageColor(state.error),
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                    if (state.deviceStatus != "ready") {
                        TextButton(onClick = { onOpenTab("settings") }) {
                            Text("Complete setup")
                        }
                    }
                }
            }
        }
    }
}

/** Drawer handle and title. Dragging resizes the drawer. */
@Composable
private fun ColumnScope.DrawerHeader(
    state: AppState,
    screen: MapScreenState,
    landscape: Boolean,
    onSelectMember: (String?) -> Unit,
    onClearTrips: () -> Unit,
    chosenPerson: HouseholdPerson?,
    lowerBound: Dp,
    upperBound: Dp,
    density: Density
) {
    Column(
        Modifier.fillMaxWidth()
            .then(
                if (landscape) {
                    Modifier
                } else {
                    Modifier.pointerInput(upperBound, density) {
                        detectVerticalDragGestures { change, pixels ->
                            val next = with(density) {
                                (screen.drawerHeightDp.dp - pixels.toDp())
                                    .coerceIn(lowerBound, upperBound)
                            }
                            change.consume()
                            screen.drawerHeightDp = next.value
                            screen.sheetExpanded = screen.drawerHeightDp > 210f
                        }
                    }.clickable {
                        screen.drawerHeightDp =
                            if (screen.drawerHeightDp < 260f) 355f else 130f
                        screen.sheetExpanded = screen.drawerHeightDp > 210f
                    }
                }
            ),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        if (!landscape) Text("━━━", color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            if (chosenPerson == null) {
                Text("Household", style = MaterialTheme.typography.titleMedium)
                Text(
                    state.people.size.toString() +
                        " members" +
                        if (landscape) {
                            ""
                        } else if (screen.sheetExpanded) {
                            " ▲"
                        } else {
                            " ▼"
                        }
                )
            } else {
                TextButton(onClick = {
                    onSelectMember(null)
                    screen.selectedTripId = null
                    onClearTrips()
                    screen.sheetExpanded = true
                    screen.drawerHeightDp = 300f
                }) { Text("‹ Household") }
                Text("Member details", style = MaterialTheme.typography.titleSmall)
            }
        }
    }
}

/** Details for the selected member: location, freshness, battery, trips and directions. */
@Composable
private fun ColumnScope.MemberDetails(
    state: AppState,
    nearbyAddresses: Map<String, String>,
    onViewTrips: (memberId: String) -> Unit,
    context: Context,
    chosenPerson: HouseholdPerson
) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        RoundProfilePhoto(chosenPerson.photo, chosenPerson.name, size = 56.dp)
        Spacer(Modifier.width(12.dp))
        Column {
            Text(chosenPerson.name, style = MaterialTheme.typography.titleLarge)
            val where = if (chosenPerson.latitude != null && chosenPerson.longitude != null) {
                PlaceGeometry.matchingPlace(
                    chosenPerson.latitude,
                    chosenPerson.longitude,
                    state.places,
                    chosenPerson.accuracy
                        ?: 25.0
                )?.name
                    ?: nearbyAddresses[chosenPerson.id]
                    ?: PlaceGeometry.label(
                        chosenPerson.latitude,
                        chosenPerson.longitude,
                        state.places
                    )
            } else {
                "Location not available"
            }
            Text(where, style = MaterialTheme.typography.bodySmall)
            Text(
                if (chosenPerson.capturedAt == 0L) {
                    "No shared GPS yet"
                } else {
                    "Last update " +
                        ZoneTimes.format(
                            chosenPerson.capturedAt,
                            chosenPerson.timeZone,
                            withDate = true
                        )
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
    chosenPerson.accuracy?.takeIf {
        it.isFinite()
    }?.let {
        MemberDetailRow("Accuracy", "${it.toInt()} m")
    }
    chosenPerson.speedMps?.let {
        MemberDetailRow(
            "Speed",
            "${"%.0f".format(
                it * 2.23694
            )} mph"
        )
    }
    chosenPerson.batteryPct?.let {
        MemberDetailRow(
            "Battery",
            "$it%" +
                if (chosenPerson.charging == true) " · Charging" else ""
        )
    }
    Row(
        Modifier.fillMaxWidth().padding(vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Button(onClick = { onViewTrips(chosenPerson.id) }) {
            Text("View trips")
        }
        if (chosenPerson.latitude != null && chosenPerson.longitude != null) {
            OutlinedButton(onClick = {
                ExternalDirections.open(context, chosenPerson.latitude, chosenPerson.longitude)
            }) { Text("Directions") }
        }
    }
    if (chosenPerson.latitude == null) {
        Text("Waiting for location.", style = MaterialTheme.typography.bodySmall)
    } else {
        LocationFreshness.of(
            chosenPerson
        ).note?.let { note ->
            Text(note, style = MaterialTheme.typography.bodySmall)
        }
    }
}

/** List of members; tapping one selects and follows them. */
@Composable
private fun ColumnScope.MemberList(
    state: AppState,
    screen: MapScreenState,
    nearbyAddresses: Map<String, String>,
    landscape: Boolean,
    onSelectMember: (String?) -> Unit,
    onCenterOnPhone: () -> Unit
) {
    val display = if (landscape || screen.sheetExpanded) state.people else state.people.take(2)
    display.forEach { person ->
        Row(
            Modifier.fillMaxWidth().clickable {
                if ((
                        person.latitude !=
                            null && person.longitude !=
                            null
                        ) || person.id ==
                    state.account?.id
                ) {
                    if (person.id == state.account?.id) onCenterOnPhone()
                    screen.focusMember = person.id
                    screen.focusKey++
                    onSelectMember(person.id)
                    screen.selectedTripId = null
                    screen.sheetExpanded = true
                    screen.drawerHeightDp = 380f
                }
            }.padding(vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            RoundProfilePhoto(person.photo, person.name, size = 42.dp)
            Spacer(Modifier.width(12.dp))
            Column {
                Text(person.name, style = MaterialTheme.typography.titleSmall)
                val label = if (person.latitude == null || person.longitude == null) {
                    "Waiting for location"
                } else {
                    val where =
                        PlaceGeometry.matchingPlace(
                            person.latitude,
                            person.longitude,
                            state.places,
                            person.accuracy
                                ?: 25.0
                        )?.name
                            ?: nearbyAddresses[person.id]
                            ?: PlaceGeometry.label(person.latitude, person.longitude, state.places)
                    where + LocationFreshness.of(person).suffix
                }
                Text(
                    label,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                val telemetry = listOfNotNull(
                    person.batteryPct?.let {
                        "Battery $it%" +
                            if (person.charging == true) " (charging)" else ""
                    },
                    person.speedMps?.takeIf {
                        it >=
                            1.5
                    }?.let {
                        "Speed ${"%.0f".format(
                            it * 2.23694
                        )} mph"
                    }
                ).joinToString(" · ")
                if (telemetry.isNotBlank()) {
                    Text(
                        telemetry,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                person.tripMaxSpeedMps?.let { top ->
                    Text(
                        "Traveling · Trip top: ${"%.0f".format(
                            top * 2.23694
                        )} mph" +
                            (
                                person.tripDistanceMeters?.let {
                                    " · ${"%.1f".format(
                                        it / 1609.344
                                    )} mi"
                                }
                                    ?: ""
                                ),
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                if (person.tripMaxSpeedMps == null) {
                    person.recentTripMaxSpeedMps?.let { top ->
                        Text(
                            "Last trip · Observed top: ${"%.0f".format(
                                top * 2.23694
                            )} mph",
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
        }
    }
}

/** Preview of the member drawer. */
@Preview
@Composable
private fun MapDrawerPreview() {
    NaraHemTheme {
        Box {
            MapContent(
                state = AppState(
                    restoring = false,
                    deviceStatus = "ready",
                    people = listOf(HouseholdPerson("1", "Sam"), HouseholdPerson("2", "Alex"))
                ),
                screen = MapScreenState(),
                loadMap = false,
                nearbyAddresses = emptyMap(),
                selectedMemberId = null,
                landscape = false,
                sidePanel = 0.dp,
                onSelectMember = {},
                onAskConsent = {},
                onOpenTab = {},
                onViewTrips = {},
                onClearTrips = {},
                onCenterOnPhone = {},
                onCameraMoved = {}
            )
        }
    }
}
