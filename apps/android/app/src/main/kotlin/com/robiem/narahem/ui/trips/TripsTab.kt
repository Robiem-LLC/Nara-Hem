package com.robiem.narahem.ui.trips

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.robiem.narahem.data.household.HouseholdPerson
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.components.AdaptiveLayout
import com.robiem.narahem.ui.theme.NaraHemTheme

/** Trips tab connected to [TripsViewModel]. */
@Composable
internal fun BoxScope.TripsTab(
    state: AppState,
    selectedMemberId: String?,
    onSelectMember: (String) -> Unit,
    loadMap: Boolean,
    addressLookup: Boolean,
    model: TripsViewModel,
    onSavePlace: (name: String, latitude: Double, longitude: Double) -> Unit
) {
    val latestSelected by rememberUpdatedState(selectedMemberId)
    LaunchedEffect(state.tripDays, state.tripsForMember) {
        model.refreshTripsWhileOpen { latestSelected }
    }
    TripsContent(
        state = state,
        mapsEnabled = loadMap,
        addressNear = if (addressLookup) model::addressNear else null,
        onSelectMember = { id ->
            onSelectMember(id)
            model.loadMemberTrips(id)
        },
        onDays = { days ->
            (selectedMemberId ?: state.people.firstOrNull()?.id)?.let {
                model.loadMemberTrips(it, days)
            }
        },
        onSavePlace = onSavePlace
    )
}

/** Trips tab UI: member picker and the trips list. Stateless; selections are callbacks. */
@Composable
internal fun BoxScope.TripsContent(
    state: AppState,
    mapsEnabled: Boolean,
    addressNear: AddressNear?,
    onSelectMember: (String) -> Unit,
    onDays: (Int) -> Unit,
    onSavePlace: (name: String, latitude: Double, longitude: Double) -> Unit
) {
    Column(
        Modifier.align(Alignment.TopCenter)
            .widthIn(max = AdaptiveLayout.READABLE_WIDTH_DP.dp)
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text("Trips and stops", style = MaterialTheme.typography.headlineMedium)
        Text(
            "Choose a household member to view trip history.",
            style = MaterialTheme.typography.bodySmall
        )
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(state.people.size) { index ->
                val person = state.people[index]
                FilterChip(
                    selected = person.id == state.tripsForMember,
                    onClick = { onSelectMember(person.id) },
                    label = { Text(person.name) }
                )
            }
        }
        if (state.tripsLoading && state.trips.isEmpty()) CircularProgressIndicator()
        if (state.tripsError.isNotBlank()) {
            Text(state.tripsError, color = MaterialTheme.colorScheme.error)
        }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            TripTimelineCards(
                state,
                mapsEnabled,
                addressNear = addressNear,
                onDays = onDays,
                onSavePlace = onSavePlace
            )
        }
    }
}

/** Preview of a day of trips. */
@Preview
@Composable
private fun TripsPreview() {
    NaraHemTheme {
        Box {
            TripsContent(
                state = AppState(
                    restoring = false,
                    people = listOf(HouseholdPerson("1", "Sam"), HouseholdPerson("2", "Alex")),
                    tripsForMember = "1",
                    tripsError = "Could not load trip history. Retry when online."
                ),
                mapsEnabled = false,
                addressNear = null,
                onSelectMember = {},
                onDays = {},
                onSavePlace = { _, _, _ -> }
            )
        }
    }
}
