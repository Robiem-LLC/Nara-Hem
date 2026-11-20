// Trips and stops for a household member.

import { createHouseholdMap } from '../maps.mjs';
import * as C from '../crypto.mjs';
import { themeColor } from '../theme.mjs';
import { frame, project, drawBasemap, drawGoogleBasemap, OSM_ATTRIBUTION } from '../thumbnails.mjs';
import {
  gpsFromRecord,
  durationText,
  routeSegments,
  stopsFromSamples,
  markCurrentStays,
  combineNearbyPlaceStops,
  tripPointsFor,
  tripBoundaryPlace,
  endpointLabel,
  isStationaryTrip,
  isInconsequentialTrip,
} from '../trips.mjs';
import { addressesEnabled, requestAddressConsent, reverseAddress } from './addresses.mjs';
import {
  TRIP_BACKGROUNDS_KEY,
  deviceApi,
  el,
  node,
  run,
  showTemplate,
  sync,
  warnGoogleStatic,
} from './core.mjs';
import { publish } from './records.mjs';
import { state } from './state.mjs';
import { zoneTime } from './zones.mjs';

/**
 * Shows the trips screen for a member: range picker, trip and stop cards, and more history on
 * scroll.
 */
export async function tripScreen(epoch) {
  const expected = state.vault;
  const directory = await state.api('/api/household/members');
  const config = await state.api('/api/maps');
  state.activeMapConfig = config;
  requestAddressConsent();
  if (epoch !== state.renderEpoch || state.vault !== expected) return;
  const members = directory.members.filter((m) => m.role !== 'admin');
  const names = new Map(members.map((m) => [m.id, m.username || 'Member']));
  showTemplate('screen-trips');
  const form = el('trip-filters');
  const list = el('trip-list');
  const status = el('trip-status');
  const historyStatus = el('trip-history-status');
  const moreStatus = el('trip-more-status');
  for (const member of members) {
    const option = node('option', member.username || 'Member');
    option.value = member.id;
    form.elements.member.append(option);
  }
  if (names.has(state.tripFocusAccount)) form.elements.member.value = state.tripFocusAccount;
  state.tripFocusAccount = '';
  // OpenStreetMap only receives the map area, never the route.
  form.elements.previews.checked = localStorage.getItem(TRIP_BACKGROUNDS_KEY) !== 'off';
  form.elements.previews.onchange = () => {
    localStorage.setItem(TRIP_BACKGROUNDS_KEY, form.elements.previews.checked ? 'on' : 'off');
    load();
  };
  /* Address lookup preference is shared with Household Map. */
  let requestNumber = 0;
  let gpsCursor = null;
  let trips = new Map();
  let samples = new Map();
  let places = [];
  let windowStart = 0;
  let windowEnd = 0;
  let scrollBusy = false;
  const current = (request) =>
    epoch === state.renderEpoch && state.vault === expected && request === requestNumber;
  // The member's time zone from their latest location; a trip's own zone wins when it has one.
  let memberZone = null;
  const zoneOf = (entry) => entry?.tz || memberZone;
  const time = (value, entry) => zoneTime(value, zoneOf(entry));
  const dated = (value, entry) => zoneTime(value, zoneOf(entry), { withDate: true });
  /** Sets the name of a trip end: the server's label, a saved place or a street address. */
  async function label(target, point, request, preferredPlace = null, known = null) {
    if (known) {
      target.textContent = known;
      return;
    }
    const fallback = preferredPlace?.name || endpointLabel(point, places);
    target.textContent = fallback;
    if (point && !preferredPlace && addressesEnabled() && fallback === endpointLabel(point, [])) {
      const found = await reverseAddress(point.latitude, point.longitude, point.accuracy || 25);
      if (found && current(request) && target.isConnected && addressesEnabled()) {
        target.textContent = found;
      }
    }
  }
  const thumbnails = new Map();
  const outlineRequests = new Set();
  const previewsOn = () => localStorage.getItem(TRIP_BACKGROUNDS_KEY) !== 'off';
  state.timelinePreviewObserver?.disconnect();
  state.timelinePreviewObserver = new IntersectionObserver(
    (items) => {
      for (const item of items) {
        if (item.isIntersecting) {
          state.timelinePreviewObserver.unobserve(item.target);
          item.target.onVisible?.();
        }
      }
    },
    { rootMargin: '300px' },
  );
  /** Returns the route outline for a trip card. */
  function tripOutline(entry) {
    if (entry.preview?.length >= 2) return entry.preview;
    return routeSegments(tripPointsFor(entry, [...samples.values()]))
      .flat()
      .map((p) => [p.latitude, p.longitude]);
  }
  /** Creates a trip card's static route image, rendered when it scrolls into view. */
  function tripThumbnail(entry, request, account) {
    const outline = tripOutline(entry);
    const signature = outline.length + ':' + outline[0] + ':' + outline.at(-1);
    const kept = thumbnails.get(entry.id);
    if (kept && kept.signature === signature) return kept.element;
    const target = node('div');
    target.className = 'trip-map trip-route-thumbnail';
    target.setAttribute('role', 'img');
    target.setAttribute('aria-label', 'Trip route preview. Open trip for the interactive map.');
    thumbnails.set(entry.id, { signature, element: target });
    if (outline.length < 2) {
      target.append(node('span', 'Route preview loading…'));
      target.onVisible = () => {
        if (outlineRequests.has(entry.id)) return;
        outlineRequests.add(entry.id);
        fetchTripRoute(entry, request, account)
          .then(() => {
            if (!current(request)) return;
            if (tripOutline(entry).length < 2) {
              target.replaceChildren(node('span', 'No route recorded for this trip'));
              return;
            }
            render(request);
          })
          .catch(() => {
            if (target.isConnected) {
              target.replaceChildren(node('span', 'Route preview unavailable'));
            }
          });
      };
      state.timelinePreviewObserver.observe(target);
      return target;
    }
    const google =
      previewsOn() &&
      state.activeMapConfig.provider === 'google' &&
      Boolean(state.activeMapConfig.api_key);
    const cardWidth = Math.max(240, Math.round((list.clientWidth || 600) - 2));
    const width = google ? Math.min(640, cardWidth) : cardWidth;
    const height = Math.round((150 * width) / cardWidth);
    const view = frame(outline, width, height, Math.max(10, Math.round((18 * width) / cardWidth)));
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('aria-hidden', 'true');
    const points = project(outline, view)
      .map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1))
      .join(' ');
    const casing = document.createElementNS(ns, 'path');
    const line = document.createElementNS(ns, 'polyline');
    casing.setAttribute('d', 'M' + points.replaceAll(' ', ' L'));
    line.setAttribute('points', points);
    for (const [shape, stroke, widthPx] of [
      [casing, themeColor('route-casing'), 7],
      [line, themeColor('route'), 4],
    ]) {
      shape.setAttribute('fill', 'none');
      shape.setAttribute('stroke', stroke);
      shape.setAttribute('stroke-width', String(widthPx));
      shape.setAttribute('stroke-linecap', 'round');
      shape.setAttribute('stroke-linejoin', 'round');
      svg.append(shape);
    }
    const ends = project([outline[0], outline.at(-1)], view);
    for (const [p, color] of [
      [ends[0], themeColor('trip-start')],
      [ends[1], themeColor('trip-end')],
    ]) {
      const dot = document.createElementNS(ns, 'circle');
      dot.setAttribute('cx', p[0].toFixed(1));
      dot.setAttribute('cy', p[1].toFixed(1));
      dot.setAttribute('r', '6');
      dot.setAttribute('fill', color);
      dot.setAttribute('stroke', themeColor('route-casing'));
      dot.setAttribute('stroke-width', '2');
      svg.append(dot);
    }
    target.append(svg);
    if (previewsOn()) {
      const visible = () => current(request) && target.isConnected;
      const osm = (error) => {
        if (error) warnGoogleStatic();
        return drawBasemap(target, view, visible);
      };
      target.onVisible = () =>
        (google
          ? drawGoogleBasemap(target, view, state.activeMapConfig.api_key, visible).catch(osm)
          : osm()
        )
          .then((result) => {
            // OpenStreetMap requires visible attribution; Google adds its own.
            if (result === 'skipped' || result === 'google' || !target.isConnected) return;
            const credit = node('span', OSM_ATTRIBUTION);
            credit.className = 'trip-tiles-attribution';
            target.append(credit);
          })
          .catch(() => {});
      state.timelinePreviewObserver.observe(target);
    }
    return target;
  }
  /** Draws an interactive map of the route. */
  async function draw(target, segments, request) {
    if (!segments.flat().length) {
      target.textContent = 'Route unavailable';
      return;
    }
    const m = createHouseholdMap(target, config, () => {
      target.setAttribute('aria-label', 'Route map could not load');
    });
    state.timelineMaps.push(m);
    target.tripMap = m;
    try {
      await m.load();
      if (!current(request) || !target.isConnected) {
        m.remove();
        return;
      }
      m.resize();
      m.route(segments);
      m.fitBounds(
        segments.flat().map((p) => [p.latitude, p.longitude]),
        { maxZoom: 16, padding: [24, 24] },
      );
    } catch (_) {
      m.remove();
      if (target.isConnected) {
        target.replaceChildren(node('p', 'Map unavailable. Trip details remain available.'));
      }
    }
  }
  /** Rebuilds the trip and stop cards. */
  function render(request) {
    const account = form.elements.member.value;
    memberZone =
      state.states?.find((p) => p.kind === 'location' && p.entity_id === account)?.data?.tz || null;
    const { values, entries } = timelineEntries(trips, samples, places);
    let day = '';
    list.replaceChildren();
    for (const entry of entries) {
      const date = new Date(entry.startedAt).toLocaleDateString(undefined, {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
      if (day !== date) {
        list.append(node('h3', date));
        day = date;
      }
      list.append(
        entry.kind === 'stop' ? stopCard(entry, request) : tripCard(entry, request, account),
      );
    }
    const count = `${values.length} completed ${values.length === 1 ? 'trip' : 'trips'}`;
    status.textContent = values.length
      ? `${count} · Open a trip for its full route.`
      : 'No completed trips available in this range.';
  }
  /**
   * Creates a stop card with its place, times and a Save Place button when it isn't a saved place.
   */
  function stopCard(entry, request) {
    const card = node('article');
    const title = node('h3');
    const where = node('span');
    const sameDay =
      new Date(entry.startedAt).toLocaleDateString() ===
      new Date(entry.endedAt).toLocaleDateString();
    const when = (value) => (sameDay ? time(value, entry) : dated(value, entry));
    const duration = durationText(entry.endedAt - entry.startedAt);
    card.className = 'trip-row timeline-card';
    const at = node('span', 'At ');
    title.append(at, where);
    // "Near 568 Myrtle Ave" reads better without "At" in front.
    const tidy = () => (at.hidden = /^Near\s/i.test(where.textContent));
    label(where, entry, request).then(tidy, tidy);
    tidy();
    if (entry.current) {
      // Still there: "At Home since 2:10 PM", with the date if it began on an earlier day.
      const today = new Date(entry.startedAt).toDateString() === new Date().toDateString();
      const since = today ? time(entry.startedAt, entry) : dated(entry.startedAt, entry);
      title.append(node('span', ` since ${since}`));
      card.append(title);
    } else {
      card.append(
        title,
        node('p', `${when(entry.startedAt)} – ${when(entry.endedAt)} · ${duration}`),
      );
    }
    if (!places.some((p) => endpointLabel(entry, [p]) === p.name)) {
      const save = node('button', 'Save Place');
      save.className = 'secondary';
      save.onclick = run(() => saveStopAsPlace(entry, request));
      card.append(save);
    }
    return card;
  }
  /** Asks for a name and saves a stop as a new place. */
  async function saveStopAsPlace(entry, request) {
    const name = prompt('Name this place');
    const newId = C.uuid();
    if (!name?.trim()) return;
    if (name.trim().length > 80) throw new Error('Place name must be at most 80 characters.');
    const place = {
      name: name.trim(),
      lat: entry.latitude,
      lon: entry.longitude,
      radius: 100,
    };
    await publish('place', newId, { ...place, alerts: {} });
    places.push({ id: newId, ...place });
    if (current(request)) render(request);
  }
  /**
   * Creates a trip card with thumbnail, endpoints, times, distance, top speed and an Open trip
   * button.
   */
  function tripCard(entry, request, account) {
    const card = node('article');
    const points = tripPointsFor(entry, [...samples.values()]);
    const usable = routeSegments(points).flat();
    const at = (p, capturedAt) =>
      p && {
        latitude: p[0],
        longitude: p[1],
        accuracy: 10,
        capturedAt,
        accountId: account,
        deviceId: entry.deviceId,
      };
    const startPoint = at(entry.start, entry.startedAt) || usable[0];
    const endPoint = at(entry.end, entry.endedAt) || usable.at(-1);
    const endpoints = [startPoint, endPoint].filter(Boolean);
    const title = node('h3');
    const start = node('span');
    const finish = node('span');
    const stats = node('div');
    const open = node('button', 'Open trip');
    card.className = 'trip-row timeline-card';
    card.append(tripThumbnail(entry, request, account));
    title.append(start, node('span', ' → '), finish);
    label(
      start,
      startPoint,
      request,
      (entry.originName && places.find((p) => p.name === entry.originName)) ||
        tripBoundaryPlace(entry, endpoints, [...samples.values()], places, 'start'),
      entry.startLabel,
    );
    label(
      finish,
      endPoint,
      request,
      tripBoundaryPlace(entry, endpoints, [...samples.values()], places, 'end'),
      entry.endLabel,
    );
    card.append(
      title,
      node('p', `${time(entry.startedAt, entry)} – ${time(entry.endedAt, entry)}`),
    );
    stats.className = 'trip-stats';
    for (const text of [
      `${(entry.distanceMeters / 1609.344).toFixed(2)} mi`,
      durationText(entry.endedAt - entry.startedAt),
      `Top speed: ${(entry.maxSpeedMps * 2.236936).toFixed(0)} mph`,
    ]) {
      stats.append(node('span', text));
    }
    open.className = 'secondary';
    open.onclick = () => openTrip(entry, request, account, title.textContent);
    card.append(stats, open);
    return card;
  }
  /** Opens the trip dialog with an interactive route map. */
  function openTrip(entry, request, account, heading) {
    const dialog = node('dialog');
    const close = node('button', 'Close');
    const large = node('div');
    const detailStatus = node('p', 'Loading route for this trip…');
    dialog.className = 'trip-dialog';
    large.className = 'trip-map trip-map-large';
    dialog.append(
      close,
      node('h3', heading),
      large,
      node(
        'p',
        `${time(entry.startedAt, entry)} – ${time(entry.endedAt, entry)} · ` +
          `${(entry.distanceMeters / 1609.344).toFixed(2)} mi · Top speed ` +
          `${(entry.maxSpeedMps * 2.236936).toFixed(0)} mph`,
      ),
      detailStatus,
    );
    state.view.append(dialog);
    dialog.onclose = () => {
      large.tripMap?.remove();
      state.timelineMaps = state.timelineMaps.filter((m) => m !== large.tripMap);
      dialog.remove();
    };
    close.onclick = () => dialog.close();
    dialog.showModal();
    (async () => {
      const stillOpen = () => current(request) && dialog.open;
      try {
        const detail = await tripDetailPoints(entry, request, account, stillOpen);
        if (!detail || !stillOpen()) return;
        const portions = routeSegments(detail);
        if (portions.flat().length < 2) {
          large.textContent = 'Not enough recorded GPS for a route.';
          detailStatus.textContent =
            'Trip summary retained; route points are unavailable or still uploading.';
          return;
        }
        detailStatus.textContent = 'Recorded path; gaps are not connected.';
        await draw(large, portions, request);
      } catch (error) {
        if (stillOpen()) {
          large.textContent = 'Route unavailable';
          detailStatus.textContent = 'Could not load route: ' + error.message;
        }
      }
    })();
  }
  /** Returns the best available route points for a trip, or null if the dialog closed. */
  async function tripDetailPoints(entry, request, account, stillOpen) {
    if (entry.normalized) {
      const record = await deviceApi('/api/trips/' + encodeURIComponent(entry.id));
      if (!stillOpen()) return null;
      const detail = serverRoutePoints(entry, record, account);
      if (detail.length >= 2) return detail;
      await fetchTripRoute(entry, request, account);
      if (!stillOpen()) return null;
      return tripPointsFor({ ...entry, normalized: false }, [...samples.values()]);
    }
    await fetchTripRoute(entry, request, account);
    if (!stillOpen()) return null;
    return tripPointsFor(entry, [...samples.values()]);
  }
  /** Fetches one page of GPS history. */
  async function history(request, account) {
    const params = new URLSearchParams({
      kind: 'location',
      limit: '50',
      account_id: account,
      start: String(windowStart),
      end: String(windowEnd),
    });
    if (gpsCursor) params.set('cursor', gpsCursor);
    const response = await deviceApi('/api/records?' + params);
    if (!current(request)) return;
    for (const record of response.records) {
      const point = gpsFromRecord(
        record,
        expected,
        state.chain.rosters,
        account,
        windowStart,
        windowEnd,
      );
      if (point) samples.set(point.id, point);
    }
    gpsCursor = response.next_cursor;
    historyStatus.textContent = gpsCursor
      ? 'Recent GPS observations loaded. Earlier stops are loaded as you scroll.'
      : 'Showing all accessible GPS observations in this selected range.';
  }
  /**
   * Fetches the GPS points within one trip's time range, for older trips without a server route.
   */
  async function fetchTripRoute(trip, request, account) {
    let cursor = null;
    let pages = 0;
    do {
      const params = new URLSearchParams({
        kind: 'location',
        limit: '50',
        account_id: account,
        device_id: trip.deviceId,
        start: String(Math.max(0, trip.startedAt - 120000)),
        end: String(trip.endedAt + 120000),
      });
      if (cursor) params.set('cursor', cursor);
      const response = await deviceApi('/api/records?' + params);
      if (!current(request)) return;
      for (const record of response.records) {
        const point = gpsFromRecord(
          record,
          expected,
          state.chain.rosters,
          account,
          Math.max(0, trip.startedAt - 120000),
          trip.endedAt + 120000,
          trip.deviceId,
        );
        if (point) samples.set(point.id, point);
      }
      cursor = response.next_cursor;
      pages++;
    } while (cursor && pages < 20 && current(request));
  }
  /** Loads the next page of history when the list is scrolled near the bottom. */
  async function olderHistory(request, account) {
    if (scrollBusy || !current(request) || !gpsCursor) return;
    scrollBusy = true;
    moreStatus.textContent = 'Loading earlier trip and stop history…';
    try {
      if (gpsCursor) await history(request, account);
      if (!current(request)) return;
      render(request);
      moreStatus.textContent = gpsCursor
        ? 'Scroll to the bottom for earlier observations.'
        : 'All accessible history in this range is loaded.';
    } catch (error) {
      if (current(request)) {
        moreStatus.textContent = 'Older history could not load: ' + error.message;
      }
    } finally {
      scrollBusy = false;
    }
  }
  /** Reloads the trips for the selected member and range. */
  async function load() {
    const request = ++requestNumber;
    const account = form.elements.member.value;
    if (!account) {
      status.textContent = 'No household members available.';
      return;
    }
    status.textContent = 'Loading trip summaries…';
    moreStatus.textContent = '';
    try {
      await sync();
      if (!current(request)) return;
      trips = new Map();
      samples = new Map();
      gpsCursor = null;
      scrollBusy = false;
      thumbnails.clear();
      outlineRequests.clear();
      windowEnd = Date.now() + 300000;
      windowStart = Date.now() - Number(form.elements.days.value) * 86400000;
      list.replaceChildren();
      const household = await deviceApi('/api/view');
      if (!current(request)) return;
      places = household.records
        .filter((p) => p.kind === 'place')
        .map((p) => ({ id: p.entity_id, ...p.data }));
      const query = new URLSearchParams({
        account_id: account,
        start: String(windowStart),
        end: String(windowEnd),
        include_routes: 'false',
      });
      const indexed = await deviceApi('/api/trips?' + query);
      if (!current(request)) return;
      for (const row of indexed.trips) {
        const t = {
          id: row.id,
          accountId: account,
          deviceId: row.device_id,
          startedAt: row.started_at,
          endedAt: row.ended_at,
          distanceMeters: row.distance_m,
          maxSpeedMps: row.max_speed_mps,
          samples: row.samples,
          tripId: row.trip_id || null,
          tz: typeof row.tz === 'string' && row.tz.length <= 64 ? row.tz : null,
          matched: row.matched === true,
          normalized: true,
          processing: row.processing === true,
          partial: row.partial === true,
          originName:
            typeof row.origin_name === 'string' && row.origin_name.length <= 80
              ? row.origin_name
              : null,
          startLabel:
            typeof row.start_label === 'string' && row.start_label.length <= 200
              ? row.start_label
              : null,
          endLabel:
            typeof row.end_label === 'string' && row.end_label.length <= 200 ? row.end_label : null,
          start:
            Array.isArray(row.start) && row.start.length === 2 && row.start.every(Number.isFinite)
              ? row.start
              : null,
          end:
            Array.isArray(row.end) && row.end.length === 2 && row.end.every(Number.isFinite)
              ? row.end
              : null,
          preview: Array.isArray(row.preview)
            ? row.preview
                .filter((p) => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))
                .slice(0, 80)
            : [],
        };
        trips.set(t.id, t);
      }
      render(request); // First meaningful paint: no historical GPS scan required.
      await history(request, account);
      if (!current(request)) return;
      render(request);
      moreStatus.textContent = gpsCursor
        ? 'Scroll down to load older trip and stop history automatically.'
        : 'All accessible history in this range is loaded.';
    } catch (error) {
      if (current(request)) status.textContent = 'Could not load trip summaries: ' + error.message;
    }
  }
  form.onsubmit = (event) => {
    event.preventDefault();
    load();
  };
  for (const field of ['member', 'days']) form.elements[field].onchange = () => load();
  state.tripScrollAbort?.abort();
  state.tripScrollAbort = new AbortController();
  window.addEventListener(
    'scroll',
    () => {
      if (!list.isConnected || scrollBusy || !gpsCursor || !requestNumber) return;
      // Only load more on a real scroll, even if the list already fits on screen.
      if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 420) {
        olderHistory(requestNumber, form.elements.member.value);
      }
    },
    { passive: true, signal: state.tripScrollAbort.signal },
  );
  await load();
}

/** Returns the trips to show and the stops between them, newest first. */
function timelineEntries(trips, samples, places) {
  const all = [...samples.values()];
  const values = [...trips.values()].filter(
    (t) => !isStationaryTrip(t, all) && !isInconsequentialTrip(t, all, places),
  );
  const stops = combineNearbyPlaceStops(stopsFromSamples(all, values, places), values, places, all);
  const entries = [
    ...values.map((t) => ({ ...t, kind: 'trip' })),
    ...stops.map((t) => ({ ...t, kind: 'stop' })),
  ].sort((a, b) => b.startedAt - a.startedAt);
  markCurrentStays(entries, all);
  return { values, entries };
}

/**
 * Converts the server's stored route into points. Uses each point's recorded time when present,
 * otherwise spreads the points evenly over the trip.
 */
function serverRoutePoints(entry, record, account) {
  const geometry = Array.isArray(record.route) ? record.route : [];
  const times =
    Array.isArray(record.times) && record.times.length === geometry.length ? record.times : null;
  const spread = (i) =>
    geometry.length > 1
      ? entry.startedAt +
        Math.round(((entry.endedAt - entry.startedAt) * i) / (geometry.length - 1))
      : entry.startedAt;
  return geometry
    .map((p, i) => ({ p, i }))
    .filter(({ p }) => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))
    .map(({ p, i }) => ({
      id: entry.id + ':detail:' + i,
      accountId: account,
      deviceId: entry.deviceId,
      latitude: p[0],
      longitude: p[1],
      accuracy: 5,
      normalized: true,
      capturedAt: times && Number.isFinite(times[i]) ? times[i] : spread(i),
    }));
}
