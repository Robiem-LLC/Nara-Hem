import assert from 'node:assert/strict';
import test from 'node:test';
import { webcrypto } from 'node:crypto';
import worker from '../apns-relay-worker.mjs';

if (!globalThis.crypto) globalThis.crypto = webcrypto;
const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, [
  'sign',
  'verify',
]);

const key = new Uint8Array(await crypto.subtle.exportKey('pkcs8', pair.privateKey));
const base64 = (bytes) => Buffer.from(bytes).toString('base64');
const secret = 'synthetic-server-only-secret-1234';

const env = {
  RELAY_AUTH_TOKEN: secret,
  APNS_TEAM_ID: 'TESTTEAM12',
  APNS_BUNDLE_ID: 'com.example.family',
  APNS_KEY_ID: 'ABCDEFGHIJ',
  APNS_PRIVATE_KEY: `-----BEGIN PRIVATE KEY-----\n${base64(key)}\n-----END PRIVATE KEY-----`,
  APNS_PROD_KEY_ID: 'KLMNOPQRST',
  APNS_PROD_PRIVATE_KEY: `-----BEGIN PRIVATE KEY-----\n${base64(key)}\n-----END PRIVATE KEY-----`,
};

const valid = { deviceToken: 'a'.repeat(64), environment: 'production', expiresInSeconds: 1800 };

const request = (payload, auth = secret) =>
  new Request('https://relay.example.invalid/v1/push', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + auth },
    body: JSON.stringify(payload),
  });

test('Cloudflare APNs Worker supports only fixed intent with time-sensitive ringtone', async () => {
  let call;
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    call = { url, options };
    return new Response(null, { status: 200 });
  };
  try {
    const unauthorized = await worker.fetch(request(valid, 'wrong-password'), env);
    assert.equal(unauthorized.status, 401);
    assert.equal(call, undefined);

    const regular = await worker.fetch(
      request({ ...valid, title: 'Forged emergency', sound: 'fake.wav' }),
      env,
    );
    assert.equal(regular.status, 200);
    let aps = JSON.parse(call.options.body).aps;
    assert.equal(aps.sound, 'default');
    assert.equal(aps.alert.title, 'Nära Hem');
    assert.equal(aps['interruption-level'], undefined);
    assert.equal(call.options.redirect, 'manual');
    assert.ok(call.options.headers.authorization.startsWith('bearer '));
    assert.equal(call.options.headers['apns-topic'], 'com.example.family');
    assert.match(call.url, /api\.push\.apple\.com/);

    const found = await worker.fetch(
      request({ ...valid, intent: 'find-phone', latitude: 40.1 }),
      env,
    );
    assert.equal(found.status, 200);
    aps = JSON.parse(call.options.body).aps;
    assert.equal(aps.sound, 'narahem-find-phone-v1.wav');
    assert.equal(aps['interruption-level'], 'time-sensitive');
    assert.equal(aps.category, 'narahem-find-phone');
    assert.ok(!call.options.body.includes('latitude'));
    assert.ok(!call.options.body.includes('critical'));
    assert.ok(
      Number(call.options.headers['apns-expiration']) - Math.floor(Date.now() / 1000) <= 120,
    );

    const alerted = await worker.fetch(
      request({ ...valid, intent: 'alert', body: 'Android left Home' }),
      env,
    );
    assert.equal(alerted.status, 200);
    aps = JSON.parse(call.options.body).aps;
    assert.equal(aps['mutable-content'], 1);
    assert.equal(aps.alert.body, 'Household alert');
    assert.ok(!call.options.body.includes('Android left Home'));
    assert.ok(
      Number(call.options.headers['apns-expiration']) - Math.floor(Date.now() / 1000) <= 900,
    );

    const badPem = await worker.fetch(request(valid), {
      ...env,
      APNS_PROD_PRIVATE_KEY: 'invalid-pem',
    });
    assert.equal(badPem.status, 502);
    let failure = await badPem.json();
    assert.equal(failure.stage, 'signing_key_decode');
    assert.equal(failure.reason, 'APNs authentication failed');
    assert.ok(!JSON.stringify(failure).includes('invalid-pem'));

    const unconfigured = await worker.fetch(request(valid), {
      ...env,
      APNS_PROD_PRIVATE_KEY: undefined,
    });
    assert.equal(unconfigured.status, 502);
    failure = await unconfigured.json();
    assert.equal(failure.stage, 'signing_configuration');

    globalThis.fetch = async () => {
      throw new TypeError('SECRET: synthetic transport diagnostics must be hidden');
    };
    const unavailable = await worker.fetch(request(valid), env);
    assert.equal(unavailable.status, 502);
    failure = await unavailable.json();
    assert.equal(failure.stage, 'apns_transport');
    assert.equal(failure.errorCode, 'TypeError');
    assert.ok(!JSON.stringify(failure).includes('SECRET:'));

    globalThis.fetch = async () =>
      new Response(JSON.stringify({ reason: 'BadDeviceToken' }), { status: 400 });
    const rejected = await worker.fetch(request(valid), env);
    assert.equal(rejected.status, 502);
    failure = await rejected.json();
    assert.equal(failure.stage, 'apns_response');
    assert.equal(failure.apnsStatus, 400);
    assert.equal(failure.reason, 'BadDeviceToken');

    // Cloudflare's workerd rejects redirect: "error"; ensure a real redirect
    // is never followed with the Apple JWT and token.
    globalThis.fetch = async (url, options) => {
      assert.equal(options.redirect, 'manual');
      return new Response(null, {
        status: 302,
        headers: { Location: 'https://untrusted.invalid/' },
      });
    };
    const redirected = await worker.fetch(request(valid), env);
    assert.equal(redirected.status, 502);
    failure = await redirected.json();
    assert.equal(failure.reason, 'UnexpectedRedirect');

    // Cloudflare may surface a manual redirect as an opaque response with
    // status 0 rather than exposing the provider's 3xx status.
    globalThis.fetch = async (_url, options) => {
      assert.equal(options.redirect, 'manual');
      return { type: 'opaqueredirect', status: 0, ok: false };
    };
    const opaqueRedirect = await worker.fetch(request(valid), env);
    assert.equal(opaqueRedirect.status, 502);
    failure = await opaqueRedirect.json();
    assert.equal(failure.reason, 'UnexpectedRedirect');
    assert.equal(failure.acceptedByApns, false);

    globalThis.fetch = async (url, options) => {
      call = { url, options };
      return new Response(null, { status: 200 });
    };
    const invalid = await worker.fetch(request({ ...valid, intent: 'arbitrary' }), env);
    assert.equal(invalid.status, 400);
    const sandbox = await worker.fetch(
      request({ ...valid, environment: 'sandbox', intent: 'find-phone' }),
      env,
    );
    assert.equal(sandbox.status, 200);
    assert.match(call.url, /api\.sandbox\.push\.apple\.com/);
  } finally {
    globalThis.fetch = original;
  }
});

test('diagnose returns fixed, sanitized Apple connectivity results and requires relay auth', async () => {
  const original = globalThis.fetch;
  const calls = [];
  try {
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options });
      return new Response(null, { status: 405 });
    };
    const diagnostic = (auth) =>
      new Request('https://relay.example.invalid/v1/diagnose', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + auth },
      });
    const denied = await worker.fetch(diagnostic('incorrect'), env);
    assert.equal(denied.status, 401);
    assert.equal(calls.length, 0);

    const success = await worker.fetch(diagnostic(secret), env);
    assert.equal(success.status, 200);
    const result = await success.json();
    assert.equal(result.ok, true);
    assert.deepEqual(
      result.probes.map((p) => p.appleHttpStatus),
      [405, 405],
    );
    assert.deepEqual(
      calls.map((p) => p.url),
      ['https://api.push.apple.com/', 'https://api.sandbox.push.apple.com/'],
    );
    assert.ok(calls.every((p) => p.options.method === 'GET'));
    assert.ok(calls.every((p) => p.options.redirect === 'manual'));

    globalThis.fetch = async () => {
      throw new TypeError('sensitive fetch error must not escape');
    };
    const failed = await worker.fetch(diagnostic(secret), env);
    assert.equal(failed.status, 200);
    const failure = await failed.json();
    assert.equal(failure.ok, false);
    assert.deepEqual(
      failure.probes.map((p) => p.errorCode),
      ['TypeError', 'TypeError'],
    );
    assert.ok(!JSON.stringify(failure).includes('sensitive fetch error'));
  } finally {
    globalThis.fetch = original;
  }
});

test('APNs Worker accepts any listed per-server token and refuses removed ones', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(null, { status: 200 });
  try {
    const alice = 'synthetic-alice-server-token-0001';
    const bob = 'synthetic-bob-server-token-00002';
    const listed = {
      ...env,
      RELAY_AUTH_TOKEN: undefined,
      RELAY_AUTH_TOKENS: `# beta testers\nalice:${alice}\n  bob : ${bob}  \nshort:too-short`,
    };
    assert.equal((await worker.fetch(request(valid, alice), listed)).status, 200);
    assert.equal((await worker.fetch(request(valid, bob), listed)).status, 200);
    // Labels, comments and too-short entries are never tokens themselves.
    for (const wrong of ['alice', 'bob', '# beta testers', 'too-short', secret]) {
      assert.equal((await worker.fetch(request(valid, wrong), listed)).status, 401);
    }
    // Deleting a line cuts off that server alone; the original single token keeps working.
    const removed = { ...env, RELAY_AUTH_TOKENS: `bob:${bob}` };
    assert.equal((await worker.fetch(request(valid, alice), removed)).status, 401);
    assert.equal((await worker.fetch(request(valid, bob), removed)).status, 200);
    assert.equal((await worker.fetch(request(valid, secret), removed)).status, 200);
    assert.equal(
      (await worker.fetch(request(valid, alice), { ...env, RELAY_AUTH_TOKEN: undefined })).status,
      401,
    );
  } finally {
    globalThis.fetch = original;
  }
});

function fakeKV() {
  const store = new Map();
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

const registration = (ip = '203.0.113.5') =>
  new Request('https://relay.example.invalid/v1/register', {
    method: 'POST',
    headers: { 'CF-Connecting-IP': ip },
  });

test('APNs Worker registers servers automatically and stores only token hashes', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(null, { status: 200 });
  try {
    const kv = fakeKV();
    const auto = { ...env, RELAY_AUTH_TOKEN: undefined, RELAY_KV: kv };
    assert.equal((await worker.fetch(registration(), { ...env, RELAY_KV: undefined })).status, 404);

    const reply = await worker.fetch(registration(), auto);
    assert.equal(reply.status, 201);
    const { token } = await reply.json();
    assert.match(token, /^[A-Za-z0-9_-]{43}$/);
    for (const [key, value] of kv.store) {
      assert.ok(!key.includes(token) && !value.includes(token), 'KV never holds the token itself');
    }
    assert.equal((await worker.fetch(request(valid, token), auto)).status, 200);
    assert.equal((await worker.fetch(request(valid, 'x'.repeat(43)), auto)).status, 401);
    // The manual tokens keep working alongside registered ones.
    assert.equal(
      (await worker.fetch(request(valid, secret), { ...env, RELAY_KV: kv })).status,
      200,
    );
    assert.equal((await worker.fetch(request(valid, token), { ...env, RELAY_KV: kv })).status, 200);

    // Blocking a registration cuts that server off.
    const [key] = [...kv.store.keys()].filter((name) => name.startsWith('token:'));
    kv.store.set(key, JSON.stringify({ ...JSON.parse(kv.store.get(key)), blocked: true }));
    assert.equal((await worker.fetch(request(valid, token), auto)).status, 401);

    // Five registrations per address per day; other addresses are unaffected.
    for (let i = 0; i < 4; i++) {
      assert.equal((await worker.fetch(registration(), auto)).status, 201);
    }
    assert.equal((await worker.fetch(registration(), auto)).status, 429);
    assert.equal((await worker.fetch(registration('198.51.100.7'), auto)).status, 201);
    kv.store.set('blocked-ip:198.51.100.9', '1');
    assert.equal((await worker.fetch(registration('198.51.100.9'), auto)).status, 403);
  } finally {
    globalThis.fetch = original;
  }
});
