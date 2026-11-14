/** Returns "lat,lon" for a directions link, or null if the coordinates are invalid. */
export function destinationCoordinates(latitude, longitude) {
  const lat = Number(latitude);
  const lon = Number(longitude);
  if (
    !Number.isFinite(lat) ||
    !Number.isFinite(lon) ||
    lat < -90 ||
    lat > 90 ||
    lon < -180 ||
    lon > 180
  ) {
    throw new RangeError('No valid location available for directions.');
  }
  return lat.toFixed(7) + ',' + lon.toFixed(7);
}

/**
 * Returns a directions URL for the platform: a geo: link on Android, Apple Maps on iOS, Google Maps
 * directions on desktop.
 */
export function externalDirectionsUrl(latitude, longitude, agent = '') {
  const destination = encodeURIComponent(destinationCoordinates(latitude, longitude));
  if (/Android/i.test(agent)) return 'geo:0,0?q=' + destination;
  if (/iPad|iPhone|iPod/i.test(agent)) return 'https://maps.apple.com/?daddr=' + destination;
  return (
    'https://www.google.com/maps/dir/?api=1&destination=' + destination + '&dir_action=navigate'
  );
}
