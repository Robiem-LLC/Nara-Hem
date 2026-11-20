// The household map: members, saved places and their editor, refreshed while open.

import { createHouseholdMap, householdAvatarFan } from '../maps.mjs';
import * as C from '../crypto.mjs';
import { matchingPlace } from '../locations.mjs';
import {
  addressesEnabled,
  forwardAddress,
  metersBetween,
  providerName,
  requestAddressConsent,
  reverseAddress,
} from './addresses.mjs';
import {
  acceptSignedPairing,
  bind,
  button,
  deviceApi,
  el,
  node,
  reconcileRevokedMembership,
  registration,
  roster,
  run,
  save,
  showTemplate,
  stop,
  sync,
} from './core.mjs';
import { devices } from './devices-screen.mjs';
import { placeState, publish } from './records.mjs';
import { state } from './state.mjs';
import { tripScreen } from './trips-screen.mjs';
import { zoneTime } from './zones.mjs';

/** Place thumbnail maps, reused between refreshes. */
export const placeTileMaps = new Map();

/** Shows a map with a message. */
export async function emptyMap(text) {
  const epoch = state.renderEpoch;
  const targetView = state.view;
  showTemplate('screen-empty-map');
  el('empty-map-message').textContent = text;
  const config = await state.api('/api/maps');
  if (epoch !== state.renderEpoch || state.view !== targetView || !targetView.isConnected) return;
  state.map = createHouseholdMap(el('household-map'), config, (e) => state.notice(e.message));
  await state.map.load();
}

/**
 * Shows the main screen: first-device setup or pairing if this browser isn't ready, otherwise the
 * map, places or trips.
 */
export async function screen() {
  const epoch = ++state.renderEpoch;
  stop();
  const d = await deviceApi('/api/device');
  const h = await state.api('/api/household');
  if (epoch !== state.renderEpoch) return;
  if (!state.vault.anchor && h.revision === 0 && state.user.role === 'admin') {
    await firstDeviceScreen();
    return;
  }
  if (!state.vault.anchor && h.revision > 0) {
    await pairingScreen(epoch, d, h);
    return;
  }
  if (d.status !== 'approved') {
    showTemplate('screen-waiting-approval');
    button('check-approval', screen);
    return;
  }
  await sync();
  if (state.user.role === 'admin' && state.vault.anchor && epoch === state.renderEpoch) {
    await adminUpkeep(epoch);
  }
  if (epoch !== state.renderEpoch) return;
  if (state.mode === 'trips') {
    await tripScreen(epoch);
    return;
  }
  const mapConfig = await state.api('/api/maps');
  if (epoch !== state.renderEpoch) return;
  state.activeMapConfig = mapConfig;
  requestAddressConsent();
  showTemplate('screen-household-map');
  state.editingPlaceId = null;
  setupMapControls(mapConfig);
  setupPlaceEditor();
  await refresh();
  if (epoch !== state.renderEpoch) return;
  await devices();
  if (epoch !== state.renderEpoch) return;
  showModePanes();
  if (state.mode === 'map') {
    const target = state.map;
    try {
      await target.load();
      target.resize();
      target._narahemFramed = false;
      await refresh();
      el('load-tiles').hidden = true;
    } catch (e) {
      mapError(e);
    }
  }
  state.timer = setInterval(() => {
    if (document.visibilityState === 'visible') {
      refresh().catch((e) => {
        if (epoch !== state.renderEpoch) return;
        if (state.map) state.markers.forEach((m) => state.map.removeLayer(m));
        state.markers = [];
        if (el('location-list')) el('location-list').replaceChildren();
        if (el('map-status')) el('map-status').textContent = `Updates unavailable: ${e.message}`;
      });
    }
  }, 15000);
}

/**
 * Registers the first device of a new household, verified by the setup token or an emailed code.
 */
async function firstDeviceScreen() {
  const bootstrap = async (verification) => {
    const body = {
      domain: 'narahem.roster.v1',
      household: state.vault.household,
      revision: 1,
      previous: '',
      signer: state.vault.id,
      devices: [C.identity(state.vault)],
      issued_at: Math.floor(Date.now() / 1000),
    };
    await deviceApi('/api/roster', 'POST', {
      body,
      signature: C.sign(body, state.vault.signing_secret),
      ...verification,
    });
    state.vault.anchor = state.vault.signing_key;
    await save();
    await screen();
  };
  const cached = sessionStorage.getItem('narahem.setup-bootstrap');
  showTemplate('screen-first-device');
  if (cached) {
    sessionStorage.removeItem('narahem.setup-bootstrap');
    try {
      await bootstrap({ bootstrap_token: cached });
      return;
    } catch (error) {
      state.notice('Initial device setup needs confirmation: ' + error.message);
    }
  }
  button('request-first-device-code', async () => {
    await state.api('/api/device-bootstrap/email/request', 'POST', { device_id: state.vault.id });
    state.notice('Verification code sent to the administrator email. It expires in ten minutes.');
  });
  bind('email-bootstrap', async (data) =>
    bootstrap({ bootstrap_email_code: data['device-email-code'] }),
  );
  bind('bootstrap-device', async (data) =>
    bootstrap({ bootstrap_token: data['bootstrap-device-token'] }),
  );
}

/**
 * Shows the pairing screen until the server approves this browser, then verifies the signed
 * approval.
 */
async function pairingScreen(epoch, d, h) {
  let errorText = '';
  if (d.status === 'approved') {
    try {
      await acceptSignedPairing(h);
      if (epoch === state.renderEpoch) await screen();
      return;
    } catch (error) {
      errorText = error.message;
    }
  }
  const code = C.pairingCode(registration(), h.anchor);
  showTemplate('screen-pairing');
  el('pairing-code').textContent = code;
  el('pairing-status').textContent =
    d.status === 'approved'
      ? errorText || 'Waiting for the signed approval…'
      : 'Waiting for trusted approval. This screen updates automatically.';
  bind('trust-root', async (data) => {
    const r = await deviceApi('/api/roster');
    if (!r.anchor || C.hash(C.unb64(r.anchor)) !== data['root-fingerprint'].trim()) {
      throw new Error('Household fingerprint does not match.');
    }
    state.vault.anchor = r.anchor;
    await save();
    await screen();
  });
  button('check-approval', screen);
  if (d.status !== 'approved') {
    state.timer = setInterval(async () => {
      if (epoch !== state.renderEpoch || !state.vault) return;
      try {
        const updated = await deviceApi('/api/device');
        if (updated.status === 'approved') await screen();
      } catch (error) {
        if (epoch === state.renderEpoch && el('pairing-status')) {
          el('pairing-status').textContent = error.message;
        }
      }
    }, 8000);
  }
}

/**
 * Removes revoked devices from the roster and adds the enrollment signer if missing. Runs on each
 * admin visit.
 */
async function adminUpkeep(epoch) {
  // Revocations go first: adding a signer while revoked devices are still listed gets rejected.
  try {
    if (await reconcileRevokedMembership()) {
      state.notice('Revoked devices removed from signed encryption membership.');
    }
  } catch (error) {
    state.notice('Household membership needs attention: ' + error.message);
  }
  if (epoch !== state.renderEpoch) return;
  try {
    const service = await state.api('/api/enrollment/signer', 'POST', {});
    if (!state.chain.current.devices.some((d) => d.id === service.id)) {
      if (
        service.status !== 'pending' ||
        service.id !== '00000000000000000000000000000000' ||
        service.account_id !== state.user.id ||
        !C.verify(service.registration, service.registration_signature, service.signing_key)
      ) {
        throw new Error('Enrollment service identity failed validation.');
      }
      await roster([
        ...state.chain.current.devices,
        {
          id: service.id,
          account_id: service.account_id,
          signing_key: service.signing_key,
          box_key: service.box_key,
        },
      ]);
    }
  } catch (error) {
    state.notice('Phone email enrollment not yet activated: ' + error.message);
  }
}

/** Shows whether address lookups are enabled. */
function showAddressStatus() {
  if (el('address-provider-status')) {
    el('address-provider-status').textContent = addressesEnabled()
      ? 'On · ' + providerName()
      : 'Off';
  }
}

/** Shows a map error and the OpenStreetMap fallback button. */
function mapError(e) {
  state.notice(e.message);
  if (el('fallback-map')) el('fallback-map').hidden = false;
}

/**
 * Creates the map and connects its buttons: load, OpenStreetMap fallback, fit, refresh and the
 * address lookup switch.
 */
function setupMapControls(mapConfig) {
  const googleMap = mapConfig.provider === 'google';
  const mapProvider = googleMap ? 'Google' : 'OpenStreetMap';
  for (const name of state.view.querySelectorAll('[data-slot="provider-name"]')) {
    name.textContent = mapProvider;
  }
  el('load-tiles').textContent = googleMap ? 'Load Google Maps' : 'Load OpenStreetMap tiles';
  showAddressStatus();
  button('address-privacy-toggle', async () => {
    const approved = confirm(
      'Allow ' +
        providerName() +
        ' to receive precise coordinates from this browser for street addresses on maps and ' +
        'trip endpoints? OK enables; Cancel disables.',
    );
    localStorage.setItem('narahem.address-lookup', approved ? 'on' : 'off');
    showAddressStatus();
    await refresh();
  });
  state.map = createHouseholdMap(el('household-map'), mapConfig, mapError);
  button('load-tiles', async () => {
    const target = state.map;
    const load = el('load-tiles');
    load.disabled = true;
    load.textContent = 'Loading map…';
    try {
      await target.load();
      if (state.map !== target) return;
      await refresh();
      load.hidden = true;
      state.notice('Map loaded.');
    } catch (e) {
      if (state.map === target) {
        load.textContent = googleMap ? 'Retry Google Maps' : 'Retry OpenStreetMap';
        mapError(e);
      }
    } finally {
      load.disabled = false;
    }
  });
  button('fallback-map', async () => {
    const previous = state.map;
    state.markers.forEach((m) => previous.removeLayer(m));
    state.markers = [];
    previous.remove();
    state.activeMapConfig = { provider: 'openstreetmap' };
    state.map = createHouseholdMap(el('household-map'), state.activeMapConfig, mapError);
    showAddressStatus();
    await state.map.load();
    el('load-tiles').hidden = true;
    el('fallback-map').hidden = true;
    el('map-provider-note').textContent = 'Map tiles send the viewed region to OpenStreetMap.';
    await refresh();
    state.notice('OpenStreetMap loaded.');
  });
  button('fit-users', () => {
    state.map._narahemFramed = false;
    return refresh();
  });
  button('refresh-map', async () => {
    await refresh();
    await devices();
  });
}

/** Connects the place form: address search, centre and radius fields, and the preview map. */
function setupPlaceEditor() {
  const latField = el('place-lat');
  const lonField = el('place-lon');
  const radiusField = el('place-radius');
  const slider = el('place-radius-slider');
  state.refreshPlacePreview = refreshPlacePreview;
  button('find-place-address', () => findSavedPlaceAddress(state.activeMapConfig.provider));
  button('find-place-osm', () => findSavedPlaceAddress('openstreetmap'));
  radiusField.addEventListener('input', () => {
    const n = Number(radiusField.value);
    if (Number.isFinite(n) && n >= 1 && n <= 2000) slider.value = String(n);
    state.refreshPlacePreview().catch(() => {});
  });
  slider.addEventListener('input', () => {
    radiusField.value = slider.value;
    state.refreshPlacePreview().catch(() => {});
  });
  for (const input of [latField, lonField]) {
    input.addEventListener('change', () =>
      state.refreshPlacePreview().catch((error) => state.notice(error.message)),
    );
  }
  bind('place-form', savePlaceForm);
  button('add-place', () => {
    resetPlaceEditor();
    openPlaceEditor();
    el('place-name').focus();
  });
  button('cancel-place-edit', () => {
    resetPlaceEditor();
    el('place-address').value = '';
    el('place-radius-slider').value = '100';
    el('place-address-status').textContent = '';
  });
}

/** Shows the place form, hiding the Add a place button. */
function openPlaceEditor() {
  el('place-editor').hidden = false;
  el('add-place').hidden = true;
  // The preview map may have been drawn while hidden, at no size.
  state.placePreviewMap?.resize();
}

/** Resets the place form to adding a new place and closes it. */
function resetPlaceEditor() {
  state.editingPlaceId = null;
  state.editingPlaceRecordId = null;
  el('place-form').reset();
  el('place-editor-heading').textContent = 'Add a place';
  el('place-save-button').textContent = 'Save place';
  el('place-editor').hidden = true;
  el('add-place').hidden = false;
}

/** Redraws the preview map with the circle being edited. */
async function refreshPlacePreview() {
  const preview = el('place-preview');
  const latField = el('place-lat');
  const lonField = el('place-lon');
  if (!preview?.isConnected || !latField.value || !lonField.value) return;
  const lat = Number(latField.value);
  const lon = Number(lonField.value);
  const radius = Number(el('place-radius').value);
  if (
    !Number.isFinite(lat) ||
    !Number.isFinite(lon) ||
    Math.abs(lat) > 90 ||
    Math.abs(lon) > 180 ||
    !Number.isFinite(radius) ||
    radius < 1 ||
    radius > 10000
  ) {
    return;
  }
  if (!state.placePreviewMap) {
    state.placePreviewMap = createHouseholdMap(preview, state.activeMapConfig, (error) => {
      if (el('place-address-status')) {
        el('place-address-status').textContent = 'Map preview unavailable: ' + error.message;
      }
    });
    await state.placePreviewMap.load();
    state.placePreviewClick = state.placePreviewMap.onMapClick((latitude, longitude) => {
      latField.value = latitude.toFixed(7);
      lonField.value = longitude.toFixed(7);
      if (el('place-address-status')) {
        el('place-address-status').textContent =
          'Center moved to map point. Review the circle, then save.';
      }
      state.refreshPlacePreview().catch((error) => state.notice(error.message));
    });
  }
  const dlat = Math.max(radius / 111320, 0.00025);
  const dlon = dlat / Math.max(0.05, Math.cos((lat * Math.PI) / 180));
  state.placePreviewCircle?.remove();
  // No popup: the radius is in the field below, and a popup here could not be closed.
  state.placePreviewCircle = state.placePreviewMap.place([lat, lon], radius);
  state.placePreviewMap.resize();
  state.placePreviewMap.fitBounds(
    [
      [lat - dlat, lon - dlon],
      [lat + dlat, lon + dlon],
    ],
    { maxZoom: 17, padding: [35, 35] },
  );
}

/** Geocodes the entered address and moves the place centre there. */
async function findSavedPlaceAddress(provider) {
  const query = el('place-address').value.trim();
  const primaryLookup = el('find-place-address');
  const osmFallback = el('find-place-osm');
  const lookupStatus = el('place-address-status');
  if (query.length < 3) {
    lookupStatus.textContent = 'Enter a fuller address or landmark before searching.';
    return;
  }
  primaryLookup.disabled = osmFallback.disabled = true;
  primaryLookup.textContent = 'Searching…';
  lookupStatus.textContent = 'Searching ' + providerName(provider) + '…';
  try {
    const candidate = await forwardAddress(query, provider);
    if (!lookupStatus.isConnected) return;
    if (
      !Number.isFinite(candidate.lat) ||
      !Number.isFinite(candidate.lon) ||
      Math.abs(candidate.lat) > 90 ||
      Math.abs(candidate.lon) > 180
    ) {
      throw new Error('The address provider returned invalid coordinates.');
    }
    el('place-lat').value = String(candidate.lat);
    el('place-lon').value = String(candidate.lon);
    lookupStatus.textContent =
      'Found: ' + candidate.address + '. Verify the circle and move its center if needed.';
    osmFallback.hidden = true;
    try {
      await state.refreshPlacePreview();
    } catch (error) {
      if (lookupStatus.isConnected) {
        lookupStatus.textContent += ' Map preview unavailable: ' + error.message;
      }
    }
  } catch (error) {
    if (!lookupStatus.isConnected) return;
    lookupStatus.textContent = 'Address search failed: ' + error.message;
    if (provider === 'google') osmFallback.hidden = false;
  } finally {
    primaryLookup.disabled = osmFallback.disabled = false;
    primaryLookup.textContent = 'Find address';
  }
}

/** Saves the place form as a new or edited place. */
async function savePlaceForm(data) {
  if (!data['place-lat'] || !data['place-lon']) {
    throw new Error('Find an address or choose the exact coordinates before saving.');
  }
  const p = point(data['place-lat'], data['place-lon'], 0);
  const radius = Number(data['place-radius']);
  if (!Number.isFinite(radius) || radius < 1 || radius > 10000) throw new Error('Invalid radius.');
  const existing = state.states.find(
    (p) => p.kind === 'place' && p.entity_id === state.editingPlaceId,
  );
  if (
    state.editingPlaceId &&
    (await placeState()).manifest.places.find((p) => p.id === state.editingPlaceId)?.record_id !==
      state.editingPlaceRecordId
  ) {
    throw new Error('This place changed. Reopen it before editing.');
  }
  await publish('place', state.editingPlaceId || C.uuid(), {
    ...(existing?.data || {}),
    name: data['place-name'],
    lat: p.lat,
    lon: p.lon,
    radius,
  });
  resetPlaceEditor();
  el('place-address').value = '';
  el('place-address-status').textContent = 'Place saved. To add another, search for a new address.';
  await refresh();
  state.notice('Place saved.');
}

/** Shows only the parts of the shared template that belong to the current mode. */
function showModePanes() {
  for (const pane of state.view.querySelectorAll('[data-client-pane]')) {
    pane.hidden = pane.dataset.clientPane !== (state.mode === 'places' ? 'tools' : state.mode);
  }
  if (state.mode === 'tools') {
    const placeEditor = el('saved-places');
    if (placeEditor) placeEditor.hidden = true;
  }
  if (state.mode === 'places') {
    const access = state.view.querySelector('[data-client-pane="tools"] > details.card');
    if (access) access.hidden = true;
    const browsers = el('browser-access');
    if (browsers) browsers.hidden = true;
    const places = state.view.querySelector('#saved-places');
    if (places) places.querySelector('h3').textContent = 'Household places';
  }
  el('location-list').hidden = true;
}

/** Returns a validated {lat, lon, accuracy}, throwing if the values are out of range. */
function point(lat, lon, accuracy) {
  const p = { lat: Number(lat), lon: Number(lon), accuracy: Number(accuracy) };
  if (
    !Number.isFinite(p.lat) ||
    !Number.isFinite(p.lon) ||
    !Number.isFinite(p.accuracy) ||
    Math.abs(p.lat) > 90 ||
    Math.abs(p.lon) > 180 ||
    p.accuracy < 0 ||
    p.accuracy > 100000
  ) {
    throw new Error('Invalid location.');
  }
  return p;
}

/**
 * Describes how current a location is. Parked phones report about every 15 minutes, so an unchanged
 * location reads "since 10:34" rather than stale. Same rules as the phone apps. alarming marks a
 * location that may be wrong.
 */
export function freshness(p, now = Date.now()) {
  const zone = p.data?.tz;
  const when = (ms) =>
    zoneTime(ms, zone, { withDate: new Date(ms).toDateString() !== new Date(now).toDateString() });
  if (now - p.captured_at <= 1200000) return { suffix: '', alarming: false };
  const heard = Math.max(p.captured_at, p.last_contact || 0);
  const battery = p.data?.battery_pct;
  if (
    Number.isFinite(battery) &&
    battery <= 10 &&
    p.data?.charging !== true &&
    now - heard > 1800000
  ) {
    return { suffix: ` · may be off (battery was ${battery}%)`, alarming: true };
  }
  if (!p.still_since) return { suffix: ' · stale', alarming: true };
  const contact =
    p.last_contact && p.last_contact > p.captured_at + 60000
      ? ` · heard from ${when(p.last_contact)}`
      : '';
  return { suffix: ` · here since ${when(p.still_since)}${contact}`, alarming: false };
}

/** Returns a non-interactive map thumbnail for a place, reused across refreshes. */
function savedPlaceThumbnail(place, lat, lon, radius) {
  const signature = [lat, lon, radius, state.activeMapConfig.provider].join(':');
  let preview = placeTileMaps.get(place.entity_id);
  if (preview && preview.signature !== signature) {
    preview.map?.remove();
    placeTileMaps.delete(place.entity_id);
    preview = null;
  }
  if (!preview) {
    const holder = node('div');
    holder.className = 'place-card-photo';
    holder.setAttribute('role', 'img');
    holder.setAttribute('aria-label', 'Read-only map preview for ' + String(place.data.name));
    holder.inert = true;
    preview = { holder, map: null, signature, loading: false };
    placeTileMaps.set(place.entity_id, preview);
  }
  const target = preview;
  if (!target.map && !target.loading) {
    target.loading = true;
    requestAnimationFrame(async () => {
      if (!target.holder.isConnected || placeTileMaps.get(place.entity_id) !== target) {
        target.loading = false;
        return;
      }
      const mini = createHouseholdMap(target.holder, state.activeMapConfig, () => {}, {
        readOnly: true,
      });
      target.map = mini;
      try {
        await mini.load();
        if (placeTileMaps.get(place.entity_id) !== target || !target.holder.isConnected) {
          mini.remove();
          return;
        }
        const label = node('span', String(place.data.name));
        mini.place([lat, lon], radius, label);
        const delta = Math.max((radius * 2.5) / 111320, 0.00065);
        const lonDelta = delta / Math.max(0.2, Math.cos((lat * Math.PI) / 180));
        mini.fitBounds(
          [
            [lat - delta, lon - lonDelta],
            [lat + delta, lon + lonDelta],
          ],
          { maxZoom: 17, padding: [8, 8] },
        );
      } catch (error) {
        target.holder.textContent = 'Map preview unavailable';
        mini.remove();
        target.map = null;
      } finally {
        target.loading = false;
      }
    });
  } else {
    requestAnimationFrame(() => {
      if (target.holder.isConnected) target.map?.resize();
    });
  }
  return target.holder;
}

/** Reloads the latest locations and places and redraws the map and lists. */
async function refresh() {
  if (!state.vault) return;
  const epoch = state.renderEpoch;
  await sync();
  if (epoch !== state.renderEpoch || !state.map) return;
  const r = await deviceApi('/api/view');
  if (epoch !== state.renderEpoch || !state.map) return;
  if (r.revision !== state.chain.revision) throw new Error('Membership changed during refresh.');
  const records = r.records;
  const directory = await state.api('/api/household/members');
  const tracked = new Set(directory.members.filter((m) => m.role !== 'admin').map((m) => m.id));
  // The server's username is current; a profile keeps the name from when its photo was set.
  const usernames = new Map(directory.members.map((m) => [m.id, m.username]));
  state.states = records.filter((p) => p.kind !== 'location' || tracked.has(p.entity_id));
  state.markers.forEach((marker) => state.map.removeLayer(marker));
  state.markers = [];
  el('location-list').replaceChildren();
  el('place-list').replaceChildren();
  const profiles = new Map(
    state.states
      .filter((p) => p.kind === 'profile' && p.operation === 'upsert')
      .map((p) => [p.entity_id, p.data]),
  );
  const places = state.states.filter((p) => p.kind === 'place' && p.operation === 'upsert');
  if (state.mode === 'places') {
    const ids = new Set(places.map((p) => p.entity_id));
    for (const [id, preview] of placeTileMaps) {
      if (!ids.has(id)) {
        preview.map?.remove();
        placeTileMaps.delete(id);
      }
    }
  }
  const savedPlace = (lat, lon, accuracy = 25) =>
    matchingPlace(
      { latitude: lat, longitude: lon, accuracy },
      places.map((p) => ({ id: p.entity_id, ...p.data })),
    )?.name;
  const personLocations = state.states
    .filter((p) => p.kind === 'location')
    .map((p) => {
      const f = point(p.data.lat, p.data.lon, p.data.accuracy);
      return { state: p, fix: f, place: savedPlace(f.lat, f.lon, f.accuracy) };
    });
  const fan = householdAvatarFan(
    personLocations.map((p) => ({
      id: p.state.entity_id,
      lat: p.fix.lat,
      lon: p.fix.lon,
      place: p.place,
    })),
  );
  const points = personLocations.map((person, index) =>
    showMember(
      person,
      fan[index],
      profiles.get(person.state.entity_id),
      usernames.get(person.state.entity_id),
    ),
  );
  for (const p of places) showPlace(p);
  if (state.mode === 'map' && points.length) {
    state.map.frameHousehold(points, !state.map._narahemFramed);
    state.map._narahemFramed = true;
  }
  await showMapStatus(points.length);
  window.dispatchEvent(new Event('narahem.locations'));
}

/** Adds a member's marker and list row. Returns their position for framing the map. */
function showMember(person, layout, profile, username) {
  const p = person.state;
  const f = person.fix;
  const name = String(username || profile?.name || `Member ${p.entity_id.slice(0, 8)}`);
  const fresh = freshness(p);
  const stale = fresh.alarming;
  const fallback = f.lat.toFixed(5) + ', ' + f.lon.toFixed(5);
  const address = person.place || fallback;
  const speed = Number(p.data.speed_mps);
  const moving = Number.isFinite(speed) && speed >= 1.5 && speed <= 70;
  const battery = Number(p.data.battery_pct);
  const details = [
    ...(moving ? [`Speed ${Math.round(speed * 2.23694)} mph`] : []),
    ...(p.data.battery_pct !== undefined &&
    Number.isFinite(battery) &&
    battery >= 0 &&
    battery <= 100
      ? [`Battery ${Math.round(battery)}%${p.data.charging ? ' (charging)' : ''}`]
      : []),
  ].join(' · ');
  const extra = details ? ' · ' + details : '';
  // A fix's time is when it was reported, not when they arrived, so no arrival time is shown.
  const reported = zoneTime(p.captured_at, p.data.tz);
  const popup = node('div');
  const heading = node('strong', name);
  const description = node(
    'p',
    moving ? `Traveling · last update ${reported}` : `At ${address} · last update ${reported}`,
  );
  const capturedAt = zoneTime(p.captured_at, p.data.tz, { withDate: true });
  const listingText = (where) =>
    `${name}: ${where}${extra}${fresh.suffix || ' · recent'} · ${capturedAt}`;
  const listing = node('p', listingText(address));
  const listingRow = node('div');
  popup.append(heading, description);
  if (moving) popup.append(node('p', `Current reported speed: ${Math.round(speed * 2.23694)} mph`));
  if (stale) {
    popup.append(
      node('p', fresh.suffix.includes('may be off') ? 'Phone may be off' : 'Location may be stale'),
    );
  }
  state.markers.push(
    state.map.location([f.lat, f.lon], memberIcon(name, profile, layout), popup, stale),
  );
  listingRow.className = 'member map-location-row';
  listingRow.append(listing);
  el('location-list').append(listingRow);
  if (!person.place && addressesEnabled() && !moving) {
    const expected = state.vault;
    const epochNow = state.renderEpoch;
    reverseAddress(f.lat, f.lon, f.accuracy)
      .then((found) => {
        if (found && state.vault === expected && state.renderEpoch === epochNow) {
          description.textContent = `At ${found} · last update ${reported}`;
          listing.textContent = listingText(found);
        }
      })
      .catch(() => {});
  }
  return [f.lat, f.lon];
}

/** Creates a member's map icon: photo or initial and name, offset when grouped. */
function memberIcon(name, profile, layout) {
  const icon = node('div');
  const nameLabel = node('span', name);
  icon.className = 'map-person';
  icon.dataset.memberName = name;
  icon.style.setProperty('--fan-x', layout.dx + 'px');
  icon.style.setProperty('--fan-y', layout.dy + 'px');
  if (layout.clusterSize > 1) icon.classList.add('map-person-grouped');
  if (
    profile?.photo &&
    /^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(profile.photo) &&
    profile.photo.length < 30000
  ) {
    const image = node('img');
    image.src = profile.photo;
    image.alt = '';
    icon.append(image);
  } else {
    const initial = node('span', name.slice(0, 1).toUpperCase());
    initial.className = 'map-person-avatar';
    icon.append(initial);
  }
  nameLabel.className = 'map-person-label';
  icon.append(nameLabel);
  return icon;
}

/** Adds a place's circle to the map and its card with Edit and Delete buttons. */
function showPlace(p) {
  const f = point(p.data.lat, p.data.lon, 0);
  const radius = Number(p.data.radius);
  if (!Number.isFinite(radius) || radius < 1 || radius > 10000) {
    throw new Error('Invalid encrypted place.');
  }
  const placePopup = node('div');
  const row = node('article');
  const header = node('div');
  const description = node('div');
  const actions = node('div');
  const editingActions = node('div');
  const edit = node('button', 'Edit boundary');
  const remove = node('button', 'Delete place');
  const overlaps = state.states.filter(
    (q) =>
      q.kind === 'place' &&
      q.operation === 'upsert' &&
      q.entity_id !== p.entity_id &&
      metersBetween(f.lat, f.lon, q.data.lat, q.data.lon) < radius + q.data.radius,
  );
  placePopup.append(node('strong', String(p.data.name)), node('p', `Boundary: ${radius} m`));
  state.markers.push(state.map.place([f.lat, f.lon], radius, placePopup));
  row.className = 'place-card';
  header.className = 'place-card-summary';
  if (state.mode === 'places') header.append(savedPlaceThumbnail(p, f.lat, f.lon, radius));
  description.className = 'place-card-details';
  description.append(
    node('strong', String(p.data.name)),
    node('span', `Boundary radius: ${radius} m`),
  );
  header.append(description);
  row.append(header);
  actions.className = 'place-card-actions';
  editingActions.className = 'place-card-edit-actions';
  edit.className = 'secondary';
  edit.onclick = () => editPlace(p);
  editingActions.append(edit);
  if (overlaps.length) {
    row.append(
      node(
        'small',
        'Overlaps ' + overlaps.map((q) => q.data.name).join(', ') + '. Edit or delete to resolve.',
      ),
    );
  }
  remove.className = 'danger';
  remove.onclick = run(async () => {
    if (!confirm('Delete ' + String(p.data.name) + ' for the household?')) return;
    await publish('place', p.entity_id, {}, 'delete');
    if (state.editingPlaceId === p.entity_id) resetPlaceEditor();
    await refresh();
    state.notice('Place deleted.');
  });
  editingActions.append(remove);
  actions.append(editingActions);
  row.append(actions);
  el('place-list').append(row);
}

/** Loads a place into the form for editing. */
function editPlace(p) {
  const currentRadius = Number(p.data.radius);
  state.editingPlaceId = p.entity_id;
  state.editingPlaceRecordId = p.id;
  for (const [id, value] of [
    ['place-name', p.data.name],
    ['place-lat', p.data.lat],
    ['place-lon', p.data.lon],
    ['place-radius', p.data.radius],
  ]) {
    el(id).value = value;
  }
  openPlaceEditor();
  el('place-editor-heading').textContent = 'Edit ' + String(p.data.name);
  el('place-save-button').textContent = 'Save changes';
  el('place-name').focus();
  el('place-address').value = '';
  el('place-address-status').textContent =
    'Editing ' +
    String(p.data.name) +
    '. The exact saved center is preserved until you search or click the map.';
  el('place-radius-slider').value = String(Math.min(2000, Math.max(1, currentRadius)));
  state.refreshPlacePreview().catch((error) => state.notice(error.message));
  el('place-form').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/** Updates the status line, noting places that still need to be shared to this browser. */
async function showMapStatus(locationCount) {
  const placeManifest = await deviceApi('/api/places/manifest');
  const missingPlaces = placeManifest.places.filter(
    (p) =>
      p.operation === 'upsert' &&
      !state.states.some((s) => s.kind === 'place' && s.id === p.record_id),
  ).length;
  if (state.mode === 'places') {
    el('places-status').textContent = missingPlaces
      ? `${missingPlaces} places need re-sharing from an approved device.`
      : state.states.some((s) => s.kind === 'place' && s.operation === 'upsert')
        ? ''
        : 'No saved places are available to this browser.';
  }
  el('map-status').textContent = missingPlaces
    ? `${missingPlaces} shared places waiting for synchronization from an existing approved client.`
    : locationCount
      ? `${locationCount} shared locations · refreshed ${new Date().toLocaleTimeString()}`
      : 'No shared locations available.';
}
