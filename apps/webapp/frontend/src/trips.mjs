import { decryptRecord } from './crypto.mjs';
import { meters, matchingPlace } from './locations.mjs';
export { meters, endpointLabel } from './locations.mjs';

/** The longest quiet spell a stay can span: a phone left still overnight checks in rarely. */
const STAY_GAP = 16 * 3600000;

/** How far back to look for where a trip began: a parked phone checks in only every 15 minutes or
 * so, and GPS starts a little after the car does. Ends look only two minutes ahead. */
const BOUNDARY_WINDOW = 30 * 60000;

/** Readings this close to the trip may be GPS warming up, so they don't rule out a place. */
const WARM_UP = 120000;

/** Returns true for a finite number. */
const finite = (value) => typeof value === 'number' && Number.isFinite(value);

/** Decrypts a trip summary record, or returns null if it isn't one. */
export function tripFromRecord(record, vault, rosters) {
  const payload = decryptRecord(record.envelope, vault, rosters);
  if (
    payload.kind !== 'event' ||
    payload.operation !== 'upsert' ||
    payload.data?.type !== 'trip_summary'
  ) {
    return null;
  }
  const sender = rosters.get(payload.revision)?.devices.find((d) => d.id === payload.sender);
  const data = payload.data;
  if (!sender || data.account_id !== sender.account_id) {
    throw new Error('Trip does not belong to its signed author.');
  }
  if (
    !Number.isSafeInteger(data.started_at) ||
    data.started_at <= 0 ||
    !Number.isSafeInteger(data.ended_at) ||
    data.ended_at < data.started_at ||
    data.ended_at !== payload.captured_at ||
    !finite(data.distance_m) ||
    data.distance_m < 0 ||
    !finite(data.max_speed_mps) ||
    data.max_speed_mps < 0 ||
    !Number.isSafeInteger(data.samples) ||
    data.samples < 0 ||
    !finite(record.received_at)
  ) {
    throw new Error('Invalid trip summary.');
  }
  return {
    id: payload.id,
    accountId: data.account_id,
    deviceId: payload.sender,
    startedAt: data.started_at,
    endedAt: data.ended_at,
    distanceMeters: data.distance_m,
    maxSpeedMps: data.max_speed_mps,
    samples: data.samples,
    tripId: /^[a-f0-9]{32}$/.test(data.trip_id || '') ? data.trip_id : null,
    capturedAt: payload.captured_at,
    receivedAt: record.received_at * 1000,
    uploadDelayMs: Math.max(0, record.received_at * 1000 - payload.captured_at),
    originName:
      typeof data.origin_name === 'string' && data.origin_name.trim().length <= 80
        ? data.origin_name.trim() || null
        : null,
    ...summaryRoute(data),
  };
}

/** Returns true for a valid [lat, lon] pair. */
const coordinate = (p) =>
  Array.isArray(p) &&
  p.length === 2 &&
  finite(p[0]) &&
  Math.abs(p[0]) <= 90 &&
  finite(p[1]) &&
  Math.abs(p[1]) <= 180;

/** Returns the endpoints and outline from a trip summary, dropping malformed fields. */
function summaryRoute(data) {
  const preview = Array.isArray(data.preview) ? data.preview.filter(coordinate).slice(0, 160) : [];
  const start = coordinate(data.start) ? data.start : preview[0] || null;
  const end = coordinate(data.end) ? data.end : preview.at(-1) || null;
  return { preview: preview.length >= 2 ? preview : [], start, end };
}

/** Decrypts a location record into a GPS point, or returns null if it is unusable. */
export function gpsFromRecord(
  record,
  vault,
  rosters,
  accountId,
  start = 0,
  end = Number.MAX_SAFE_INTEGER,
  deviceId = null,
) {
  const p = decryptRecord(record.envelope, vault, rosters);
  const d = p.data;
  if (
    p.kind !== 'location' ||
    p.operation !== 'upsert' ||
    p.entity_id !== accountId ||
    (deviceId && p.sender !== deviceId) ||
    p.captured_at < start ||
    p.captured_at > end
  ) {
    return null;
  }
  if (
    !finite(d?.lat) ||
    Math.abs(d.lat) > 90 ||
    !finite(d.lon) ||
    Math.abs(d.lon) > 180 ||
    !finite(d.accuracy) ||
    d.accuracy < 0 ||
    !finite(record.received_at)
  ) {
    throw new Error('Invalid GPS sample.');
  }
  return {
    id: p.id,
    accountId: p.entity_id,
    deviceId: p.sender,
    speedMps: finite(d.speed_mps) ? d.speed_mps : null,
    capturedAt: p.captured_at,
    receivedAt: record.received_at * 1000,
    latitude: d.lat,
    longitude: d.lon,
    accuracy: d.accuracy,
    tripId: /^[a-f0-9]{32}$/.test(d.trip_id || '') ? d.trip_id : null,
  };
}

/**
 * Returns the saved place where a trip started or ended, from the fixes before the start or after
 * the end: the nearest one in time decides, unless it is within the GPS warm-up.
 */
export function tripBoundaryPlace(trip, routePoints, nearbySamples, places, side) {
  const start = side === 'start';
  const routePoint = start ? routePoints[0] : routePoints.at(-1);
  const direct = matchingPlace(routePoint, places);
  if (direct) return direct;
  if (!routePoint) return null;
  const boundary = start ? trip.startedAt : trip.endedAt;
  const candidates = nearbySamples
    .filter(
      (p) =>
        p.accountId === trip.accountId &&
        p.deviceId === trip.deviceId &&
        Number.isFinite(p.capturedAt) &&
        Number.isFinite(p.latitude) &&
        Number.isFinite(p.longitude) &&
        Number.isFinite(p.accuracy) &&
        p.accuracy >= 0 &&
        p.accuracy <= 70 &&
        (start
          ? p.capturedAt <= boundary && p.capturedAt >= boundary - BOUNDARY_WINDOW
          : p.capturedAt >= boundary && p.capturedAt <= boundary + WARM_UP),
    )
    .sort((a, b) => Math.abs(a.capturedAt - boundary) - Math.abs(b.capturedAt - boundary));
  for (const fix of candidates) {
    const place = matchingPlace(fix, places);
    const seconds = Math.abs(routePoint.capturedAt - fix.capturedAt) / 1000;
    if (
      place &&
      seconds >= 1 &&
      meters(routePoint, fix) <= 65 * seconds + routePoint.accuracy + fix.accuracy
    ) {
      return place;
    }
    // Past the warm-up, the nearest reading somewhere else means they set off from there.
    if (!place && Math.abs(fix.capturedAt - boundary) > WARM_UP) return null;
  }
  return null;
}

/** Returns the GPS points belonging to a trip, oldest first. */
export function tripPointsFor(trip, samples) {
  return samples
    .filter(
      (p) =>
        p.deviceId === trip.deviceId &&
        p.accountId === trip.accountId &&
        p.capturedAt >= trip.startedAt &&
        p.capturedAt <= trip.endedAt &&
        (!trip.normalized || p.normalized === true) &&
        (!trip.tripId || !p.tripId || trip.tripId === p.tripId),
    )
    .sort((a, b) => a.capturedAt - b.capturedAt);
}

/** Formats a duration as "45 sec", "12 min" or "1 hr 5 min". */
export function durationText(ms) {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds} sec`;
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} hr ${minutes % 60} min` : `${minutes} min`;
}

/** Returns true for a GPS point with valid coordinates and accuracy. */
const usable = (p) =>
  Number.isFinite(p.latitude) &&
  Math.abs(p.latitude) <= 90 &&
  Number.isFinite(p.longitude) &&
  Math.abs(p.longitude) <= 180 &&
  Number.isFinite(p.accuracy) &&
  p.accuracy >= 0 &&
  p.accuracy <= 70;

/**
 * Splits points into drawable segments, breaking at long gaps, device changes, inaccurate points
 * and implausible jumps.
 */
export function routeSegments(samples) {
  // Retried uploads can create several records with the same capture time; they don't split the
  // route.
  const unique = new Map();
  const result = [];
  let segment = [];
  let last = null;
  for (const p of samples) {
    const key = p.accountId + ':' + p.deviceId + ':' + p.capturedAt;
    const prior = unique.get(key);
    if (
      !prior ||
      (usable(p) && !usable(prior)) ||
      (usable(p) === usable(prior) && Number(p.accuracy) < Number(prior.accuracy))
    ) {
      unique.set(key, p);
    }
  }
  for (const p of [...unique.values()].sort((a, b) => a.capturedAt - b.capturedAt)) {
    if (!usable(p)) {
      segment = [];
      last = null;
      continue;
    }
    const dt = last ? (p.capturedAt - last.capturedAt) / 1000 : 0;
    if (
      last &&
      dt > 0 &&
      dt <= 120 &&
      p.deviceId === last.deviceId &&
      p.accountId === last.accountId &&
      !(p.normalized && last.normalized) &&
      meters(last, p) > 65 * dt + last.accuracy + p.accuracy
    ) {
      segment = [];
      last = null;
      continue;
    }
    if (
      !last ||
      dt <= 0 ||
      dt > 120 ||
      p.deviceId !== last.deviceId ||
      p.accountId !== last.accountId
    ) {
      segment = [];
      result.push(segment);
    }
    segment.push(p);
    last = p;
  }
  return result;
}

/** Returns true if the trip's recorded points show it never left one spot. */
export function isStationaryTrip(trip, samples) {
  const points = routeSegments(tripPointsFor(trip, samples)).flat();
  if (
    points.length < 3 ||
    points[0].capturedAt - trip.startedAt > 120000 ||
    trip.endedAt - points.at(-1).capturedAt > 120000
  ) {
    return false;
  }
  if (points.some((p, i) => i && p.capturedAt - points[i - 1].capturedAt > 300000)) return false;
  const sorted = points.map((p) => p.accuracy).sort((a, b) => a - b);
  const tolerance = Math.max(60, Math.min(100, 2 * sorted[Math.floor(sorted.length / 2)]));
  const center = {
    latitude: points.map((p) => p.latitude).sort((a, b) => a - b)[Math.floor(points.length / 2)],
    longitude: points.map((p) => p.longitude).sort((a, b) => a - b)[Math.floor(points.length / 2)],
  };
  return points.every((p) => meters(center, p) <= tolerance);
}

/**
 * Returns true for a very short movement that never left a place's boundary. Only hides it from the
 * list.
 */
export function isInconsequentialTrip(trip, samples, places = []) {
  const duration = trip.endedAt - trip.startedAt;
  if (
    !Number.isFinite(duration) ||
    duration < 0 ||
    duration > 120000 ||
    !Number.isFinite(trip.distanceMeters) ||
    trip.distanceMeters > 45 ||
    !Number.isFinite(trip.maxSpeedMps) ||
    trip.maxSpeedMps > 10
  ) {
    return false;
  }
  const points = routeSegments(tripPointsFor(trip, samples)).flat();
  if (points.length < 2 || points.some((p) => p.accuracy > 40)) return false;
  const atStart = matchingPlace(points[0], places);
  if (atStart) {
    const center = { latitude: atStart.lat, longitude: atStart.lon };
    return points.every((p) => meters(p, center) <= atStart.radius + Math.min(10, p.accuracy));
  }
  return points.length >= 3 && points.every((p) => meters(points[0], p) <= 30);
}

/** Derives stops between trips from GPS history. */
export function stopsFromSamples(samples, trips = [], places = []) {
  const stops = [];
  const groups = new Map();
  for (const p of samples) {
    const key = p.accountId + ':' + p.deviceId;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(p);
  }
  for (const points of groups.values()) {
    let cluster = [];
    let place = null;
    const finish = () => {
      // Readings far apart only make a stop when there are several: two alone leave the time
      // between them unknown.
      const spread = cluster.some((p, i) => i && p.capturedAt - cluster[i - 1].capturedAt > 300000);
      if (
        cluster.length >= (spread ? 3 : 2) &&
        cluster.at(-1).capturedAt - cluster[0].capturedAt >= 180000
      ) {
        const a = cluster[0];
        const b = cluster.at(-1);
        let gapMillis = 0;
        for (let i = 1; i < cluster.length; i++) {
          const dt = cluster[i].capturedAt - cluster[i - 1].capturedAt;
          if (dt > 300000) gapMillis += dt;
        }
        stops.push({
          id: 'stop:' + a.id,
          accountId: a.accountId,
          deviceId: a.deviceId,
          startedAt: a.capturedAt,
          endedAt: b.capturedAt,
          latitude: place ? place.lat : a.latitude,
          longitude: place ? place.lon : a.longitude,
          gapMillis,
        });
      }
      cluster = [];
      place = null;
    };
    for (const p of points.sort((a, b) => a.capturedAt - b.capturedAt)) {
      if (!usable(p)) continue;
      if (
        trips.some(
          (t) =>
            t.deviceId === p.deviceId &&
            t.accountId === p.accountId &&
            p.capturedAt >= t.startedAt &&
            p.capturedAt <= t.endedAt,
        )
      ) {
        finish();
        continue;
      }
      const nextPlace = matchingPlace(p, places);
      const same = place && nextPlace && place.id === nextPlace.id;
      if (cluster.length) {
        // A parked phone checks in about every 15 minutes, so allow that between readings.
        const dt = p.capturedAt - cluster.at(-1).capturedAt;
        if (dt > 1800000 || (!same && meters(cluster[0], p) > 75 + Math.min(50, p.accuracy))) {
          finish();
        }
      }
      if ((p.speedMps || 0) >= 2.8 && !nextPlace) continue;
      if (!cluster.length) place = nextPlace;
      cluster.push(p);
    }
    finish();
  }
  return stops.sort((a, b) => b.startedAt - a.startedAt);
}

/**
 * Merges consecutive stops at the same place (a saved place, or the same spot) into one stay,
 * however long the phone was quiet in between, unless a trip or a clear departure came between.
 */
export function combineNearbyPlaceStops(stops, trips = [], places = [], samples = []) {
  const result = [];
  for (const stop of [...stops].sort((a, b) => a.startedAt - b.startedAt)) {
    const prior = result.at(-1);
    const gap = prior ? stop.startedAt - prior.endedAt : Infinity;
    const place =
      prior &&
      matchingPlace({ latitude: prior.latitude, longitude: prior.longitude, accuracy: 0 }, places);
    const samePlace =
      prior &&
      (place
        ? matchingPlace({ latitude: stop.latitude, longitude: stop.longitude, accuracy: 0 }, [
            place,
          ])
        : meters(prior, stop) <= 100);
    // Only a clear reading counts as leaving: one fuzzy fix drifting outside is still home.
    const center = place ? { latitude: place.lat, longitude: place.lon } : prior;
    const reach = place ? place.radius : 75;
    const away = (p) =>
      p.accuracy <= 50 && meters(center, p) > reach + Math.max(100, 2 * p.accuracy);
    const tripBetween =
      prior &&
      trips.some(
        (t) =>
          t.accountId === stop.accountId &&
          t.startedAt < stop.startedAt &&
          t.endedAt > prior.endedAt,
      );
    const observedDeparture =
      prior &&
      samples.some(
        (p) =>
          p.accountId === stop.accountId &&
          p.capturedAt > prior.endedAt &&
          p.capturedAt < stop.startedAt &&
          usable(p) &&
          away(p),
      );
    if (
      prior &&
      prior.accountId === stop.accountId &&
      samePlace &&
      gap >= 0 &&
      gap <= STAY_GAP &&
      !tripBetween &&
      !observedDeparture
    ) {
      result[result.length - 1] = {
        ...prior,
        endedAt: Math.max(prior.endedAt, stop.endedAt),
        gapMillis: (prior.gapMillis || 0) + (stop.gapMillis || 0) + gap,
      };
    } else {
      result.push({ ...stop });
    }
  }
  return result.sort((a, b) => b.startedAt - a.startedAt);
}

/**
 * Marks each member's newest stay as current when nothing came after it: no trip and no clear
 * reading later than the stay's last one. Entries are newest first.
 */
export function markCurrentStays(entries, samples) {
  const latest = new Map();
  for (const p of samples) {
    if (!(Number(p.accuracy) <= 100)) continue;
    latest.set(p.accountId, Math.max(latest.get(p.accountId) ?? 0, p.capturedAt));
  }
  const seen = new Set();
  for (const entry of entries) {
    if (seen.has(entry.accountId)) continue;
    seen.add(entry.accountId);
    entry.current = entry.kind === 'stop' && (latest.get(entry.accountId) ?? 0) <= entry.endedAt;
  }
}
