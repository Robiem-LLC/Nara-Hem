import assert from 'node:assert/strict';
import { destinationCoordinates, externalDirectionsUrl } from '../../src/directions.mjs';

assert.equal(destinationCoordinates(40.12345678, -74.22222229), '40.1234568,-74.2222223');
assert.equal(
  externalDirectionsUrl(40, -74, 'Mozilla/5.0 (Linux; Android 15)'),
  'geo:0,0?q=40.0000000%2C-74.0000000',
);
assert.equal(
  externalDirectionsUrl(40, -74, 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)'),
  'https://maps.apple.com/?daddr=40.0000000%2C-74.0000000',
);
assert.equal(
  externalDirectionsUrl(40, -74, 'Mozilla/5.0 desktop'),
  'https://www.google.com/maps/dir/?api=1&destination=40.0000000%2C-74.0000000&dir_action=navigate',
);
for (const [lat, lon] of [
  [NaN, 20],
  [Infinity, 2],
  [-91, 0],
  [0, 180.01],
]) {
  assert.throws(() => externalDirectionsUrl(lat, lon, ''), RangeError);
}
console.log('External directions link tests passed');
