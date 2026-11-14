// Shared display geometry. Coordinates remain in approved clients.

/** Returns the great-circle distance between two points in metres. */
export function meters(a, b) {
  const r = Math.PI / 180;
  const h =
    Math.sin(((b.latitude - a.latitude) * r) / 2) ** 2 +
    Math.cos(a.latitude * r) *
      Math.cos(b.latitude * r) *
      Math.sin(((b.longitude - a.longitude) * r) / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, h))));
}

/** Returns the saved place containing the point, allowing for its accuracy, or null. */
export function matchingPlace(point, places = []) {
  if (!point) return null;
  const tolerance = Math.min(
    50,
    Math.max(15, Number.isFinite(point.accuracy) ? point.accuracy : 25),
  );
  return (
    places
      .map((p) => ({ ...p, distance: meters(point, { latitude: p.lat, longitude: p.lon }) }))
      .filter((p) => p.distance <= p.radius + tolerance)
      .sort(
        (a, b) =>
          Number(a.distance > a.radius) - Number(b.distance > b.radius) || a.distance - b.distance,
      )[0] || null
  );
}

/** Returns the name of the saved place containing the point, or its coordinates. */
export function endpointLabel(point, places = []) {
  if (!point) return 'Location unavailable';
  return (
    matchingPlace(point, places)?.name ||
    `${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}`
  );
}

/** Returns how far an address result may be from the point, based on its accuracy. */
function addressTolerance(accuracy = 25) {
  return Math.max(100, Math.min(250, Math.max(0, accuracy) * 2));
}

/**
 * Returns Google's formatted address if the result is close enough to the point, otherwise null.
 */
export function validatedGoogleReverseAddress(result, point) {
  if (
    !point ||
    typeof result?.address !== 'string' ||
    !result.address.trim() ||
    !Number.isFinite(result.lat) ||
    !Number.isFinite(result.lon) ||
    Math.abs(result.lat) > 90 ||
    Math.abs(result.lon) > 180
  ) {
    return null;
  }
  const distance = meters(point, { latitude: result.lat, longitude: result.lon });
  return distance <= addressTolerance(point.accuracy) ? result.address.trim() : null;
}

/**
 * Returns the nearest usable Google reverse geocoding result, preferring street addresses over
 * localities and skipping Plus Codes.
 */
export function selectGoogleReverseAddress(results, point) {
  const ranked = [];
  for (const item of results || []) {
    if (
      !Number.isFinite(item?.lat) ||
      !Number.isFinite(item?.lon) ||
      Math.abs(item.lat) > 90 ||
      Math.abs(item.lon) > 180
    ) {
      continue;
    }
    const types = Array.isArray(item.types) ? item.types : [];
    const address = typeof item.address === 'string' ? item.address.trim() : '';
    if (!address || types.includes('plus_code') || /^[A-Z0-9]{4,8}\+[A-Z0-9]{2,}/i.test(address)) {
      continue;
    }
    const street = types.some((t) =>
      ['street_address', 'premise', 'subpremise', 'establishment', 'point_of_interest'].includes(t),
    );
    const route = types.some((t) => ['route', 'intersection'].includes(t));
    const nearby = types.some((t) =>
      [
        'neighborhood',
        'sublocality',
        'locality',
        'postal_code',
        'administrative_area_level_3',
      ].includes(t),
    );
    const distance = meters(point, { latitude: item.lat, longitude: item.lon });
    const precise = validatedGoogleReverseAddress(item, point);
    // A town's coordinates are often its centre, kilometres away, so allow a town name but never a
    // distant street.
    if (!precise && !(nearby && distance <= 5000)) continue;
    ranked.push({
      address,
      priority: precise ? (street ? 0 : route ? 1 : nearby ? 2 : 3) : 4,
      distance,
    });
  }
  ranked.sort((a, b) => a.priority - b.priority || a.distance - b.distance);
  const best = ranked[0];
  if (!best) return null;
  const approximate = best.priority !== 0 || best.distance > Math.max(30, point.accuracy || 0);
  return approximate && !/^Near\s/i.test(best.address) ? 'Near ' + best.address : best.address;
}

/** Returns a short street address from a Nominatim result. */
export function formatAddress(result, point) {
  const a = result?.address || {};
  const lat = Number(result?.lat);
  const lon = Number(result?.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  const distance = meters(point, { latitude: lat, longitude: lon });
  if (distance > addressTolerance(point.accuracy)) return null;
  const street = [a.house_number, a.road].filter(Boolean).join(' ');
  const name = street || result.name || a.pedestrian || a.road;
  if (!name) return null;
  const text = [name, a.city || a.town || a.village || a.county, a.state]
    .filter(Boolean)
    .join(', ');
  return distance > Math.max(30, point.accuracy || 0) || !a.house_number ? 'Near ' + text : text;
}
