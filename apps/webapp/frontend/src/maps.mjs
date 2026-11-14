import L from 'leaflet';
import { GOOGLE_DARK_STYLES, OSM_TILE_URL, OSM_TILE_ATTRIBUTION } from './mapstyle.mjs';
import { themeColor } from './theme.mjs';

/** The whole world in map coordinates (web maps stop at about 85° north and south). */
const WORLD = { north: 85, south: -85, west: -180, east: 180 };

/**
 * Google error messages meaning the key isn't allowed to use an API, as opposed to a temporary
 * failure.
 */
const GOOGLE_ACCESS_ERRORS = new RegExp(
  [
    'REQUEST_DENIED',
    'PERMISSION_DENIED',
    'ApiTargetBlocked',
    'not authorized',
    'not activated',
    'billing',
    'Geocoding API',
  ].join('|'),
  'i',
);

let googleLoad;
const authListeners = new Set();

/** Returns the smallest zoom at which one copy of the world fills a map this many pixels wide. */
export function worldMinZoom(width) {
  return width > 256 ? Math.ceil(Math.log2(width / 256)) : 0;
}

/** Loads the Google Maps script once and returns the google.maps namespace. */
function loadGoogle(apiKey) {
  if (googleLoad) return googleLoad;
  googleLoad = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    let timeout;
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      delete window.naraHemGoogleReady;
      if (error) {
        script.remove();
        googleLoad = null;
        reject(error);
      } else {
        resolve(window.google.maps);
      }
    };
    window.gm_authFailure = () => {
      const error = new Error(
        'Google Maps authorization failed. Check the API key, billing and website restrictions.',
      );
      finish(error);
      for (const listener of authListeners) listener(error);
    };
    window.naraHemGoogleReady = () => finish();
    script.onerror = () =>
      finish(new Error('Google Maps could not load. Check your connection or use OpenStreetMap.'));
    const url = new URL('https://maps.googleapis.com/maps/api/js');
    url.search = new URLSearchParams({
      key: apiKey,
      loading: 'async',
      callback: 'naraHemGoogleReady',
      v: 'quarterly',
    });
    script.src = url.href;
    script.async = true;
    script.nonce = document.querySelector('script[nonce]')?.nonce || '';
    script.referrerPolicy = 'origin';
    timeout = setTimeout(
      () => finish(new Error('Google Maps timed out. Try again or use OpenStreetMap.')),
      20000,
    );
    document.head.append(script);
  });
  return googleLoad;
}

/** Rejects with message if promise doesn't settle within the time limit. */
function withDeadline(promise, milliseconds, message) {
  let timeout;
  return Promise.race([
    Promise.resolve(promise),
    new Promise((_, reject) => {
      timeout = setTimeout(() => reject(new Error(message)), milliseconds);
    }),
  ]).finally(() => clearTimeout(timeout));
}

/** Converts a Google geocoding failure into a readable Error. */
function geocodingError(error) {
  const code = String(error?.code || error?.message || error || 'Unknown error');
  if (/ZERO_RESULTS|No matching/i.test(code)) {
    return new Error('No address found. Check the spelling or try a nearby landmark.');
  }
  if (/OVER_QUERY_LIMIT|RESOURCE_EXHAUSTED|quota/i.test(code)) {
    return new Error('Google geocoding quota was reached. Try later or search with OpenStreetMap.');
  }
  if (GOOGLE_ACCESS_ERRORS.test(code)) {
    return new Error(
      'Google denied address lookup. Enable Geocoding API and billing, and allow Geocoding ' +
        'API for this website-restricted browser key in Google Cloud.',
    );
  }
  if (/timed out/i.test(code)) {
    return new Error(
      'Google address search timed out. Check Geocoding API access or try OpenStreetMap.',
    );
  }
  return new Error(
    'Google address search failed: ' +
      code.slice(0, 180) +
      '. Check Geocoding API access or try OpenStreetMap.',
  );
}

/** Geocodes an address or location with Google. The key must allow the Geocoding API. */
async function googleGeocode(config, query) {
  try {
    return await withDeadline(
      (async () => {
        const maps = await loadGoogle(config.api_key);
        const { Geocoder } = await maps.importLibrary('geocoding');
        if (typeof Geocoder !== 'function') throw new Error('Geocoding API is unavailable');
        const result = await new Geocoder().geocode(
          typeof query === 'string' ? { address: query } : { location: query },
        );
        if (!result.results?.length) throw new Error('ZERO_RESULTS');
        return result.results;
      })(),
      12000,
      'Google geocoding timed out',
    );
  } catch (error) {
    throw geocodingError(error);
  }
}

/** Converts a Google geocoding result to {lat, lon, address}. */
function geocodeItem(item) {
  const loc = item?.geometry?.location;
  return {
    address: item?.formatted_address || '',
    lat: typeof loc?.lat === 'function' ? loc.lat() : NaN,
    lon: typeof loc?.lng === 'function' ? loc.lng() : NaN,
    types: item?.types || [],
  };
}

/** Returns Google's best match for an address. */
export async function googleAddress(config, query) {
  return geocodeItem((await googleGeocode(config, query))[0]);
}

/** Returns Google's addresses near a point. */
export async function googleReverseCandidates(config, location) {
  return (await googleGeocode(config, location)).map(geocodeItem);
}

/**
 * Returns screen offsets that spread out overlapping member avatars. Members with nearby fixes, or
 * in the same saved place within 100 m, form a group. Coordinates are never changed.
 */
export function householdAvatarFan(members) {
  const parent = members.map((_, i) => i);
  const root = (i) => {
    while (parent[i] !== i) {
      parent[i] = parent[parent[i]];
      i = parent[i];
    }
    return i;
  };
  const unite = (a, b) => {
    a = root(a);
    b = root(b);
    if (a !== b) parent[b] = a;
  };
  for (let i = 0; i < members.length; i++) {
    for (let j = i + 1; j < members.length; j++) {
      const a = members[i];
      const b = members[j];
      if (![a.lat, a.lon, b.lat, b.lon].every(Number.isFinite)) continue;
      const radians = (((a.lat + b.lat) / 2) * Math.PI) / 180;
      const north = (a.lat - b.lat) * 111320;
      const east = (a.lon - b.lon) * 111320 * Math.cos(radians);
      const distance = Math.hypot(north, east);
      if (distance <= 35 || (a.place && a.place === b.place && distance <= 100)) unite(i, j);
    }
  }
  const groups = new Map();
  for (let i = 0; i < members.length; i++) {
    const id = root(i);
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(i);
  }
  const positions = members.map(() => ({ dx: 0, dy: 0, clusterSize: 1 }));
  for (const indices of groups.values()) {
    if (indices.length < 2) continue;
    indices.sort((a, b) => String(members[a].id).localeCompare(String(members[b].id)));
    const cols = Math.min(4, indices.length);
    indices.forEach((index, slot) => {
      const row = Math.floor(slot / cols);
      const inRow = slot % cols;
      const count = Math.min(cols, indices.length - row * cols);
      positions[index] = {
        dx: Math.round((inRow - (count - 1) / 2) * 42),
        dy: row ? -(row * 36) : 0,
        clusterSize: indices.length,
      };
    });
  }
  return positions;
}

/**
 * Creates a map using Google or OpenStreetMap with the same interface for markers, places and
 * routes. readOnly maps have no controls and ignore gestures.
 */
export function createHouseholdMap(element, configuration, onError, { readOnly = false } = {}) {
  let current = null;
  let provider = configuration.provider === 'google' ? 'google' : 'openstreetmap';
  let active = true;
  let loaded = false;
  let info;
  let google;
  const authError = (error) => {
    if (active) onError(error);
  };
  authListeners.add(authError);
  const result = {
    _narahemFramed: false,
    async load() {
      if (!active || loaded) return;
      if (configuration.provider === 'google') {
        google = await loadGoogle(configuration.api_key);
        const library = await google.importLibrary('maps');
        if (!active) return;
        element.replaceChildren();
        current = new library.Map(element, {
          center: { lat: 0, lng: 0 },
          zoom: Math.max(2, worldMinZoom(element.clientWidth)),
          minZoom: worldMinZoom(element.clientWidth),
          maxZoom: 19,
          // One world: no repeated copies side by side, and no panning past the poles.
          restriction: { latLngBounds: WORLD, strictBounds: true },
          gestureHandling: readOnly ? 'none' : 'greedy',
          mapTypeControl: false,
          streetViewControl: false,
          styles: GOOGLE_DARK_STYLES,
          backgroundColor: '#1f2a36',
          ...(readOnly
            ? { disableDefaultUI: true, keyboardShortcuts: false, clickableIcons: false }
            : {}),
        });
        info = new google.InfoWindow();
        provider = 'google';
        result._narahemFramed = false;
      } else {
        current = L.map(
          element,
          readOnly
            ? {
                zoomControl: false,
                dragging: false,
                scrollWheelZoom: false,
                doubleClickZoom: false,
                boxZoom: false,
                keyboard: false,
                touchZoom: false,
              }
            : { scrollWheelZoom: true },
        );
        // One world: no repeated copies side by side, and no panning past the poles.
        current.setMinZoom(worldMinZoom(element.clientWidth));
        current.setMaxBounds([
          [WORLD.south, WORLD.west],
          [WORLD.north, WORLD.east],
        ]);
        current.options.maxBoundsViscosity = 1;
        current.setView([0, 0], Math.max(2, worldMinZoom(element.clientWidth)));
        // OpenStreetMap's tile policy requires a Referer; send only this server's origin.
        L.tileLayer(OSM_TILE_URL, {
          noWrap: true,
          maxZoom: 19,
          referrerPolicy: 'origin',
          attribution: OSM_TILE_ATTRIBUTION,
        }).addTo(current);
      }
      loaded = true;
    },
    dismissPopup() {
      if (!active || !loaded) return;
      if (provider === 'openstreetmap') current.closePopup();
      else info?.close();
    },
    location(point, icon, popup, stale) {
      if (!active || !loaded) return { remove() {} };
      const detach = attachMemberTooltip(icon, popup);
      const marker =
        provider === 'openstreetmap'
          ? leafletPerson(current, point, icon, stale)
          : googlePerson(google, current, point, icon, stale);
      return {
        remove: () => {
          detach();
          marker.remove();
        },
      };
    },
    // label is optional: without one, clicking the circle opens nothing.
    place(point, radius, label) {
      if (!active || !loaded) return { remove() {} };
      if (provider === 'openstreetmap') {
        const circle = L.circle(point, {
          radius,
          color: themeColor('place'),
          interactive: Boolean(label),
        }).addTo(current);
        if (label) circle.bindPopup(label);
        return { remove: () => circle.remove() };
      }
      const circle = new google.Circle({
        map: current,
        center: { lat: point[0], lng: point[1] },
        radius,
        strokeColor: themeColor('place'),
        fillColor: themeColor('place'),
        fillOpacity: 0.2,
        clickable: Boolean(label),
      });
      const listener =
        label &&
        circle.addListener('click', () => {
          info.setContent(label);
          info.setPosition(circle.getCenter());
          info.open({ map: current });
        });
      return {
        remove: () => {
          listener?.remove();
          circle.setMap(null);
        },
      };
    },
    route(segments) {
      const layers = [];
      if (!active || !loaded) return { remove() {} };
      for (const segment of segments) {
        const points = segment.map((p) => [p.latitude, p.longitude]);
        if (points.length < 2) continue;
        if (provider === 'openstreetmap') {
          layers.push(L.polyline(points, { color: themeColor('route'), weight: 4 }).addTo(current));
        } else {
          layers.push(
            new google.Polyline({
              map: current,
              path: points.map((p) => ({ lat: p[0], lng: p[1] })),
              strokeColor: themeColor('route'),
              strokeWeight: 4,
            }),
          );
        }
      }
      const all = segments.flat();
      for (const [p, label] of [
        [all[0], 'Start'],
        [all.at(-1), 'Finish'],
      ]) {
        if (p) {
          if (provider === 'openstreetmap') {
            layers.push(
              L.circleMarker([p.latitude, p.longitude], {
                radius: 6,
                color: themeColor(label === 'Start' ? 'trip-start' : 'trip-end'),
                fillOpacity: 1,
              })
                .addTo(current)
                .bindTooltip(label),
            );
          } else {
            layers.push(
              new google.Marker({
                map: current,
                position: { lat: p.latitude, lng: p.longitude },
                title: label,
              }),
            );
          }
        }
      }
      return {
        remove: () =>
          layers.forEach((layer) =>
            provider === 'openstreetmap' ? layer.remove() : layer.setMap(null),
          ),
      };
    },
    onMapClick(callback) {
      if (!active || !loaded) return () => {};
      if (provider === 'openstreetmap') {
        const handler = (e) => callback(e.latlng.lat, e.latlng.lng);
        current.on('click', handler);
        return () => current.off('click', handler);
      }
      const handler = current.addListener('click', (e) => callback(e.latLng.lat(), e.latLng.lng()));
      return () => handler.remove();
    },
    resize() {
      if (!active || !loaded) return;
      if (provider === 'openstreetmap') current.invalidateSize({ animate: false, pan: false });
      else google.event.trigger(current, 'resize');
    },
    removeLayer(marker) {
      marker.remove();
    },
    frameHousehold(points, force = false) {
      if (!active || !loaded) return;
      const width = element.clientWidth;
      const height = element.clientHeight;
      if (!points.length || width <= 60 || height <= 60) return;
      const bounds = L.latLngBounds(points);
      const fitZoom = zoomToFit(points, width, height);
      // The minimum zoom comes from member locations only, never places or trips, and never
      // so far out that the world repeats.
      const minZoom = Math.max(fitZoom, worldMinZoom(width));
      if (provider === 'openstreetmap') {
        current.setMinZoom(minZoom);
        if (force || !current.getBounds().contains(bounds)) {
          current.fitBounds(bounds, { maxZoom: 15, padding: [30, 30], animate: false });
        }
      } else {
        current.setOptions({ minZoom });
        if (force) result.fitBounds(points, { maxZoom: 15, padding: [30, 30] });
      }
    },
    fitBounds(points, options) {
      if (!active || !loaded || !points.length) return;
      // No animation: a delayed Leaflet zoom would fail if the map was removed meanwhile.
      if (provider === 'openstreetmap') {
        return current.fitBounds(points, { ...options, animate: false });
      }
      const bounds = new google.LatLngBounds();
      points.forEach((p) => bounds.extend({ lat: p[0], lng: p[1] }));
      const target = current;
      google.event.addListenerOnce(target, 'idle', () => {
        if (active && target.getZoom() > options.maxZoom) target.setZoom(options.maxZoom);
      });
      target.fitBounds(bounds, options.padding[0]);
    },
    remove() {
      if (!active) return;
      active = false;
      authListeners.delete(authError);
      if (provider === 'openstreetmap') {
        if (current) {
          current.stop();
          current.remove();
        }
      } else if (info) {
        info.close();
        google.event.clearInstanceListeners(current);
        element.replaceChildren();
      }
    },
  };
  return result;
}

/**
 * Attaches a tooltip to a member avatar, shown on hover, focus or tap. Returns a function that
 * removes it.
 */
function attachMemberTooltip(icon, popup) {
  const tooltipId = 'narahem-map-tip-' + Math.random().toString(36).slice(2);
  const toggle = (event) => {
    event.stopPropagation();
    icon.classList.toggle('is-open');
  };
  const onOutside = (event) => {
    if (!icon.contains(event.target)) icon.classList.remove('is-open');
  };
  popup.classList.add('member-map-popup');
  popup.setAttribute('role', 'tooltip');
  popup.id = tooltipId;
  icon.append(popup);
  icon.setAttribute('role', 'button');
  icon.setAttribute('tabindex', '0');
  icon.setAttribute('aria-label', icon.dataset.memberName || 'Member location');
  icon.setAttribute('aria-describedby', tooltipId);
  icon.addEventListener('click', toggle);
  icon.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggle(event);
    } else if (event.key === 'Escape') {
      icon.classList.remove('is-open');
      event.stopPropagation();
    }
  });
  document.addEventListener('pointerdown', onOutside);
  return () => {
    document.removeEventListener('pointerdown', onOutside);
    icon.removeEventListener('click', toggle);
  };
}

/** Adds a member avatar marker to a Leaflet map. */
function leafletPerson(map, point, icon, stale) {
  const marker = L.marker(point, {
    icon: L.divIcon({
      html: icon,
      className: stale ? 'person-marker stale' : 'person-marker',
      iconSize: [96, 70],
      iconAnchor: [48, 52],
    }),
  }).addTo(map);
  const leaf = marker.getElement();
  if (leaf) {
    leaf.setAttribute('aria-label', icon.dataset.memberName || 'Member location');
    leaf.setAttribute('title', '');
  }
  return { remove: () => marker.remove() };
}

/**
 * Adds a member avatar to a Google map as a custom overlay, since the classic API has no HTML
 * markers.
 */
function googlePerson(google, map, point, icon, stale) {
  const position = new google.LatLng(point[0], point[1]);
  const wrapper = document.createElement('div');
  wrapper.className = stale ? 'person-marker stale' : 'person-marker';
  wrapper.style.cssText =
    'position:absolute;z-index:10;background:transparent;border:0;padding:0;' +
    'width:96px;transform:translate(-50%,-100%)';
  wrapper.append(icon);
  /** Overlay that positions the avatar element at its coordinates. */
  class Person extends google.OverlayView {
    onAdd() {
      this.getPanes().overlayMouseTarget.append(wrapper);
      google.OverlayView.preventMapHitsAndGesturesFrom(wrapper);
    }

    draw() {
      const pixel = this.getProjection().fromLatLngToDivPixel(position);
      if (pixel) {
        wrapper.style.left = `${pixel.x}px`;
        wrapper.style.top = `${pixel.y}px`;
      }
    }

    onRemove() {
      wrapper.remove();
    }
  }
  const marker = new Person();
  marker.setMap(map);
  return { remove: () => marker.setMap(null) };
}

/** Returns the highest zoom, up to 15, at which every point fits in a width by height box. */
function zoomToFit(points, width, height) {
  const projected = points.map((p) => L.CRS.EPSG3857.latLngToPoint(L.latLng(p), 0));
  const spanX = Math.max(...projected.map((p) => p.x)) - Math.min(...projected.map((p) => p.x));
  const spanY = Math.max(...projected.map((p) => p.y)) - Math.min(...projected.map((p) => p.y));
  const scale = Math.min(
    (width - 60) / Math.max(spanX, 0.000001),
    (height - 60) / Math.max(spanY, 0.000001),
  );
  return Math.max(0, Math.min(15, Math.floor(Math.log2(scale))));
}
