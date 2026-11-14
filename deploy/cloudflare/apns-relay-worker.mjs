/**
 * Nära Hem APNs relay — deploy as a Cloudflare module Worker.
 *
 * Secrets (existing worker):
 *  RELAY_AUTH_TOKENS and/or RELAY_AUTH_TOKEN, APNS_PRIVATE_KEY, APNS_KEY_ID,
 *  APNS_PROD_PRIVATE_KEY, APNS_PROD_KEY_ID, APNS_TEAM_ID
 * Variable: APNS_BUNDLE_ID.
 *
 * Only a household server holding one of the relay tokens may submit messages.
 * With a KV namespace bound as RELAY_KV, servers register themselves at
 * POST /v1/register and receive their own token; only its SHA-256 is stored.
 * RELAY_AUTH_TOKENS lists one token per server, one per line as "label:token"
 * (the label is only for you); delete a line to cut off that server alone.
 * RELAY_AUTH_TOKEN is a single token, still accepted for existing servers.
 * A fixed "find-phone" intent selects the built-in app ringtone. A fixed "alert"
 * intent lets the app's notification service extension decrypt a household alert
 * on the phone and replace the placeholder text before it is shown. This Worker
 * never accepts arbitrary caller-supplied alert text, priority or sound.
 * It has no phone owner's location, household identity, or signed command.
 */
const encoder = new TextEncoder();

const fixedNotifications = Object.freeze({
  update: {
    alert: { title: 'Nära Hem', body: 'A household update is available.' },
    sound: 'default',
  },
  // Placeholder only: the iPhone decrypts the real alert ("Android left Home") itself.
  alert: {
    alert: { title: 'Nära Hem', body: 'Household alert' },
    sound: 'default',
    'mutable-content': 1,
  },
  'find-phone': {
    alert: {
      title: 'Find My Phone',
      body: 'An approved household administrator requested a phone-finding alert.',
    },
    sound: 'narahem-find-phone-v1.wav',
    'interruption-level': 'time-sensitive',
    category: 'narahem-find-phone',
  },
});

/** How long a registered server token stays valid without use. */
const REGISTRATION_TTL_SECONDS = 90 * 86400;

/** Maximum server registrations per IP per day. */
const REGISTRATIONS_PER_IP_PER_DAY = 5;

/** Returns today's UTC date as YYYY-MM-DD. */
const today = () => new Date().toISOString().slice(0, 10);

/** Returns a JSON response. */
function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}

/** Encodes bytes as unpadded base64url, for JWTs. */
function base64url(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/**
 * Returns every configured token: RELAY_AUTH_TOKEN plus each "label:token" line of
 * RELAY_AUTH_TOKENS.
 */
function relayTokens(env) {
  const entries = [env.RELAY_AUTH_TOKEN, ...String(env.RELAY_AUTH_TOKENS || '').split(/[\n,]/)];
  return entries
    .map((entry) => String(entry || '').trim())
    .filter((entry) => entry && !entry.startsWith('#'))
    .map((entry) => entry.slice(entry.lastIndexOf(':') + 1).trim())
    .filter((token) => token.length >= 20);
}

/** Returns the SHA-256 of a string as hex. */
async function sha256Hex(value) {
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(value)));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** Returns true if the token was registered and hasn't expired, extending its lifetime. */
async function registeredToken(env, token) {
  if (!env.RELAY_KV || !/^[A-Za-z0-9_-]{43}$/.test(token)) return false;
  const key = 'token:' + (await sha256Hex(token));
  const record = await env.RELAY_KV.get(key, 'json');
  if (!record || record.blocked) return false;
  // Refresh the expiry at most once a day to stay well inside KV write limits.
  if (record.lastUsed !== today()) {
    await env.RELAY_KV.put(key, JSON.stringify({ ...record, lastUsed: today() }), {
      expirationTtl: REGISTRATION_TTL_SECONDS,
    });
  }
  return true;
}

/** Issues a new server its own relay token, rate limited per IP. */
async function register(request, env) {
  if (!env.RELAY_KV) return json({ error: 'Registration is not enabled' }, 404);
  const ip = request.headers.get('cf-connecting-ip') || 'unknown';
  if (await env.RELAY_KV.get('blocked-ip:' + ip)) {
    return json({ error: 'Registration refused' }, 403);
  }
  const counter = `registrations:${ip}:${today()}`;
  const count = Number(await env.RELAY_KV.get(counter)) || 0;
  if (count >= REGISTRATIONS_PER_IP_PER_DAY) {
    return json({ error: 'Too many registrations today' }, 429);
  }
  await env.RELAY_KV.put(counter, String(count + 1), { expirationTtl: 2 * 86400 });
  const token = base64url(crypto.getRandomValues(new Uint8Array(32)));
  await env.RELAY_KV.put(
    'token:' + (await sha256Hex(token)),
    JSON.stringify({ created: today(), lastUsed: today(), ip }),
    { expirationTtl: REGISTRATION_TTL_SECONDS },
  );
  return json({ token }, 201);
}

/** Returns true if the request carries a configured or registered token. */
async function authorized(request, env) {
  const tokens = relayTokens(env);
  const actual = request.headers.get('authorization') || '';
  if (actual.length > 512 || !actual.startsWith('Bearer ')) return false;
  if (!tokens.length) return registeredToken(env, actual.slice(7));
  // Fixed-size digest comparison against every token prevents a leaked prefix or token count.
  const [supplied, ...expected] = await Promise.all(
    [actual.slice(7), ...tokens].map(
      async (value) => new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(value))),
    ),
  );
  let matches = 0;
  for (const candidate of expected) {
    let difference = 0;
    for (let i = 0; i < supplied.length; i++) difference |= supplied[i] ^ candidate[i];
    matches |= difference === 0 ? 1 : 0;
  }
  return matches === 1 || registeredToken(env, actual.slice(7));
}

/** Returns a fixed error identifier, never a message that could contain secrets. */
function safeErrorName(error) {
  const name = String(error?.name || '');
  return [
    'TypeError',
    'DataError',
    'NotSupportedError',
    'OperationError',
    'InvalidAccessError',
    'SyntaxError',
    'Error',
    'NetworkError',
  ].includes(name)
    ? name
    : 'UnknownError';
}

/** Returns a signed APNs provider token, cached while valid. */
async function authorizationHeader(env, production) {
  let stage = 'signing_configuration';
  try {
    const keyId = production ? env.APNS_PROD_KEY_ID : env.APNS_KEY_ID;
    const pem = production ? env.APNS_PROD_PRIVATE_KEY : env.APNS_PRIVATE_KEY;
    if (!keyId || !pem || !env.APNS_TEAM_ID) throw new Error('Missing signing configuration');
    if (!/^[A-Z0-9]{10}$/.test(keyId) || !/^[A-Z0-9]{10}$/.test(env.APNS_TEAM_ID)) {
      throw new Error('Invalid signing configuration');
    }
    stage = 'signing_key_decode';
    const encoded = pem
      .replace(/\\n/g, '\n')
      .replace(/-----BEGIN PRIVATE KEY-----|-----END PRIVATE KEY-----|\s/g, '');
    const der = Uint8Array.from(atob(encoded), (value) => value.charCodeAt(0));
    stage = 'signing_key_import';
    const key = await crypto.subtle.importKey(
      'pkcs8',
      der,
      { name: 'ECDSA', namedCurve: 'P-256' },
      false,
      ['sign'],
    );
    stage = 'signing_jwt';
    const jwtHeader = base64url(
      encoder.encode(JSON.stringify({ alg: 'ES256', kid: keyId, typ: 'JWT' })),
    );
    const jwtClaims = base64url(
      encoder.encode(
        JSON.stringify({
          iss: env.APNS_TEAM_ID,
          iat: Math.floor(Date.now() / 1000),
        }),
      ),
    );
    const signedInput = jwtHeader + '.' + jwtClaims;
    const signature = new Uint8Array(
      await crypto.subtle.sign(
        { name: 'ECDSA', hash: 'SHA-256' },
        key,
        encoder.encode(signedInput),
      ),
    );
    if (signature.length !== 64) throw new Error('Unexpected ECDSA signature format');
    return 'bearer ' + signedInput + '.' + base64url(signature);
  } catch (error) {
    const failure = new Error('APNs signing failed');
    failure.stage = stage;
    failure.safeCode = safeErrorName(error);
    throw failure;
  }
}

/**
 * Checks that Apple's fixed APNs hosts are reachable over HTTP/2. Callers can't choose hosts or
 * send tokens.
 */
async function probeApnsConnectivity() {
  const probes = [];
  for (const [environment, host] of [
    ['production', 'api.push.apple.com'],
    ['sandbox', 'api.sandbox.push.apple.com'],
  ]) {
    try {
      const response = await fetch(`https://${host}/`, { method: 'GET', redirect: 'manual' });
      if (response.type === 'opaqueredirect' || (response.status >= 300 && response.status < 400)) {
        probes.push({
          environment,
          result: 'unexpected_redirect',
          appleHttpStatus: response.status,
        });
      } else {
        probes.push({ environment, result: 'http_response', appleHttpStatus: response.status });
      }
      await response.body?.cancel().catch(() => {});
    } catch (error) {
      probes.push({ environment, result: 'transport_error', errorCode: safeErrorName(error) });
    }
  }
  return { ok: probes.every((probe) => probe.result === 'http_response'), probes };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    let body;
    let response;
    if (request.method === 'GET' && url.pathname === '/health') {
      return json({ ok: true, workerRevision: 'apns-registration-1' });
    }
    if (request.method === 'POST' && url.pathname === '/v1/register') return register(request, env);
    if (request.method === 'POST' && url.pathname === '/v1/diagnose') {
      if (!(await authorized(request, env))) return json({ error: 'Unauthorized' }, 401);
      return json(await probeApnsConnectivity());
    }
    if (request.method !== 'POST' || url.pathname !== '/v1/push') {
      return json({ error: 'Not found' }, 404);
    }
    if (!(await authorized(request, env))) return json({ error: 'Unauthorized' }, 401);
    if ((request.headers.get('content-type') || '').split(';')[0].trim() !== 'application/json') {
      return json({ error: 'Expected application/json' }, 415);
    }
    const source = await request.text();
    if (source.length > 4096) return json({ error: 'Payload too large' }, 413);
    try {
      body = JSON.parse(source);
    } catch {
      return json({ error: 'Invalid JSON' }, 400);
    }

    if (
      !body ||
      !/^[a-f0-9]{32,512}$/i.test(body.deviceToken || '') ||
      !['production', 'sandbox'].includes(body.environment) ||
      (body.intent !== undefined && !Object.hasOwn(fixedNotifications, body.intent)) ||
      !Number.isInteger(body.expiresInSeconds) ||
      body.expiresInSeconds < 0 ||
      body.expiresInSeconds > 3600
    ) {
      return json({ error: 'Invalid push registration or message intent' }, 400);
    }
    if (!/^[A-Za-z0-9.-]{3,200}$/.test(env.APNS_BUNDLE_ID || '')) {
      return json({ error: 'APNs topic is not configured' }, 503);
    }
    const intent = body.intent || 'update';
    const expiry =
      Math.floor(Date.now() / 1000) +
      Math.min(
        body.expiresInSeconds,
        intent === 'find-phone' ? 120 : intent === 'alert' ? 900 : 3600,
      );
    const host =
      body.environment === 'production' ? 'api.push.apple.com' : 'api.sandbox.push.apple.com';
    let auth;
    try {
      auth = await authorizationHeader(env, body.environment === 'production');
    } catch (error) {
      return json(
        {
          ok: false,
          acceptedByApns: false,
          stage: error.stage || 'signing_unknown',
          errorCode: error.safeCode || 'UnknownError',
          reason: 'APNs authentication failed',
        },
        502,
      );
    }
    try {
      response = await fetch(`https://${host}/3/device/${body.deviceToken}`, {
        method: 'POST',
        redirect: 'manual',
        headers: {
          authorization: auth,
          'apns-topic': env.APNS_BUNDLE_ID,
          'apns-push-type': 'alert',
          'apns-priority': '10',
          'apns-expiration': String(expiry),
          'content-type': 'application/json',
        },
        body: JSON.stringify({ aps: fixedNotifications[intent] }),
      });
    } catch (error) {
      return json(
        {
          ok: false,
          acceptedByApns: false,
          stage: 'apns_transport',
          errorCode: safeErrorName(error),
          reason: 'APNs connection failed',
        },
        502,
      );
    }
    // Never follow a redirect with the provider JWT or device token. workerd doesn't reliably
    // support redirect: "error", so redirects are rejected explicitly.
    if (response.type === 'opaqueredirect' || (response.status >= 300 && response.status < 400)) {
      return json(
        {
          ok: false,
          acceptedByApns: false,
          stage: 'apns_response',
          apnsStatus: response.status,
          reason: 'UnexpectedRedirect',
        },
        502,
      );
    }
    if (!response.ok) {
      let error = {};
      try {
        error = await response.json();
      } catch {
        /* APNs returned no JSON */
      }
      return json(
        {
          ok: false,
          acceptedByApns: false,
          stage: 'apns_response',
          apnsStatus: response.status,
          reason: String(error.reason || 'Rejected').slice(0, 100),
        },
        502,
      );
    }
    return json({ ok: true, acceptedByApns: true });
  },
};
