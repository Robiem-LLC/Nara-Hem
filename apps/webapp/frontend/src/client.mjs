// The encrypted household client, bundled as client.js. app.js uses it through window.FamilyClient;
// the screens live in ./client/.

import { matchingPlace } from './locations.mjs';
import * as C from './crypto.mjs';
import * as T from './trusted-vault.mjs';
import { endpointLabel } from './trips.mjs';
import { addressesEnabled, forgetSavedLocations, reverseAddress } from './client/addresses.mjs';
import { locked } from './client/browser-access.mjs';
import { deviceApi, lock, save, showTemplate, stop, sync } from './client/core.mjs';
import { refreshHouseholdMemberPhones } from './client/devices-screen.mjs';
import { freshness, screen } from './client/map-screen.mjs';
import { initials } from './client/initials.mjs';
import { zoneTime } from './client/zones.mjs';
import { state } from './client/state.mjs';
import * as mailPresets from './mail-presets.mjs';

/**
 * Registers this browser as one of the administrator's devices. The vault is only shared once
 * the server has stored it, so no request goes out with a device the server doesn't know yet.
 */
async function registerAdminBrowser() {
  const h = await state.api('/api/household');
  const key = await T.createKey();
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const vault = C.keys(state.user.id, h.id, 'Admin');
  const registration = {
    domain: 'narahem.device.v1',
    household: h.id,
    ...C.identity(vault),
    platform: 'web',
  };
  const result = await state.api('/api/devices/register', 'POST', {
    id: vault.id,
    name: 'Admin',
    signing_key: vault.signing_key,
    box_key: vault.box_key,
    platform: 'web',
    signature: C.sign(registration, vault.signing_secret),
  });

  vault.credential = result.credential;
  state.key = key;
  state.salt = salt;
  state.vault = vault;
  await T.putKey(state.context, key);
  await save();
}

window.FamilyClient = {
  /** Email provider presets for the admin email form in app.js. */
  mailPresets,
  async mount(options) {
    const requested = ++state.renderEpoch;
    if (sessionStorage.getItem('narahem.signed-out')) return;
    await C.ready;
    if (requested !== state.renderEpoch) return;
    stop();
    if (state.vault && state.vault.account_id !== options.user.id) lock();
    const epoch = state.renderEpoch;
    ({ api: state.api, user: state.user, notice: state.notice, view: state.view } = options);
    state.mode = options.mode || 'map';
    state.context = `${location.origin}/${state.user.id}`;
    state.storeKey = `narahem.vault.${state.user.id}`;
    let expected = epoch;
    try {
      if (!state.vault && crypto.subtle) {
        const saved = localStorage.getItem(state.storeKey);
        if (saved) {
          const remembered = await T.getKey(state.context);
          if (epoch !== state.renderEpoch) return;
          if (remembered) {
            const opened = await T.open(JSON.parse(saved), remembered, state.context);
            if (epoch !== state.renderEpoch) return;
            state.vault = opened;
            state.key = remembered;
            state.salt = C.unb64(JSON.parse(saved).salt);
          }
        }
      }
      if (
        !state.vault &&
        state.user.role === 'admin' &&
        crypto.subtle &&
        !localStorage.getItem(state.storeKey)
      ) {
        // Two screens can open at once (sign-in shows the map while Manage household opens):
        // both wait for one registration instead of registering twice.
        state.registering ??= registerAdminBrowser().finally(() => {
          state.registering = null;
        });
        await state.registering;
      }
      if (state.vault) {
        const loading = screen();
        expected = state.renderEpoch;
        await loading;
      } else {
        await locked();
      }
    } catch (error) {
      if (expected !== state.renderEpoch) return;
      lock();
      if (state.mode === 'tools') await locked();
      else showTemplate('screen-location-unavailable', options.view);
      window.dispatchEvent(new Event('narahem.locations'));
      throw error;
    }
  },
  async refreshHouseholdMemberPhones(root) {
    await refreshHouseholdMemberPhones(root);
  },
  async renderMemberPhones(accountId, host) {
    if (host?.closest('.member-card')) {
      await refreshHouseholdMemberPhones(host.closest('#members') || host.parentElement);
    }
  },
  async inspectRecord(recordId) {
    if (!state.vault?.anchor) {
      throw new Error('Open Household map first to restore or approve this browser.');
    }
    const expected = state.vault;
    await sync();
    if (state.vault !== expected || sessionStorage.getItem('narahem.signed-out')) {
      throw new Error('Browser session changed.');
    }
    const record = await deviceApi('/api/records/' + encodeURIComponent(recordId));
    if (state.vault !== expected || sessionStorage.getItem('narahem.signed-out')) {
      throw new Error('Browser session changed.');
    }
    return C.decryptRecord(record.envelope, expected, state.chain.rosters);
  },

  async locationLabel(accountId) {
    const expected = state.vault;
    const p = state.states.find((p) => p.kind === 'location' && p.entity_id === accountId);
    if (!p) return 'Location unavailable';
    const point = { latitude: p.data.lat, longitude: p.data.lon, accuracy: p.data.accuracy };
    const places = state.states
      .filter((p) => p.kind === 'place' && p.operation === 'upsert')
      .map((p) => ({ id: p.entity_id, ...p.data }));
    const place = matchingPlace(point, places);
    if (place) return place.name;
    const address = addressesEnabled()
      ? await reverseAddress(point.latitude, point.longitude, point.accuracy)
      : null;
    if (state.vault !== expected) throw new Error('Browser session changed.');
    return address || endpointLabel(point, []);
  },
  openTripsFor(accountId) {
    state.tripFocusAccount = accountId;
    document.getElementById('open-trips').click();
  },
  canApprove() {
    return Boolean(
      state.vault?.anchor && state.chain?.current?.devices.some((d) => d.id === state.vault.id),
    );
  },
  freshness: (p) => freshness(p),
  /** A time, with the member's own time beside it when their zone differs (zones.mjs). */
  zoneTime: (ms, zone, options) => zoneTime(ms, zone, options),
  initials: (name) => initials(name),
  summaries() {
    if (!state.vault || !state.chain) return [];
    const profiles = new Map(
      state.states
        .filter((p) => p.kind === 'profile' && p.operation === 'upsert')
        .map((p) => [p.entity_id, p.data]),
    );
    return state.states
      .filter((p) => p.kind === 'location')
      .map((p) => ({
        id: p.entity_id,
        ...profiles.get(p.entity_id),
        location: p.data,
        captured_at: p.captured_at,
        still_since: p.still_since,
        last_contact: p.last_contact,
      }));
  },
  suspend() {
    state.renderEpoch++;
    stop();
  },
  lock() {
    lock();
    forgetSavedLocations();
    state.view = state.user = null;
  },
};
