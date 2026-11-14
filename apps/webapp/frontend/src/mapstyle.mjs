// Map styling. With a Google key: classic dark styled-map rules (no Map ID needed).
// Without one: OpenStreetMap's own standard tiles, which need no key.

/** Dark Google Maps style matching the app. */
export const GOOGLE_DARK_STYLES = [
  { elementType: 'geometry', stylers: [{ color: '#1f2a36' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#1f2a36' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#8a96a8' }] },
  {
    featureType: 'administrative.locality',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#c3ccd8' }],
  },
  { featureType: 'poi', elementType: 'labels.icon', stylers: [{ visibility: 'off' }] },
  { featureType: 'poi', elementType: 'labels.text.fill', stylers: [{ color: '#7c8797' }] },
  { featureType: 'poi.park', elementType: 'geometry', stylers: [{ color: '#1d3330' }] },
  // Buildings: lighter than the base, or the catch-all geometry rule above hides them.
  {
    featureType: 'landscape.man_made',
    elementType: 'geometry.fill',
    stylers: [{ color: '#2a3646' }],
  },
  {
    featureType: 'landscape.man_made',
    elementType: 'geometry.stroke',
    stylers: [{ color: '#3b4859' }],
  },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#334155' }] },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: [{ color: '#1a2330' }] },
  { featureType: 'road', elementType: 'labels.text.fill', stylers: [{ color: '#9aa6b6' }] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#475569' }] },
  { featureType: 'road.highway', elementType: 'labels.text.fill', stylers: [{ color: '#cbd5e1' }] },
  { featureType: 'transit', elementType: 'geometry', stylers: [{ color: '#263241' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#0f1b2b' }] },
  { featureType: 'water', elementType: 'labels.text.fill', stylers: [{ color: '#4b5b70' }] },
];

/** OpenStreetMap tile URL template. */
export const OSM_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

/** Attribution OpenStreetMap requires on maps. */
export const OSM_TILE_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener ' +
  'noreferrer">OpenStreetMap contributors</a>';
