import assert from 'node:assert/strict';
import {
  mercator,
  frame,
  project,
  tilesFor,
  googleStaticUrl,
  googleStaticStyle,
} from '../../src/thumbnails.mjs';

const [x, y] = mercator(0, 0, 1);
assert.deepEqual([x, y], [256, 256], 'Equator/prime meridian is the centre of zoom 1');
const route = [
  [40.86, -74.42],
  [40.87, -74.4],
  [40.88, -74.38],
];

const view = frame(route, 600, 150);
assert.ok(view.zoom >= 10 && view.zoom <= 17, 'A short drive frames at street-level zoom');
for (const [px, py] of project(route, view)) {
  assert.ok(
    px >= 18 - 1 && px <= 600 - 18 + 1 && py >= 18 - 1 && py <= 150 - 18 + 1,
    'Every point lands inside the padded card',
  );
}
const tiles = tilesFor(view);
assert.ok(
  tiles.length >= 3 && tiles.length <= 12,
  'Only the handful of tiles covering the card are requested',
);
assert.ok(
  tiles.every((t) => t.x >= 0 && t.y >= 0 && t.x < 2 ** view.zoom),
  'Tile indices are valid',
);
assert.equal(frame([[91, 0]], 600, 150), null, 'Invalid coordinates produce no frame');
const point = frame([[40.86, -74.42]], 600, 150);
assert.equal(point.zoom, 17, 'A single point uses the closest zoom');
const small = frame(route, 640, 113);
const url = new URL(googleStaticUrl(small, 'synthetic-key'));
assert.equal(url.searchParams.get('size'), '640x113');
assert.equal(url.searchParams.get('zoom'), String(small.zoom));
assert.ok(
  !url.searchParams.has('path') && !url.searchParams.has('markers'),
  'Only the basemap area is requested',
);
const [lat, lon] = url.searchParams.get('center').split(',').map(Number);
const [cx, cy] = mercator(lat, lon, small.zoom);
assert.ok(
  Math.abs(cx - (small.left + 320)) < 1 && Math.abs(cy - (small.top + 56.5)) < 1,
  'Center matches the overlay frame',
);
assert.throws(() => googleStaticUrl(frame(route, 900, 150), 'k'), /too large/);
assert.ok(
  googleStaticStyle().every((rule) =>
    /^(feature:[^|]+\|)?(element:[^|]+\|)?(color:0x[0-9a-f]{6}|visibility:\w+)$/.test(rule),
  ),
  'Static style rules are well formed',
);
assert.ok(
  googleStaticStyle().includes('feature:landscape.man_made|element:geometry.fill|color:0x2a3646'),
  'Dark style keeps buildings visible',
);
console.log('Trip thumbnail framing, projection, tile selection and Google static maps passed.');
