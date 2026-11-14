// Street addresses: the local cache, consent, and OpenStreetMap or Google lookups.

import { clearSavedBasemaps } from '../thumbnails.mjs';
import { googleAddress, googleReverseCandidates } from '../maps.mjs';
import { formatAddress, selectGoogleReverseAddress } from '../locations.mjs';
import { state } from './state.mjs';

const addressCache = new Map();

/**
 * localStorage key prefix for cached trip addresses. Entries last 30 days and are cleared at
 * sign-out because they are stored unencrypted.
 */
const ADDRESS_PREFIX = 'narahem.address.';

/** Returns the great-circle distance between two points in metres. */
export function metersBetween(aLat, aLon, bLat, bLon) {
  const rad = Math.PI / 180;
  const dLat = (bLat - aLat) * rad;
  const dLon = (bLon - aLon) * rad;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(aLat * rad) * Math.cos(bLat * rad) * Math.sin(dLon / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(Math.max(0, Math.min(1, h))));
}

/** Returns a cached address less than 30 days old, or null. */
function savedAddress(key) {
  try {
    const v = JSON.parse(localStorage.getItem(ADDRESS_PREFIX + key) || 'null');
    return v && v.expires > Date.now() && typeof v.text === 'string' ? v.text : null;
  } catch (_) {
    return null;
  }
}

/** Caches an address in localStorage, ignoring storage errors. */
function keepAddress(key, text) {
  try {
    localStorage.setItem(
      ADDRESS_PREFIX + key,
      JSON.stringify({ text, expires: Date.now() + 30 * 86400000 }),
    );
  } catch (_) {
    // Storage may be full or disabled (private browsing); the address cache is optional.
  }
}

/** Deletes every cached address. */
export function forgetSavedLocations() {
  try {
    for (const k of Object.keys(localStorage)) {
      if (k.startsWith(ADDRESS_PREFIX)) localStorage.removeItem(k);
    }
  } catch (_) {
    // Storage may be disabled (private browsing); there is nothing to forget then.
  }
  clearSavedBasemaps();
}

/** Returns true if street address lookups are enabled in this browser. */
export function addressesEnabled() {
  return localStorage.getItem('narahem.address-lookup') === 'on';
}

/** Asks once whether to enable address lookups and stores the answer. */
export function requestAddressConsent() {
  if (localStorage.getItem('narahem.address-lookup') !== null) return addressesEnabled();
  const accepted = confirm(
    'Show street addresses automatically on household maps and trips? This sends precise ' +
      'locations of the points you view directly to the selected map provider (Google or ' +
      'OpenStreetMap), not to your Nära Hem server. You can change this in Maps privacy ' +
      'settings.',
  );
  localStorage.setItem('narahem.address-lookup', accepted ? 'on' : 'off');
  return accepted;
}

/** Returns "Google" or "OpenStreetMap". */
export function providerName(provider = state.activeMapConfig.provider) {
  return provider === 'google' ? 'Google' : 'OpenStreetMap';
}

/** Geocodes an address with OpenStreetMap Nominatim. */
async function osmLookup(query) {
  const url = new URL('https://nominatim.openstreetmap.org/search');
  url.search = new URLSearchParams({ format: 'jsonv2', q: query, limit: '1' });
  const result = await fetch(url, { referrerPolicy: 'origin' });
  if (!result.ok) throw new Error('OpenStreetMap address search unavailable');
  const matches = await result.json();
  if (!matches.length) {
    throw new Error('Address not found. Try a fuller address or choose a point on the map.');
  }
  return {
    address: matches[0].display_name,
    lat: Number(matches[0].lat),
    lon: Number(matches[0].lon),
  };
}

/** Geocodes an address with the given provider. */
export async function forwardAddress(query, provider = state.activeMapConfig.provider) {
  if (provider === 'google') return googleAddress(state.activeMapConfig, query);
  // Public Nominatim is not an autocomplete service; search only on user action.
  const task = state.addressQueue.then(() => osmLookup(query));
  state.addressQueue = task
    .catch(() => null)
    .then(() => new Promise((resolve) => setTimeout(resolve, 1100)));
  return task;
}

/**
 * Returns a cached or looked-up street address for the point, or null if lookups are disabled or
 * fail.
 */
export function reverseAddress(lat, lon, accuracy = 25) {
  if (!addressesEnabled()) return Promise.resolve(null);
  const provider = state.activeMapConfig.provider === 'google' ? 'google' : 'openstreetmap';
  const cacheKey =
    provider + ':' + lat.toFixed(4) + ',' + lon.toFixed(4) + ':' + Math.round(accuracy / 25);
  if (addressCache.has(cacheKey) && addressCache.get(cacheKey).expires < Date.now()) {
    addressCache.delete(cacheKey);
  }
  const remembered = savedAddress(cacheKey);
  if (remembered) return Promise.resolve(remembered);
  if (!addressCache.has(cacheKey)) {
    const task =
      provider === 'google'
        ? googleReverseCandidates(state.activeMapConfig, { lat, lng: lon }).then((results) =>
            selectGoogleReverseAddress(results, { latitude: lat, longitude: lon, accuracy }),
          )
        : state.addressQueue.then(async () => {
            const url = new URL('https://nominatim.openstreetmap.org/reverse');
            url.search = new URLSearchParams({
              format: 'jsonv2',
              addressdetails: '1',
              zoom: '18',
              lat: String(lat),
              lon: String(lon),
            });
            const response = await fetch(url, { referrerPolicy: 'origin' });
            if (!response.ok) throw new Error('Address service unavailable');
            return formatAddress(await response.json(), {
              latitude: lat,
              longitude: lon,
              accuracy,
            });
          });
    if (provider === 'openstreetmap') {
      state.addressQueue = task
        .catch(() => null)
        .then(() => new Promise((resolve) => setTimeout(resolve, 1100)));
    }
    const entry = {
      expires: Date.now() + 30000,
      promise: task
        .catch(() => null)
        .then((value) => {
          entry.expires = Date.now() + (value ? 86400000 : 30000);
          if (value) keepAddress(cacheKey, value);
          return value;
        }),
    };
    addressCache.set(cacheKey, entry);
  }
  return addressCache.get(cacheKey).promise;
}
