import assert from 'node:assert/strict';
import test from 'node:test';
import { webcrypto } from 'node:crypto';
import worker from '../fcm-relay-worker.mjs';

if (!globalThis.crypto) globalThis.crypto = webcrypto;
const pair = await crypto.subtle.generateKey(
  {
    name: 'RSASSA-PKCS1-v1_5',
    modulusLength: 2048,
    publicExponent: new Uint8Array([1, 0, 1]),
    hash: 'SHA-256',
  },
  true,
  ['sign', 'verify'],
);

const pkcs8 = Buffer.from(await crypto.subtle.exportKey('pkcs8', pair.privateKey)).toString(
  'base64',
);

const secret = 'synthetic-android-relay-secret-1234';

const env = {
  RELAY_AUTH_TOKEN: secret,
  FCM_SERVICE_ACCOUNT_JSON: JSON.stringify({
    type: 'service_account',
    project_id: 'synthetic-project',
    client_email: 'relay@synthetic-project.iam.gserviceaccount.com',
    private_key: `-----BEGIN PRIVATE KEY-----\n${pkcs8}\n-----END PRIVATE KEY-----\n`,
    token_uri: 'https://oauth2.googleapis.com/token',
  }),
};

const token = 'synthetic-registration:' + 'X'.repeat(140);

const request = (payload, auth = secret) =>
  new Request('https://relay.example.invalid/v1/push', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + auth },
    body: JSON.stringify(payload),
  });

function fakeGoogle(send = () => new Response('{}', { status: 200 })) {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    if (String(url) === 'https://oauth2.googleapis.com/token') {
      const assertion = new URLSearchParams(options.body).get('assertion').split('.');
      const ok = await crypto.subtle.verify(
        'RSASSA-PKCS1-v1_5',
        pair.publicKey,
        Buffer.from(assertion[2], 'base64url'),
        new TextEncoder().encode(assertion[0] + '.' + assertion[1]),
      );
      assert.ok(ok, 'OAuth assertion is signed by the service account key');
      return new Response(JSON.stringify({ access_token: 'synthetic-oauth', expires_in: 3600 }), {
        status: 200,
      });
    }
    return send(url, options);
  };
  return calls;
}

test('FCM Worker sends only fixed messages; alerts are data-only and high priority', async () => {
  const original = globalThis.fetch;
  const calls = fakeGoogle();
  try {
    assert.equal(
      (
        await worker.fetch(
          request({ deviceToken: token, expiresInSeconds: 60 }, 'wrong-secret-value-123'),
          env,
        )
      ).status,
      401,
    );
    assert.equal(calls.length, 0);
    assert.equal(
      (
        await worker.fetch(
          request({ deviceToken: token, expiresInSeconds: 60, intent: 'custom' }),
          env,
        )
      ).status,
      400,
    );
    assert.equal(
      (await worker.fetch(request({ deviceToken: 'bad token', expiresInSeconds: 60 }), env)).status,
      400,
    );

    const alert = await worker.fetch(
      request({
        deviceToken: token,
        expiresInSeconds: 3600,
        intent: 'alert',
        title: 'Android left Home',
      }),
      env,
    );
    assert.equal(alert.status, 200);
    assert.deepEqual(await alert.json(), { ok: true, acceptedByFcm: true, fcmStatus: 200 });
    assert.equal(calls[0].url, 'https://oauth2.googleapis.com/token');
    const send = calls.at(-1);
    assert.equal(
      send.url,
      'https://fcm.googleapis.com/v1/projects/synthetic-project/messages:send',
    );
    assert.equal(send.options.headers.Authorization, 'Bearer synthetic-oauth');
    assert.equal(send.options.redirect, 'manual');
    const message = JSON.parse(send.options.body).message;
    assert.deepEqual(message, {
      data: { intent: 'alert' },
      android: { priority: 'HIGH', ttl: '900s' },
      token,
    });
    assert.ok(!send.options.body.includes('Android left Home'));

    const update = await worker.fetch(request({ deviceToken: token, expiresInSeconds: 120 }), env);
    assert.equal(update.status, 200);
    const generic = JSON.parse(calls.at(-1).options.body).message;
    assert.equal(generic.notification.body, 'A household update is available.');
    // The generic notification is unchanged from the deployed Worker.
    assert.deepEqual(generic.android, { priority: 'HIGH', ttl: '120s' });
    assert.equal(calls.filter((c) => c.url.includes('oauth2')).length, 1, 'OAuth token is reused');
  } finally {
    globalThis.fetch = original;
  }
});

test('FCM Worker reports unregistered tokens and hides credentials on failure', async () => {
  const original = globalThis.fetch;
  fakeGoogle(
    () =>
      new Response(
        JSON.stringify({
          error: {
            status: 'NOT_FOUND',
            details: [
              {
                '@type': 'type.googleapis.com/google.firebase.fcm.v1.FcmError',
                errorCode: 'UNREGISTERED',
              },
            ],
          },
        }),
        { status: 404 },
      ),
  );
  try {
    const gone = await worker.fetch(
      request({ deviceToken: token, expiresInSeconds: 60, intent: 'alert' }),
      env,
    );
    assert.equal(gone.status, 502);
    assert.deepEqual(await gone.json(), {
      ok: false,
      acceptedByFcm: false,
      stage: 'parse_fcm_response',
      fcmStatus: 404,
      reason: 'UNREGISTERED',
    });
    const broken = await worker.fetch(request({ deviceToken: token, expiresInSeconds: 60 }), {
      ...env,
      FCM_SERVICE_ACCOUNT_JSON: '{"project_id":"x"}',
    });
    const failure = await broken.json();
    assert.equal(broken.status, 502);
    assert.equal(failure.stage, 'read_firebase_credentials');
    assert.equal(failure.reason, 'Invalid Firebase credentials');
    assert.ok(!JSON.stringify(failure).includes('PRIVATE'));
    const health = await worker.fetch(new Request('https://relay.example.invalid/health'), env);
    assert.deepEqual(await health.json(), {
      ok: true,
      service: 'narahem-fcm-relay',
      workerRevision: 'fcm-registration-1',
    });
  } finally {
    globalThis.fetch = original;
  }
});

test('FCM Worker accepts any listed per-server token and refuses removed ones', async () => {
  const original = globalThis.fetch;
  fakeGoogle();
  try {
    const alice = 'synthetic-alice-android-token-01';
    const bob = 'synthetic-bob-android-token-0002';
    const payload = { deviceToken: token, expiresInSeconds: 60 };
    const listed = {
      ...env,
      RELAY_AUTH_TOKEN: undefined,
      RELAY_AUTH_TOKENS: `alice:${alice}\nbob:${bob}`,
    };
    assert.equal((await worker.fetch(request(payload, alice), listed)).status, 200);
    assert.equal((await worker.fetch(request(payload, bob), listed)).status, 200);
    assert.equal((await worker.fetch(request(payload, 'alice'), listed)).status, 401);
    assert.equal((await worker.fetch(request(payload, secret), listed)).status, 401);
    const removed = { ...env, RELAY_AUTH_TOKENS: `bob:${bob}` };
    assert.equal((await worker.fetch(request(payload, alice), removed)).status, 401);
    assert.equal((await worker.fetch(request(payload, secret), removed)).status, 200);
  } finally {
    globalThis.fetch = original;
  }
});

test('FCM Worker registers servers automatically and accepts their tokens', async () => {
  const original = globalThis.fetch;
  fakeGoogle();
  try {
    const store = new Map();
    const kv = {
      async get(key, type) {
        const value = store.get(key);
        return value === undefined ? null : type === 'json' ? JSON.parse(value) : value;
      },
      async put(key, value) {
        store.set(key, String(value));
      },
    };
    const auto = { ...env, RELAY_AUTH_TOKEN: undefined, RELAY_KV: kv };
    const payload = { deviceToken: token, expiresInSeconds: 60 };
    const register = () =>
      worker.fetch(
        new Request('https://relay.example.invalid/v1/register', {
          method: 'POST',
          headers: { 'CF-Connecting-IP': '203.0.113.5' },
        }),
        auto,
      );

    const reply = await register();
    assert.equal(reply.status, 201);
    const issued = (await reply.json()).token;
    assert.ok(![...store.entries()].flat().some((item) => item.includes(issued)));
    assert.equal((await worker.fetch(request(payload, issued), auto)).status, 200);
    assert.equal((await worker.fetch(request(payload, 'y'.repeat(43)), auto)).status, 401);
    for (let i = 0; i < 4; i++) assert.equal((await register()).status, 201);
    assert.equal((await register()).status, 429);
  } finally {
    globalThis.fetch = original;
  }
});
