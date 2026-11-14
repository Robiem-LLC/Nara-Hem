// Street address consent, caching and OpenStreetMap lookups in the web client.
import assert from 'node:assert/strict';
import test from 'node:test';

// Just enough of a browser for Leaflet, which the map code imports, to load.
globalThis.window = globalThis;
globalThis.devicePixelRatio = 1;
globalThis.screen = {};
globalThis.document = {
  documentElement: { style: {} },
  createElement: () => ({ style: {}, getContext: null }),
};

/** localStorage kept in a Map, with enumerable keys like the real one. */
const storage = new Map();
globalThis.localStorage = new Proxy(
  {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
  },
  {
    ownKeys: () => [...storage.keys()],
    getOwnPropertyDescriptor: () => ({ enumerable: true, configurable: true }),
  },
);

const asked = [];
globalThis.fetch = async (url) => {
  asked.push(String(url));
  if (url.searchParams.get('q') === 'nowhere') return { ok: true, json: async () => [] };
  if (url.searchParams.get('q') === 'offline') return { ok: false };
  if (url.pathname === '/search') {
    return {
      ok: true,
      json: async () => [{ display_name: 'Town Hall', lat: '51.5', lon: '-0.1' }],
    };
  }
  if (url.searchParams.get('lat') === '9') return { ok: false };
  return {
    ok: true,
    json: async () => ({
      lat: url.searchParams.get('lat'),
      lon: url.searchParams.get('lon'),
      address: { house_number: '12', road: 'High Street', town: 'Oxford' },
    }),
  };
};

const addresses = await import('../../src/client/addresses.mjs');
const { state } = await import('../../src/client/state.mjs');

test('consent is asked once and remembered', () => {
  globalThis.confirm = () => true;
  assert.equal(addresses.addressesEnabled(), false);
  assert.equal(addresses.requestAddressConsent(), true);
  globalThis.confirm = () => assert.fail('asked twice');
  assert.equal(addresses.requestAddressConsent(), true);
  assert.equal(addresses.addressesEnabled(), true);
});

test('providers are named for people', () => {
  assert.equal(addresses.providerName('google'), 'Google');
  assert.equal(addresses.providerName(), 'OpenStreetMap');
});

test('address search finds a place or explains why not', async () => {
  assert.deepEqual(await addresses.forwardAddress('town hall'), {
    address: 'Town Hall',
    lat: 51.5,
    lon: -0.1,
  });
  await assert.rejects(addresses.forwardAddress('nowhere'), /Address not found/);
  await assert.rejects(addresses.forwardAddress('offline'), /unavailable/);
});

test('reverse lookups are cached in memory and in storage, and forgotten at sign-out', async () => {
  storage.set('narahem.address-lookup', 'on');
  const first = await addresses.reverseAddress(51.75, -1.25);
  assert.match(first, /High Street/);
  const before = asked.length;
  assert.equal(await addresses.reverseAddress(51.75, -1.25), first);
  assert.equal(asked.length, before);
  assert.ok([...storage.keys()].some((key) => key.startsWith('narahem.address.')));
  assert.equal(await addresses.reverseAddress(9, 9), null);
  storage.set('narahem.address.openstreetmap:1.0000,1.0000:1', 'not json');
  assert.match(await addresses.reverseAddress(1, 1), /High Street/);
  addresses.forgetSavedLocations();
  assert.ok(![...storage.keys()].some((key) => key.startsWith('narahem.address.')));
  storage.set('narahem.address-lookup', 'off');
  assert.equal(await addresses.reverseAddress(51.75, -1.25), null);
});

test('distances between points are great-circle metres', () => {
  assert.equal(addresses.metersBetween(0, 0, 0, 0), 0);
  assert.ok(Math.abs(addresses.metersBetween(0, 0, 0, 1) - 111195) < 10);
  assert.equal(state.activeMapConfig.provider, 'openstreetmap');
});
