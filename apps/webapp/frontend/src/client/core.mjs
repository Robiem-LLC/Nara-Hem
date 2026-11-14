// Shared helpers: DOM shortcuts, the device API, sync, lock/stop, the roster and pairing.

import * as C from '../crypto.mjs';
import { placeTileMaps } from './map-screen.mjs';
import { state } from './state.mjs';

/** Find My Phone polling timers, cancelled by stop(). */
export const findTimers = new Set();

/**
 * localStorage key for the trip map background setting. Renamed when the option changed, so an old
 * "off" value doesn't hide the new backgrounds.
 */
export const TRIP_BACKGROUNDS_KEY = 'narahem.trip-map-backgrounds';

/** Returns the element with the given ID. */
export const el = (id) => document.getElementById(id);

/** Shows a one-time notice when Google static maps fail. */
export const warnGoogleStatic = () => {
  if (state.googleStaticWarned) return;
  state.googleStaticWarned = true;
  console.warn(
    'Google refused the trip map picture; using OpenStreetMap instead. Enable "Maps Static ' +
      'API" on this Google key (and allow it under API restrictions).',
  );
};

/** Creates an element with optional text. */
export const node = (tag, text) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = String(text);
  return n;
};

/** Copies a template from index.html into target (the main view by default). */
export function showTemplate(templateId, target = state.view) {
  target.replaceChildren(document.getElementById(templateId).content.cloneNode(true));
  return target;
}

/** Wraps an event handler: prevents the default action and shows any error as a notice. */
export function run(task) {
  return async (event) => {
    event?.preventDefault();
    try {
      state.notice('');
      await task(event);
    } catch (e) {
      state.notice(e.message);
    }
  };
}

/** Calls task with the form's values on submit. */
export function bind(id, task) {
  el(id).onsubmit = run((e) => task(Object.fromEntries(new FormData(e.target))));
}

/** Calls task when the button is clicked. */
export function button(id, task) {
  el(id).onclick = run(task);
}

/** Calls the API authenticated as this browser's device. */
export const deviceApi = (path, method = 'GET', body, headers = {}) =>
  state.api(path, method, body, { Authorization: `Bearer ${state.vault.credential}`, ...headers });

/** Encrypts and stores the vault in this browser. */
export async function save() {
  const expected = state.vault;
  const target = state.storeKey;
  const saved = {
    ...(await C.sealVault(state.vault, state.key, state.salt, state.context)),
    trusted: true,
  };
  if (state.vault === expected) localStorage.setItem(target, JSON.stringify(saved));
}

/** Cancels timers and removes maps and observers before the screen changes. */
export function stop() {
  state.tripScrollAbort?.abort();
  state.tripScrollAbort = null;
  for (const preview of placeTileMaps.values()) preview.map?.remove();
  placeTileMaps.clear();
  state.timelinePreviewObserver?.disconnect();
  state.timelinePreviewObserver = null;
  state.placePreviewClick?.();
  state.placePreviewClick = null;
  state.placePreviewCircle?.remove();
  state.placePreviewCircle = null;
  state.placePreviewMap?.remove();
  state.placePreviewMap = null;
  findTimers.forEach(clearTimeout);
  findTimers.clear();
  state.timelineMaps.forEach((m) => m.remove());
  state.timelineMaps = [];
  clearInterval(state.timer);
  if (state.map) {
    state.markers.forEach((marker) => state.map.removeLayer(marker));
    state.map.remove();
    state.map = null;
  }
  state.markers = [];
}

/** Clears the unlocked keys and shows the locked screen. */
export function lock() {
  state.renderEpoch++;
  stop();
  C.wipe(state.vault);
  state.vault = state.key = state.salt = state.chain = null;
  state.states = [];
  state.tripFocusAccount = '';
}

/** Fetches and verifies new signed roster revisions. */
export async function sync() {
  const expected = state.vault;
  let after = 0;
  const changes = [];
  let r;
  if (!expected) throw new Error('Browser session changed.');
  do {
    r = await deviceApi(`/api/roster?after=${after}`);
    if (state.vault !== expected) throw new Error('Browser session changed.');
    changes.push(...r.changes);
    after = changes.at(-1)?.body.revision || 0;
    if (!r.changes.length && after < r.revision) throw new Error('Incomplete membership chain.');
    if (changes.length > 10000) throw new Error('Membership exceeds browser limit.');
  } while (after < r.revision);
  if (!r.revision) return null;
  if (!state.vault.anchor) throw new Error('Verify the owner fingerprint first.');
  const result = C.verifyChain(changes, state.vault.household, state.vault.anchor);
  if (
    result.revision < state.vault.revision ||
    (result.revision === state.vault.revision && result.hash !== state.vault.chain_hash)
  ) {
    throw new Error('Membership rollback or fork rejected.');
  }
  if (!result.current.devices.some((d) => d.id === state.vault.id)) {
    throw new Error('This browser is no longer approved.');
  }
  state.vault.revision = result.revision;
  state.vault.chain_hash = result.hash;
  state.chain = result;
  await save();
  return result.current;
}

/** Returns this browser's device registration body. */
export const registration = () => ({
  domain: 'narahem.device.v1',
  household: state.vault.household,
  ...C.identity(state.vault),
  platform: 'web',
});

/**
 * Accepts the household root only after finding a signed roster revision that approves this exact
 * registration.
 */
export async function acceptSignedPairing(h) {
  if (!h.anchor) throw new Error('Household root is unavailable.');
  const expected = state.vault;
  const changes = [];
  let after = 0;
  let revision;
  do {
    const page = await deviceApi('/api/roster?after=' + after);
    if (state.vault !== expected) throw new Error('Browser session changed.');
    if (page.household !== state.vault.household || page.anchor !== h.anchor) {
      throw new Error('Household changed during pairing.');
    }
    if (!page.changes.length && after < page.revision) {
      throw new Error('Incomplete trusted roster.');
    }
    changes.push(...page.changes);
    after = changes.at(-1)?.body.revision || 0;
    revision = page.revision;
    if (changes.length > 10000) throw new Error('Membership history too long.');
  } while (after < revision);
  const result = C.verifyPairing(changes, state.vault.household, h.anchor, registration());
  if (result.revision !== h.revision) throw new Error('Membership changed; retry pairing.');
  state.vault.anchor = h.anchor;
  state.vault.revision = result.revision;
  state.vault.chain_hash = result.hash;
  state.chain = result;
  await save();
}

/**
 * Signs a roster revision removing devices the server reports as revoked. Only the admin's browser
 * can do this; the server can't sign for it.
 */
export async function reconcileRevokedMembership() {
  if (!state.vault || !state.chain || state.user?.role !== 'admin') return false;
  const directory = await state.api('/api/devices');
  const active = new Set(directory.devices.filter((d) => d.status !== 'revoked').map((d) => d.id));
  const removed = state.chain.current.devices.filter((d) => !active.has(d.id));
  if (!removed.length) return false;
  if (removed.some((d) => d.id === state.vault.id)) {
    throw new Error('This administrator browser was revoked.');
  }
  await roster(state.chain.current.devices.filter((d) => active.has(d.id)));
  return true;
}

/** Signs and uploads a new roster revision with the given devices. */
export async function roster(devices, pairing = null) {
  await sync();
  const body = {
    domain: 'narahem.roster.v1',
    household: state.vault.household,
    revision: state.chain.revision + 1,
    previous: state.chain.hash,
    signer: state.vault.id,
    devices: devices.sort((a, b) => a.id.localeCompare(b.id)),
    issued_at: Math.floor(Date.now() / 1000),
    ...(pairing || {}),
  };
  await deviceApi('/api/roster', 'POST', {
    body,
    signature: C.sign(body, state.vault.signing_secret),
  });
  await sync();
}
