// Malformed, unauthorised and misconfigured requests to both push relays, and per-server tokens
// stored in KV.
import assert from 'node:assert/strict';
import { createHash, webcrypto } from 'node:crypto';
import test from 'node:test';
import apns from '../apns-relay-worker.mjs';
import fcm from '../fcm-relay-worker.mjs';

if (!globalThis.crypto) globalThis.crypto = webcrypto;

const secret = 'synthetic-relay-secret-123456';
const apnsEnv = { RELAY_AUTH_TOKEN: secret, APNS_BUNDLE_ID: 'com.example.family' };
const push = { deviceToken: 'a'.repeat(64), environment: 'production', expiresInSeconds: 60 };

const url = (path) => 'https://relay.example.invalid' + path;

const post = (path, body, { auth = secret, type = 'application/json', headers = {} } = {}) =>
  new Request(url(path), {
    method: 'POST',
    headers: { 'Content-Type': type, Authorization: 'Bearer ' + auth, ...headers },
    body,
  });

/** KV kept in a Map, recording what was written. */
function fakeKV(entries = {}) {
  const store = new Map(Object.entries(entries));
  return {
    store,
    async get(key, type) {
      const value = store.get(key);
      return value === undefined ? null : type === 'json' ? JSON.parse(value) : value;
    },
    async put(key, value) {
      store.set(key, String(value));
    },
  };
}

/** A per-server relay token and its KV entry, last used long ago. */
function storedToken(record = { lastUsed: '2000-01-01' }) {
  const token = 'T'.repeat(43);
  const key = 'token:' + createHash('sha256').update(token).digest('hex');
  return { token, key, kv: fakeKV({ [key]: JSON.stringify(record) }) };
}

test('APNs relay refuses unknown paths, strangers and malformed pushes', async () => {
  const status = async (request, env = apnsEnv) => (await apns.fetch(request, env)).status;
  assert.equal(await status(new Request(url('/elsewhere'))), 404);
  assert.equal(
    await status(post('/v1/push', JSON.stringify(push), { auth: 'wrong-secret-12345' })),
    401,
  );
  assert.equal(await status(post('/v1/diagnose', '{}', { auth: 'wrong-secret-12345' })), 401);
  assert.equal(await status(post('/v1/push', JSON.stringify(push), { type: 'text/plain' })), 415);
  assert.equal(await status(post('/v1/push', 'x'.repeat(5000))), 413);
  assert.equal(await status(post('/v1/push', '{not json')), 400);
  assert.equal(
    await status(post('/v1/push', JSON.stringify({ ...push, expiresInSeconds: 9999 }))),
    400,
  );
  assert.equal(
    await status(post('/v1/push', JSON.stringify({ ...push, intent: 'free-text' }))),
    400,
  );
  assert.equal(
    await status(post('/v1/push', JSON.stringify(push)), { RELAY_AUTH_TOKEN: secret }),
    503,
  );
});

test('APNs relay accepts a stored server token and refreshes it once a day', async () => {
  const { token, key, kv } = storedToken();
  const env = { RELAY_KV: kv, APNS_BUNDLE_ID: '' };
  // An unconfigured topic answers 503 only after the token was accepted.
  assert.equal(
    (await apns.fetch(post('/v1/push', JSON.stringify(push), { auth: token }), env)).status,
    503,
  );
  assert.notEqual(JSON.parse(kv.store.get(key)).lastUsed, '2000-01-01');
  const blocked = storedToken({ blocked: true });
  const refused = await apns.fetch(
    post('/v1/push', JSON.stringify(push), { auth: blocked.token }),
    { RELAY_KV: blocked.kv, APNS_BUNDLE_ID: 'com.example.family' },
  );
  assert.equal(refused.status, 401);
});

const fcmEnv = { RELAY_AUTH_TOKEN: secret, FCM_SERVICE_ACCOUNT_JSON: '{}' };
const fcmPush = JSON.stringify({ deviceToken: 'x'.repeat(160), expiresInSeconds: 60 });

test('FCM relay refuses wrong methods, strangers, missing setup and malformed pushes', async () => {
  const status = async (request, env = fcmEnv) => (await fcm.fetch(request, env)).status;
  assert.equal(await status(new Request(url('/v1/push'))), 405);
  assert.equal(await status(post('/v1/push', fcmPush, { auth: 'wrong-secret-12345' })), 401);
  assert.equal(await status(post('/v1/push', fcmPush), { RELAY_AUTH_TOKEN: secret }), 503);
  assert.equal(
    await status(post('/v1/push', fcmPush, { headers: { 'Content-Length': '9000' } })),
    413,
  );
  assert.equal(await status(post('/v1/push', 'y'.repeat(9000))), 413);
  assert.equal(await status(post('/v1/push', '{not json')), 400);
});

test('FCM registration is off without KV and refused for blocked addresses', async () => {
  const register = (ip) =>
    new Request(url('/v1/register'), { method: 'POST', headers: { 'CF-Connecting-IP': ip } });
  assert.equal((await fcm.fetch(register('203.0.113.9'), {})).status, 404);
  const kv = fakeKV({ 'blocked-ip:203.0.113.9': '1' });
  assert.equal((await fcm.fetch(register('203.0.113.9'), { RELAY_KV: kv })).status, 403);
});

test('FCM relay accepts a stored server token and refreshes it once a day', async () => {
  const { token, key, kv } = storedToken();
  const reply = await fcm.fetch(post('/v1/push', fcmPush, { auth: token }), { RELAY_KV: kv });
  // Accepted, then stopped because FCM itself isn't configured on this relay.
  assert.equal(reply.status, 503);
  assert.notEqual(JSON.parse(kv.store.get(key)).lastUsed, '2000-01-01');
});
