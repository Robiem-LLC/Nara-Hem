package com.robiem.narahem.ui.places

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Directions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.robiem.narahem.data.household.HouseholdPlace
import com.robiem.narahem.data.household.PlaceMatching
import com.robiem.narahem.data.settings.MapCamera
import com.robiem.narahem.data.settings.PhoneAppSettings
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.components.AdaptiveLayout
import com.robiem.narahem.ui.components.ExternalDirections
import com.robiem.narahem.ui.components.FormSection
import com.robiem.narahem.ui.map.PlacePickerMap
import com.robiem.narahem.ui.theme.NaraHemColors
import com.robiem.narahem.ui.theme.NaraHemTheme
import com.robiem.narahem.ui.theme.cardBorder

/** Places tab connected to [PlacesViewModel]. */
@Composable
internal fun BoxScope.PlacesTab(
    state: AppState,
    editor: PlaceEditorState,
    lastCamera: MapCamera?,
    model: PlacesViewModel
) {
    PlacesContent(
        state = state,
        editor = editor,
        lastMapZoom = lastCamera?.zoom ?: PhoneAppSettings.DEFAULT_ZOOM,
        onNewPlace = { editor.beginNew(state, lastCamera) },
        onFindAddress = {
            model.findAddress(editor.search) { latitude, longitude ->
                editor.latitude = latitude.toString()
                editor.longitude = longitude.toString()
                editor.recenter++
            }
        },
        onSave = {
            model.savePlace(
                editor.name.trim(),
                editor.latitude.toDouble(),
                editor.longitude.toDouble(),
                editor.radius.toDoubleOrNull() ?: 0.0,
                editor.editing,
                // Everyone sharing their location gets a place's alerts; no per-person rules.
                emptyMap()
            ) { editor.open = false }
        },
        onDelete = { place -> model.deletePlace(place) { editor.open = false } }
    )
}

/**
 * Places tab UI: the list of saved places, or the editor when it is open. Stateless apart from
 * [editor]. [loadMap] is false in tests, where the map can't run.
 */
@Composable
internal fun BoxScope.PlacesContent(
    state: AppState,
    editor: PlaceEditorState,
    lastMapZoom: Double,
    onNewPlace: () -> Unit,
    onFindAddress: () -> Unit,
    onSave: () -> Unit,
    onDelete: (HouseholdPlace) -> Unit,
    loadMap: Boolean = true
) {
    val context = LocalContext.current
    Column(
        Modifier.align(
            Alignment.TopCenter
        ).widthIn(
            max = AdaptiveLayout.READABLE_WIDTH_DP.dp
        ).fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        if (!editor.open) {
            PlaceList(state, editor, onNewPlace, context)
        } else {
            PlaceEditor(state, editor, lastMapZoom, onFindAddress, onSave, onDelete, loadMap)
        }
    }
}

/** List of saved places with directions buttons and an Add button. */
@Composable
private fun ColumnScope.PlaceList(
    state: AppState,
    editor: PlaceEditorState,
    onNewPlace: () -> Unit,
    context: Context
) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text("Places", style = MaterialTheme.typography.headlineMedium)
        Button(onClick = onNewPlace, enabled = state.deviceStatus == "ready") {
            Text("Add a Place", fontWeight = FontWeight.Bold)
        }
    }
    Text(
        "The circle determines when someone " + "arrives or departs.",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant
    )
    if (state.places.isEmpty()) {
        Text("No saved places yet. Add Home, " + "School, Work, or anywhere you " + "visit often.")
    }
    Column(
        Modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        state.places.forEach { place ->
            ElevatedCard(
                Modifier.fillMaxWidth().cardBorder().clickable(enabled = !state.busy) {
                    editor.editing = place
                    editor.name = place.name
                    editor.latitude = place.latitude.toString()
                    editor.longitude = place.longitude.toString()
                    editor.radius = place.radius.toInt().toString()
                    editor.alerts = place.alerts
                    editor.search = ""
                    editor.recenter = 0
                    editor.showCoordinates = false
                    editor.step = "map"
                    editor.open = true
                }
            ) {
                Row(
                    Modifier.fillMaxWidth().padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("⌂", style = MaterialTheme.typography.headlineMedium)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(place.name, style = MaterialTheme.typography.titleMedium)
                        val overlaps = state.places.filter {
                            it.id !=
                                place.id &&
                                PlaceMatching.distance(
                                    place.latitude,
                                    place.longitude,
                                    it.latitude,
                                    it.longitude
                                ) <
                                place.radius + it.radius
                        }
                        if (overlaps.isNotEmpty()) {
                            Text(
                                "Overlaps " +
                                    overlaps.joinToString {
                                        it.name
                                    } + ". Edit the boundary or delete a duplicate.",
                                color = MaterialTheme.colorScheme.error,
                                style = MaterialTheme.typography.bodySmall
                            )
                        }
                        Text(
                            "${place.radius.toInt()} m radius · ${"%.5f".format(
                                place.latitude
                            )}, ${"%.5f".format(
                                place.longitude
                            )}",
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                    Spacer(Modifier.width(8.dp))
                    OutlinedButton(
                        onClick = {
                            ExternalDirections.open(context, place.latitude, place.longitude)
                        },
                        modifier = Modifier.heightIn(min = 48.dp),
                        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp)
                    ) {
                        Icon(
                            Icons.Filled.Directions,
                            contentDescription = null,
                            modifier = Modifier.size(18.dp)
                        )
                        Spacer(Modifier.width(6.dp))
                        Text("Directions")
                    }
                }
            }
        }
    }
}

/** Editor toolbar with Cancel and Next or Save. */
@Composable
private fun ColumnScope.PlaceEditorHeader(
    state: AppState,
    editor: PlaceEditorState,
    onSave: () -> Unit,
    validPosition: Boolean,
    validRadius: Boolean
) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        TextButton(onClick = {
            editor.open = false
        }, enabled = !state.busy) { Text("Cancel") }
        Text(
            if (editor.editing == null) {
                "Add place"
            } else {
                "Edit place"
            },
            Modifier.weight(1f),
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.titleMedium
        )
        if (editor.step == "map") {
            TextButton(
                onClick = {
                    editor.step = "details"
                },
                enabled = validPosition && validRadius
            ) {
                Text("Next")
            }
        } else {
            TextButton(
                onClick = {
                    onSave()
                },
                enabled = !state.busy && editor.name.isNotBlank() && validPosition && validRadius
            ) { Text("Save") }
        }
    }
}

/**
 * First editor step: position and size the place's circle by moving the map or searching. It
 * doesn't scroll, so dragging the map always moves the map; the map takes the space left over.
 */
@OptIn(ExperimentalMaterial3Api::class) // the slider's custom pill handle and track
@Composable
private fun ColumnScope.PlaceBoundaryStep(
    editor: PlaceEditorState,
    lastMapZoom: Double,
    onFindAddress: () -> Unit,
    radiusValue: Double,
    validPosition: Boolean,
    loadMap: Boolean
) {
    FormSection(if (editor.editing == null) "New place · 1 of 2" else "Edit boundary · 1 of 2") {
        Text(
            "Search for an address or business, or drag the map to position the center.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                editor.search,
                { editor.search = it },
                label = { Text("Search address or business") },
                singleLine = true,
                modifier = Modifier.weight(1f)
            )
            Spacer(Modifier.width(6.dp))
            TextButton(onClick = onFindAddress, enabled = editor.search.isNotBlank()) {
                Text("Find")
            }
        }
    }
    if (loadMap) {
        PlacePickerMap(
            latitude = editor.latitude.toDoubleOrNull() ?: 0.0,
            longitude = editor.longitude.toDoubleOrNull() ?: 0.0,
            radiusMeters = radiusValue.coerceIn(1.0, 10000.0),
            initialZoom = if (editor.editing == null) 16.0 else lastMapZoom,
            recenterKey = editor.recenter,
            onCenterChanged = { lat, lon ->
                editor.latitude = lat.toString()
                editor.longitude = lon.toString()
            },
            modifier = Modifier.fillMaxWidth().weight(1f).heightIn(min = 160.dp)
                .clip(RoundedCornerShape(16.dp))
        )
    } else {
        Spacer(Modifier.fillMaxWidth().weight(1f))
    }
    FormSection("Boundary") {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                "Boundary radius: ${radiusValue.toInt()} metres",
                Modifier.weight(1f),
                style = MaterialTheme.typography.titleSmall
            )
            OutlinedTextField(
                editor.radius,
                { editor.radius = it.filter(Char::isDigit).take(5) },
                label = { Text("Exact (1–10,000)") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.width(150.dp)
            )
        }
        Slider(
            value = radiusValue.coerceIn(1.0, 2000.0).toFloat(),
            onValueChange = { editor.radius = it.toInt().toString() },
            valueRange = 1f..2000f,
            // A round pill handle on a plain track, not Material's newer thin line handle.
            thumb = {
                Box(
                    Modifier.size(width = 28.dp, height = 22.dp)
                        .background(MaterialTheme.colorScheme.primary, RoundedCornerShape(50))
                )
            },
            track = { state ->
                SliderDefaults.Track(
                    sliderState = state,
                    drawStopIndicator = null,
                    thumbTrackGapSize = 0.dp,
                    modifier = Modifier.height(6.dp)
                )
            }
        )
        if (radiusValue in 1.0..19.0) {
            Text(
                "Small radii are supported, but phone GPS may be less accurate than the " +
                    "selected boundary. Arrival and departure detection can be unreliable.",
                style = MaterialTheme.typography.bodySmall,
                color = NaraHemColors.Warn
            )
        }
        TextButton(onClick = { editor.showCoordinates = !editor.showCoordinates }) {
            Text((if (editor.showCoordinates) "▾ " else "▸ ") + "Advanced: exact coordinates")
        }
        if (editor.showCoordinates) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                OutlinedTextField(
                    editor.latitude,
                    { editor.latitude = it },
                    label = { Text("Latitude") },
                    singleLine = true,
                    modifier = Modifier.weight(1f)
                )
                OutlinedTextField(
                    editor.longitude,
                    { editor.longitude = it },
                    label = { Text("Longitude") },
                    singleLine = true,
                    modifier = Modifier.weight(1f)
                )
                TextButton(onClick = { editor.recenter++ }, enabled = validPosition) {
                    Text("Use")
                }
            }
        }
        Text(
            "Address searches use your phone's map service.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

/** Second editor step: name and delete. */
@Composable
private fun ColumnScope.PlaceDetailsStep(
    state: AppState,
    editor: PlaceEditorState,
    onDelete: (HouseholdPlace) -> Unit,
    radiusValue: Double
) {
    Column(
        Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        FormSection("Place details · 2 of 2") {
            OutlinedTextField(
                editor.name,
                { editor.name = it.take(80) },
                label = { Text("Name this place") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            val latitude = editor.latitude.toDoubleOrNull()?.let { "%.5f".format(it) }
            val longitude = editor.longitude.toDoubleOrNull()?.let { "%.5f".format(it) }
            Text(
                "Location: $latitude, $longitude",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text("Boundary radius: ${radiusValue.toInt()} metres")
            OutlinedButton(onClick = { editor.step = "map" }, enabled = !state.busy) {
                Text("Edit boundary")
            }
        }
        if (state.error && state.message.isNotBlank()) {
            Text(state.message, color = MaterialTheme.colorScheme.error)
        }
        editor.editing?.takeIf { state.account?.role == "admin" }?.let { place ->
            FormSection("Remove") {
                TextButton(onClick = { editor.confirmingDelete = true }, enabled = !state.busy) {
                    Text("Delete place", color = MaterialTheme.colorScheme.error)
                }
            }
            if (editor.confirmingDelete) {
                AlertDialog(
                    onDismissRequest = { editor.confirmingDelete = false },
                    title = { Text("Delete ${place.name}?") },
                    text = { Text("This removes the saved boundary and its alert preferences.") },
                    confirmButton = {
                        TextButton(onClick = {
                            editor.confirmingDelete = false
                            onDelete(place)
                        }, enabled = !state.busy) { Text("Delete") }
                    },
                    dismissButton = {
                        TextButton(onClick = { editor.confirmingDelete = false }) {
                            Text("Cancel")
                        }
                    }
                )
            }
        }
    }
}

/** Place editor: the boundary step followed by the details step. */
@Composable
private fun ColumnScope.PlaceEditor(
    state: AppState,
    editor: PlaceEditorState,
    lastMapZoom: Double,
    onFindAddress: () -> Unit,
    onSave: () -> Unit,
    onDelete: (HouseholdPlace) -> Unit,
    loadMap: Boolean
) {
    val radiusValue = editor.radius.toDoubleOrNull() ?: 0.0
    val validPosition =
        editor.latitude.toDoubleOrNull()?.let {
            it in -90.0..90.0
        } ==
            true &&
            editor.longitude.toDoubleOrNull()?.let {
                it in -180.0..180.0
            } ==
            true
    val validRadius = radiusValue in 1.0..10000.0
    PlaceEditorHeader(state, editor, onSave, validPosition, validRadius)
    if (editor.step == "map") {
        PlaceBoundaryStep(editor, lastMapZoom, onFindAddress, radiusValue, validPosition, loadMap)
    } else {
        PlaceDetailsStep(state, editor, onDelete, radiusValue)
    }
}

/** Preview of the places list. */
@Preview
@Composable
private fun PlacesPreview() {
    NaraHemTheme {
        Box {
            PlacesContent(
                state = AppState(
                    restoring = false,
                    deviceStatus = "ready",
                    places = listOf(HouseholdPlace("1", "Home", 40.0, -74.0, 100.0))
                ),
                editor = PlaceEditorState(),
                lastMapZoom = PhoneAppSettings.DEFAULT_ZOOM,
                onNewPlace = {},
                onFindAddress = {},
                onSave = {},
                onDelete = {}
            )
        }
    }
}
