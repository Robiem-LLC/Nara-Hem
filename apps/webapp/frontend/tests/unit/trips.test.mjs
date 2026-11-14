import assert from 'node:assert/strict';
import * as C from '../../src/crypto.mjs';
import { tripFromRecord, gpsFromRecord, durationText } from '../../src/trips.mjs';
await C.ready;
const household = C.uuid();
const a = C.keys(C.uuid(), household, 'Phone');
const b = C.keys(C.uuid(), household, 'Browser');
const outsider = C.keys(C.uuid(), household, 'Unapproved');
const roster = { revision: 1, household, devices: [C.identity(a), C.identity(b)] };
const rosters = new Map([[1, roster]]);
const start = 1700000000000;
const end = start + 600000;
const received = end + 3600000;

const data = {
  type: 'trip_summary',
  account_id: a.account_id,
  started_at: start,
  ended_at: end,
  distance_m: 1609.344,
  max_speed_mps: 20,
  samples: 36,
};

const record = (value) => ({
  envelope: C.encryptedRecord(a, roster, 'event', C.uuid(), value, 'upsert', null, end),
  received_at: received / 1000,
});

const uploaded = record(data);
const trip = tripFromRecord(uploaded, b, rosters);
assert.equal(trip.accountId, a.account_id);
assert.equal(trip.deviceId, a.id);
assert.equal(trip.startedAt, start);
assert.equal(trip.receivedAt, received);
assert.equal(trip.uploadDelayMs, 3600000);
assert.equal(trip.samples, 36);
assert.equal(
  tripFromRecord(record({ ...data, origin_name: 'Home' }), b, rosters).originName,
  'Home',
  'Signed iOS trip origin Place name must survive browser history decoding',
);
assert.equal(
  tripFromRecord(record({ ...data, origin_name: 'X'.repeat(120) }), b, rosters).originName,
  null,
  'Unbounded historical place metadata is not promoted to a label',
);
assert.equal(durationText(trip.endedAt - trip.startedAt), '10 min');
assert.equal(durationText(trip.uploadDelayMs), '1 hr 0 min');
const routed = tripFromRecord(
  record({
    ...data,
    start: [40.1, -74.1],
    end: [40.3, -74.3],
    preview: [
      [40.1, -74.1],
      [40.2, -74.2],
      [40.3, -74.3],
    ],
  }),
  b,
  rosters,
);
assert.deepEqual(
  [routed.start, routed.end, routed.preview.length],
  [[40.1, -74.1], [40.3, -74.3], 3],
  'Summary endpoints and outline are kept',
);
const damaged = tripFromRecord(
  record({ ...data, start: 'x', preview: [[40.1, -74.1], [999, 0], 'bad', [40.2, -74.2]] }),
  b,
  rosters,
);
assert.deepEqual(
  [damaged.start, damaged.preview.length],
  [[40.1, -74.1], 2],
  'Malformed route fields are dropped, not fatal',
);
assert.deepEqual(
  [trip.preview, trip.start, trip.end],
  [[], null, null],
  'Older summaries without a route stay valid',
);
assert.equal(tripFromRecord(record({ type: 'arrival' }), b, rosters), null);
assert.throws(
  () => tripFromRecord(record({ ...data, account_id: b.account_id }), b, rosters),
  /signed author/,
);
assert.throws(
  () => tripFromRecord(record({ ...data, ended_at: end - 1 }), b, rosters),
  /Invalid trip/,
);
assert.throws(
  () => tripFromRecord(record({ ...data, distance_m: -1 }), b, rosters),
  /Invalid trip/,
);
assert.throws(
  () => tripFromRecord(record({ ...data, max_speed_mps: '20' }), b, rosters),
  /Invalid trip/,
);
assert.throws(() => tripFromRecord(uploaded, outsider, rosters));
const tampered = structuredClone(uploaded);
tampered.envelope.body.captured_at--;
assert.throws(() => tripFromRecord(tampered, b, rosters));
const gps = {
  envelope: C.encryptedRecord(
    a,
    roster,
    'location',
    a.account_id,
    { lat: 45.5, lon: -122.6, accuracy: 5 },
    'upsert',
    null,
    start + 1000,
  ),
  received_at: received / 1000,
};
assert.equal(gpsFromRecord(gps, b, rosters, a.account_id, start, end).receivedAt, received);
assert.equal(gpsFromRecord(gps, b, rosters, b.account_id, start, end), null);
assert.equal(gpsFromRecord(gps, b, rosters, a.account_id, start, end, b.id), null);
assert.equal(gpsFromRecord(gps, b, rosters, a.account_id, end, end + 1000), null);
assert.ok(!JSON.stringify(uploaded).includes('trip_summary'));
console.log(
  'Verified trip ownership, offline receipt times, malformed/tampered summaries, recipient ' +
    'boundaries and GPS ranges passed.',
);

const { routeSegments, stopsFromSamples, endpointLabel } = await import('../../src/trips.mjs');

const point = (id, t, lat = 40, device = 'phone', accuracy = 5) => ({
  id,
  accountId: 'member',
  deviceId: device,
  capturedAt: start + t,
  latitude: lat,
  longitude: -74,
  accuracy,
  speedMps: 0,
});

assert.equal(
  routeSegments([point('b', 60000, 40.001), point('a', 0)]).length,
  1,
  'Capture order survives deferred uploads',
);
assert.equal(
  routeSegments([point('a', 0), point('b', 180000, 40.001)]).length,
  2,
  'Long gaps are not bridged',
);
assert.equal(
  routeSegments([point('a', 0), point('b', 15000, 41), point('c', 30000, 40.001)]).length,
  2,
  'Impossible jumps are not bridged',
);
assert.equal(
  routeSegments([point('a', 0), point('bad', 1000, 40, 'phone', 100), point('b', 2000)]).length,
  2,
  'Unreliable point breaks route',
);
assert.equal(
  routeSegments([point('a', 0), point('b', 1000, 40, 'other')]).length,
  2,
  'Devices never connect',
);
const stationary = [point('a', 0), point('b', 120000), point('c', 240000)];
assert.equal(stopsFromSamples(stationary).length, 1);
assert.equal(stopsFromSamples(stationary)[0].endedAt, start + 240000);
assert.equal(
  stopsFromSamples([point('a', 0), point('b', 600000)]).length,
  0,
  'Unknown time is not a stop',
);
assert.equal(
  stopsFromSamples(stationary, [
    { accountId: 'member', deviceId: 'phone', startedAt: start, endedAt: start + 240000 },
  ]).length,
  0,
  'Trip points are not stops',
);
assert.equal(
  stopsFromSamples([point('a', 0), point('b', 240000, 40, 'other')]).length,
  0,
  'Different devices do not establish a stop',
);
assert.equal(
  endpointLabel(point('a', 0), [{ lat: 40, lon: -74, radius: 100, name: 'Home' }]),
  'Home',
);
assert.equal(endpointLabel(null), 'Location unavailable');
console.log(
  'Route gaps, deferred ordering, spike rejection, device isolation, observed stops and ' +
    'endpoint labels passed.',
);

assert.equal(
  routeSegments([point('a', 0), point('b', 15000, 41), point('c', 30000, 40.001)]).flat().length,
  2,
  'Rejected spike does not distort map bounds',
);

const { matchingPlace, formatAddress, validatedGoogleReverseAddress, selectGoogleReverseAddress } =
  await import('../../src/locations.mjs');

const home = { id: 'home', name: 'Home', lat: 40, lon: -74, radius: 100 };
assert.equal(
  matchingPlace({ ...point('a', 0, 40.001), accuracy: 30 }, [home]).name,
  'Home',
  'Bounded drift beyond radius retains saved place',
);
assert.equal(
  formatAddress(
    {
      lat: '40',
      lon: '-74',
      address: { house_number: '123', road: 'Main Street', town: 'Town', state: 'State' },
    },
    point('a', 0),
  ),
  '123 Main Street, Town, State',
);
assert.match(
  formatAddress(
    { lat: '40.0008', lon: '-74', address: { house_number: '123', road: 'Main Street' } },
    point('a', 0),
  ),
  /^Near 123 Main Street/,
);
const here = { latitude: 45.5, longitude: -122.6, accuracy: 10 };
assert.equal(
  validatedGoogleReverseAddress(
    { address: '123 Main Street, OR', lat: 45.5002, lon: -122.6001 },
    here,
  ),
  '123 Main Street, OR',
  'Nearby Google reverse geocode remains visible',
);
assert.equal(
  validatedGoogleReverseAddress(
    { address: '5R58+F8C Hanoi, Vietnam', lat: 21.008, lon: 105.815 },
    here,
  ),
  null,
  'Cross-continent geocode is rejected despite a valid displayed address',
);
assert.equal(
  validatedGoogleReverseAddress({ address: 'Untrusted', lat: 45.505, lon: -122.6 }, here),
  null,
  'A result hundreds of meters away does not replace an exact GPS endpoint',
);
assert.equal(
  validatedGoogleReverseAddress({ address: 'No coordinate', lat: NaN, lon: -122.6 }, here),
  null,
  'Google result must have valid coordinates',
);
assert.equal(
  validatedGoogleReverseAddress({ address: ' ', lat: 45.5, lon: -122.6 }, here),
  null,
  'Blank reverse lookup labels are ignored',
);
assert.equal(
  selectGoogleReverseAddress(
    [
      { address: '5R58+F8C Hanoi Vietnam', lat: 21.008, lon: 105.815, types: ['plus_code'] },
      { address: 'Fairview, OR', lat: 45.50001, lon: -122.6, types: ['locality'] },
      {
        address: '625 Church St, Fairview, OR',
        lat: 45.50003,
        lon: -122.6,
        types: ['street_address'],
      },
    ],
    here,
  ),
  '625 Church St, Fairview, OR',
  'Near and precise street-level result wins over unrelated Plus Code',
);
assert.equal(
  selectGoogleReverseAddress(
    [
      { address: '9C3W+X4 Fairview', lat: 45.5, lon: -122.6, types: ['plus_code'] },
      { address: 'Lakeside, OR', lat: 45.50001, lon: -122.6, types: ['locality'] },
    ],
    here,
  ),
  'Near Lakeside, OR',
  'Locality fallback beats an unhelpful Plus Code',
);
assert.equal(
  selectGoogleReverseAddress(
    [
      { address: '9XG5+74 Unknown', lat: 42.3, lon: -76.5, types: ['plus_code'] },
      { address: 'Fairview, Oregon, USA', lat: 45.52, lon: -122.6, types: ['locality'] },
    ],
    here,
  ),
  'Near Fairview, Oregon, USA',
  'A nearby municipal label beats bare coordinates without an exact street result',
);
assert.equal(
  selectGoogleReverseAddress(
    [{ address: '5R58+F8C Hanoi Vietnam', lat: 21.008, lon: 105.815, types: ['plus_code'] }],
    here,
  ),
  null,
  'Do not surface a geographically unrelated street address',
);

const { isStationaryTrip, isInconsequentialTrip } = await import('../../src/trips.mjs');

const tiny = {
  accountId: 'member',
  deviceId: 'phone',
  startedAt: start,
  endedAt: start + 32000,
  distanceMeters: 16,
  maxSpeedMps: 4.47,
  samples: 184,
};

const twoHomeFixes = [point('home-a', 0), point('home-b', 32000, 40.00009)];
assert.equal(
  isInconsequentialTrip(tiny, twoHomeFixes, [home]),
  true,
  '32-second 0.01-mile Home to Home movement with two retained fixes must not appear as a trip',
);
assert.equal(
  isInconsequentialTrip(tiny, twoHomeFixes, []),
  false,
  'Two endpoints without a known Place cannot prove the entire path was stationary',
);
assert.equal(
  isInconsequentialTrip(tiny, [point('a', 0), point('b', 16000, 40.00003), point('c', 32000)], []),
  true,
  'Three accurate fixes clustered within 30 m can reject unsaved-place GPS jitter',
);
assert.equal(
  isInconsequentialTrip(
    tiny,
    [point('a', 0), point('outside', 16000, 40.002), point('c', 32000)],
    [home],
  ),
  false,
  'An observed departure is never suppressed, even with a very short distance summary',
);
assert.equal(
  isInconsequentialTrip({ ...tiny, endedAt: start + 7 * 86400000 }, twoHomeFixes, [home]),
  false,
  'A week of creeping movement must never be dismissed from only two GPS fixes',
);
assert.equal(
  isInconsequentialTrip({ ...tiny, distanceMeters: 400 }, twoHomeFixes, [home]),
  false,
  'Evidence of real travelled distance outweighs identical endpoints',
);
assert.equal(
  isInconsequentialTrip(
    tiny,
    [point('a', 0, 40, 'phone', 65), point('b', 32000, 40.00009, 'phone', 65)],
    [home],
  ),
  false,
  'Poor accuracy cannot establish a negligible trip',
);
const noise = { accountId: 'member', deviceId: 'phone', startedAt: start, endedAt: start + 240000 };
assert.equal(
  isStationaryTrip(noise, [point('a', 0), point('b', 120000, 40.0001), point('c', 240000)]),
  true,
);
assert.equal(
  isStationaryTrip(noise, [point('a', 0), point('b', 120000, 40.01), point('c', 240000)]),
  false,
  'Real round trips are preserved',
);
const night = [
  point('a', 0),
  point('b', 240000, 40.001),
  point('c', 720000, 40.0001),
  point('d', 960000),
];

const consolidated = stopsFromSamples(night, [], [home]);
assert.equal(consolidated.length, 1);
assert.equal(consolidated[0].gapMillis, 480000);
assert.equal(
  stopsFromSamples(
    [point('a', 0), point('b', 240000), point('c', 4000000), point('d', 4240000)],
    [],
    [home],
  ).length,
  2,
  'Long missing history remains separate',
);

const { combineNearbyPlaceStops } = await import('../../src/trips.mjs');

const nearby = (id, from, to, device = 'phone') => ({
  id,
  accountId: 'member',
  deviceId: device,
  startedAt: start + from,
  endedAt: start + to,
  latitude: 40,
  longitude: -74,
  gapMillis: 0,
});

const fragments = [
  nearby('a', 0, 240000),
  nearby('b', 540000, 780000, 'second'),
  nearby('c', 1320000, 1560000),
];

const retrospectivelyGrouped = combineNearbyPlaceStops(fragments, [], [home]);
assert.equal(
  retrospectivelyGrouped.length,
  1,
  'Adjacent Home cards merge across observations/devices',
);
assert.equal(
  retrospectivelyGrouped[0].gapMillis,
  840000,
  'Merging accounts for unknown observed gaps',
);
assert.equal(
  combineNearbyPlaceStops(
    fragments,
    [{ accountId: 'member', startedAt: start + 260000, endedAt: start + 500000 }],
    [home],
  ).length,
  2,
  'A real trip blocks the first merge',
);
assert.equal(
  combineNearbyPlaceStops(fragments, [], [home], [point('left', 380000, 40.02)]).length,
  2,
  'Observed departure blocks the first merge',
);
assert.equal(
  combineNearbyPlaceStops([nearby('a', 0, 240000), nearby('b', 3600000, 3840000)], [], [home])
    .length,
  1,
  'Hours at home with the phone quiet are one stay',
);
const afternoon = [0, 1, 2, 3, 4].map((hour) =>
  nearby('h' + hour, hour * 3600000, hour * 3600000 + 1200000),
);

const stay = combineNearbyPlaceStops(afternoon, [], [home]);
assert.equal(stay.length, 1, 'An afternoon at home is one card');
assert.equal(stay[0].endedAt - stay[0].startedAt, 4 * 3600000 + 1200000);
assert.equal(
  combineNearbyPlaceStops(afternoon, [], [home], [point('drift', 1500000, 40.0015, 'phone', 80)])
    .length,
  1,
  'A fuzzy reading outside Home is not a departure',
);
assert.equal(
  combineNearbyPlaceStops([
    nearby('a', 0, 240000),
    nearby('b', 20 * 3600000, 20 * 3600000 + 240000),
  ]).length,
  2,
  'A whole day apart stays separate',
);
assert.equal(
  combineNearbyPlaceStops([nearby('a', 0, 240000), nearby('b', 3600000, 3840000)]).length,
  1,
  'The same unsaved spot is one stay too',
);
const checkIns = [0, 900000, 1800000, 2700000, 3600000].map((t, i) => point('p' + i, t));
assert.equal(stopsFromSamples(checkIns).length, 1, 'Parked check-ins every 15 minutes are a stop');

const { markCurrentStays } = await import('../../src/trips.mjs');

const timeline = [
  { kind: 'stop', accountId: 'member', startedAt: start + 3600000, endedAt: start + 7200000 },
  { kind: 'trip', accountId: 'member', startedAt: start, endedAt: start + 3000000 },
];
markCurrentStays(timeline, [point('last', 7200000), point('fuzzy', 7300000, 40, 'phone', 500)]);
assert.equal(timeline[0].current, true, 'The newest stay is where they are now');
assert.equal(timeline[1].current, undefined);
const moved = [{ ...timeline[0], current: undefined }];
markCurrentStays(moved, [point('later', 7500000, 40.01)]);
assert.equal(moved[0].current, false, 'A later reading means they have moved on');

const { tripPointsFor, tripBoundaryPlace } = await import('../../src/trips.mjs');

const homeTrip = {
  accountId: 'member',
  deviceId: 'phone',
  startedAt: start + 120000,
  endedAt: start + 600000,
};

const awayFirst = point('away-start', 120000, 40.005);
const awayLast = point('away-end', 600000, 40.006);
const justBefore = point('home-before', 90000);
const justAfter = point('home-after', 650000);
assert.equal(
  tripBoundaryPlace(homeTrip, [awayFirst, awayLast], [justBefore, justAfter], [home], 'start')
    ?.name,
  'Home',
  'Reliable Home observation before a recorded departure is the start label',
);
assert.equal(
  tripBoundaryPlace(homeTrip, [awayFirst, awayLast], [justBefore, justAfter], [home], 'end')?.name,
  'Home',
  'Reliable Home observation after an arrival is the end label',
);
assert.equal(
  tripBoundaryPlace(homeTrip, [awayFirst, awayLast], [point('parked', -420000)], [home], 'start')
    ?.name,
  'Home',
  'A parked check-in at Home 9 minutes before GPS started is still where the trip began',
);
assert.equal(
  tripBoundaryPlace(
    homeTrip,
    [awayFirst, awayLast],
    [point('parked', -420000), point('elsewhere', -200000, 40.02)],
    [home],
    'start',
  ),
  null,
  'A later reading somewhere else means the trip began there, not at Home',
);
assert.equal(
  tripBoundaryPlace(homeTrip, [awayFirst, awayLast], [point('old', -2400000)], [home], 'start'),
  null,
  'A Home reading over half an hour earlier is too old to say where the trip began',
);
assert.equal(
  tripBoundaryPlace(
    homeTrip,
    [awayFirst, awayLast],
    [point('wrong-phone', 90000, 40, 'other')],
    [home],
    'start',
  ),
  null,
  'Another device cannot confirm this trip starting at Home',
);
const taggedTrip = {
  accountId: 'member',
  deviceId: 'phone',
  startedAt: start,
  endedAt: start + 30000,
  tripId: 'b'.repeat(32),
};

const tagged = [
  { ...point('legacy', 0), tripId: null },
  { ...point('yes', 15000), tripId: 'b'.repeat(32) },
  { ...point('no', 20000), tripId: 'a'.repeat(32) },
];
assert.deepEqual(
  tripPointsFor(taggedTrip, tagged).map((p) => p.id),
  ['legacy', 'yes'],
  'Trip ID rejects a foreign trip but old untagged data remains compatible',
);

assert.deepEqual(
  tripPointsFor({ ...taggedTrip, normalized: true }, [
    { ...point('raw', 0), tripId: taggedTrip.tripId },
    { ...point('processed', 15000), tripId: taggedTrip.tripId, normalized: true },
  ]).map((x) => x.id),
  ['processed'],
  'Do not mix legacy GPS into a verified normalized route',
);
