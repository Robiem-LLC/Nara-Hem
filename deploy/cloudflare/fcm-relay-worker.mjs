/*
 * Nära Hem Android FCM Relay
 *
 * - Firebase Cloud Messaging HTTP v1
 * - Google service-account OAuth authentication
 * - Generic notifications, plus a data-only "alert" wake-up
 *   (the Android app decrypts and shows the household alert itself)
 * - No GPS or household data
 * - No persistent storage
 * - Safe diagnostic error reporting
 *
 * Required Cloudflare secrets:
 *   FCM_SERVICE_ACCOUNT_JSON
 *   RELAY_AUTH_TOKENS and/or RELAY_AUTH_TOKEN
 *
 * RELAY_AUTH_TOKENS lists one token per household server, one per line
 * as "label:token" (the label is only for you); delete a line to cut off
 * that server alone. RELAY_AUTH_TOKEN is a single token, still accepted
 * for existing servers.
 *
 * Optional KV namespace binding:
 *   RELAY_KV — servers register themselves at POST /v1/register and
 *   receive their own token; only its SHA-256 is stored.
 */

const encoder = new TextEncoder();
let cachedAccessToken = '';
let accessTokenExpiresAt = 0;

/** How long a registered server token stays valid without use. */
const REGISTRATION_TTL_SECONDS = 90 * 86400;

/** Maximum server registrations per IP per day. */
const REGISTRATIONS_PER_IP_PER_DAY = 5;

/** Returns a JSON response. */
function reply(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    },
  });
}

/** Encodes bytes or a string as unpadded base64url, for JWTs. */
function base64url(value) {
  const bytes = typeof value === 'string' ? encoder.encode(value) : new Uint8Array(value);

  let binary = '';

  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }

  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Returns the key bytes from a PEM private key. */
function pemBytes(pem) {
  const cleaned = pem.replace(/-----BEGIN PRIVATE KEY-----|-----END PRIVATE KEY-----|\s/g, '');

  const raw = atob(cleaned);

  return Uint8Array.from(raw, (character) => character.charCodeAt(0));
}

/**
 * Returns every configured token: RELAY_AUTH_TOKEN plus each "label:token" line of
 * RELAY_AUTH_TOKENS.
 */
function relayTokens(env) {
  const listed = String(env.RELAY_AUTH_TOKENS || '')
    .split(/[\n,]/)
    .map((entry) => entry.trim())
    .filter((entry) => entry && !entry.startsWith('#'))
    .map((entry) => entry.slice(entry.lastIndexOf(':') + 1).trim())
    .filter((token) => token.length >= 20);

  // The original single token keeps its original rule: any non-empty value.
  return env.RELAY_AUTH_TOKEN ? [String(env.RELAY_AUTH_TOKEN), ...listed] : listed;
}

/** Returns today's UTC date as YYYY-MM-DD. */
function today() {
  return new Date().toISOString().slice(0, 10);
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

  // Refresh the expiry at most once a day to stay within KV write limits.
  if (record.lastUsed !== today()) {
    await env.RELAY_KV.put(key, JSON.stringify({ ...record, lastUsed: today() }), {
      expirationTtl: REGISTRATION_TTL_SECONDS,
    });
  }

  return true;
}

/** Issues a new server its own relay token, rate limited per IP. */
async function register(request, env) {
  if (!env.RELAY_KV) {
    return reply(
      {
        ok: false,
        error: 'Registration is not enabled',
      },
      404,
    );
  }

  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';

  if (await env.RELAY_KV.get('blocked-ip:' + ip)) {
    return reply(
      {
        ok: false,
        error: 'Registration refused',
      },
      403,
    );
  }

  const counter = `registrations:${ip}:${today()}`;
  const count = Number(await env.RELAY_KV.get(counter)) || 0;

  if (count >= REGISTRATIONS_PER_IP_PER_DAY) {
    return reply(
      {
        ok: false,
        error: 'Too many registrations today',
      },
      429,
    );
  }

  await env.RELAY_KV.put(counter, String(count + 1), { expirationTtl: 2 * 86400 });

  const token = base64url(crypto.getRandomValues(new Uint8Array(32)));

  await env.RELAY_KV.put(
    'token:' + (await sha256Hex(token)),
    JSON.stringify({ created: today(), lastUsed: today(), ip }),
    { expirationTtl: REGISTRATION_TTL_SECONDS },
  );

  return reply({ ok: true, token }, 201);
}

/** Returns true if the request carries a configured or registered token. */
async function authorized(request, env) {
  const header = request.headers.get('Authorization') || '';
  const tokens = relayTokens(env);

  if (header.length > 512 || !header.startsWith('Bearer ')) return false;

  if (!tokens.length) return registeredToken(env, header.slice(7));

  // Compare fixed-size digests against every token,
  // so timing reveals neither a prefix nor which token matched.
  const [aa, ...expected] = await Promise.all(
    [header.slice(7), ...tokens].map(
      async (value) => new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(value))),
    ),
  );

  let matches = 0;

  for (const bb of expected) {
    let difference = 0;

    for (let i = 0; i < aa.length; i++) {
      difference |= aa[i] ^ bb[i];
    }

    matches |= difference === 0 ? 1 : 0;
  }

  return matches === 1 || registeredToken(env, header.slice(7));
}

/** Parses and validates the Firebase service account. */
function loadCredentials(env) {
  if (!env.FCM_SERVICE_ACCOUNT_JSON) throw new Error('Missing Firebase credentials');

  const credentials = JSON.parse(env.FCM_SERVICE_ACCOUNT_JSON);

  if (
    credentials.type !== 'service_account' ||
    !/^[a-z][a-z0-9-]{4,62}$/.test(credentials.project_id || '') ||
    typeof credentials.client_email !== 'string' ||
    !credentials.client_email.endsWith('.gserviceaccount.com') ||
    typeof credentials.private_key !== 'string' ||
    !credentials.private_key.startsWith('-----BEGIN PRIVATE KEY-----') ||
    credentials.token_uri !== 'https://oauth2.googleapis.com/token'
  ) {
    throw new Error('Invalid Firebase credentials');
  }

  return credentials;
}

/** Returns an OAuth access token for FCM, cached until shortly before it expires. */
async function googleAccessToken(credentials, setStage) {
  if (cachedAccessToken && Date.now() < accessTokenExpiresAt) return cachedAccessToken;

  setStage('decode_private_key');

  const privateKeyBytes = pemBytes(credentials.private_key);

  setStage('import_private_key');

  const signingKey = await crypto.subtle.importKey(
    'pkcs8',
    privateKeyBytes,
    {
      name: 'RSASSA-PKCS1-v1_5',
      hash: 'SHA-256',
    },
    false,
    ['sign'],
  );

  setStage('create_google_jwt');

  const now = Math.floor(Date.now() / 1000);

  const header = base64url(
    JSON.stringify({
      alg: 'RS256',
      typ: 'JWT',
    }),
  );

  const claims = base64url(
    JSON.stringify({
      iss: credentials.client_email,
      scope: 'https://www.googleapis.com/auth/firebase.messaging',
      aud: 'https://oauth2.googleapis.com/token',
      iat: now,
      exp: now + 3500,
    }),
  );

  const unsigned = `${header}.${claims}`;

  setStage('sign_google_jwt');

  const signature = await crypto.subtle.sign(
    'RSASSA-PKCS1-v1_5',
    signingKey,
    encoder.encode(unsigned),
  );

  const assertion = `${unsigned}.${base64url(signature)}`;

  setStage('request_google_oauth');

  const response = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    redirect: 'manual',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      assertion,
    }),
  });

  if (!response.ok) {
    const error = new Error('Google OAuth authentication failed');

    error.httpStatus = response.status;

    throw error;
  }

  setStage('parse_google_oauth');

  const payload = await response.json();

  if (typeof payload.access_token !== 'string' || !payload.access_token) {
    throw new Error('Missing Google OAuth token');
  }

  cachedAccessToken = payload.access_token;

  const expiresIn = Number(payload.expires_in) || 3600;

  accessTokenExpiresAt = Date.now() + Math.max(60, Math.min(expiresIn, 3600) - 120) * 1000;

  return cachedAccessToken;
}

/** Returns Firebase's error code if it is a known one, otherwise a generic reason. */
function safeFcmReason(payload) {
  const allowed = new Set([
    'UNREGISTERED',
    'INVALID_ARGUMENT',
    'SENDER_ID_MISMATCH',
    'QUOTA_EXCEEDED',
    'THIRD_PARTY_AUTH_ERROR',
    'UNAVAILABLE',
    'INTERNAL',
    'PERMISSION_DENIED',
    'UNAUTHENTICATED',
    'NOT_FOUND',
  ]);

  const details = Array.isArray(payload?.error?.details) ? payload.error.details : [];

  const fromDetail = details.find((item) => typeof item?.errorCode === 'string')?.errorCode;

  const reason = fromDetail || payload?.error?.status;

  return allowed.has(reason) ? reason : 'FCM_REJECTED';
}

/** Returns a failure summary containing only known reasons and the stage, never secrets. */
function safeDiagnostic(error, stage) {
  const allowedReasons = new Set([
    'Missing Firebase credentials',
    'Invalid Firebase credentials',
    'Google OAuth authentication failed',
    'Missing Google OAuth token',
  ]);

  const allowedTypes = new Set([
    'TypeError',
    'InvalidCharacterError',
    'DataError',
    'OperationError',
    'NotSupportedError',
    'ReferenceError',
    'SyntaxError',
    'AbortError',
  ]);

  const message = error instanceof Error ? error.message : '';

  const type = error && typeof error.name === 'string' ? error.name : '';

  const diagnostic = {
    ok: false,
    error: 'FCM delivery unavailable',
    stage,
    errorType: allowedTypes.has(type) ? type : 'Other',
    reason: allowedReasons.has(message) ? message : 'Unexpected Worker or network error',
  };

  if (Number.isInteger(error?.httpStatus) && error.httpStatus >= 400 && error.httpStatus <= 599) {
    diagnostic.upstreamStatus = error.httpStatus;
  }

  return diagnostic;
}

/** Validates a push request. Returns {token, ttl, intent}, or {failure} with the error response. */
async function readPushRequest(request, env) {
  const fail = (error, status) => ({ failure: reply({ ok: false, error }, status) });
  let body;
  if (request.method !== 'POST') return fail('Method not allowed', 405);
  if (!(await authorized(request, env))) return fail('Unauthorized', 401);
  if (!env.FCM_SERVICE_ACCOUNT_JSON) return fail('FCM not configured', 503);
  if (Number(request.headers.get('Content-Length') || 0) > 8192) {
    return fail('Payload too large', 413);
  }
  try {
    const buffer = await request.arrayBuffer();
    if (buffer.byteLength > 8192) return fail('Payload too large', 413);
    body = JSON.parse(new TextDecoder().decode(buffer));
  } catch {
    return fail('Invalid JSON', 400);
  }
  if (
    !body ||
    typeof body !== 'object' ||
    Array.isArray(body) ||
    typeof body.deviceToken !== 'string' ||
    !/^[A-Za-z0-9_.:-]{20,4096}$/.test(body.deviceToken)
  ) {
    return fail('Invalid device token', 400);
  }
  const ttl = body.expiresInSeconds === undefined ? 60 : body.expiresInSeconds;
  if (!Number.isInteger(ttl) || ttl < 0 || ttl > 3600) return fail('Invalid expiration', 400);
  const intent = body.intent === undefined ? 'update' : body.intent;
  if (intent !== 'update' && intent !== 'alert') return fail('Invalid message intent', 400);
  return { token: body.deviceToken, ttl, intent };
}

/**
 * Builds the FCM message: a data-only alert wake-up or a fixed generic notification. No other
 * content is ever sent.
 */
function fcmMessage(intent, token, ttl) {
  if (intent === 'alert') {
    return {
      token,
      data: { intent: 'alert' },
      android: { priority: 'HIGH', ttl: `${Math.min(ttl, 900)}s` },
    };
  }
  return {
    token,
    notification: { title: 'Nära Hem', body: 'A household update is available.' },
    android: { priority: 'HIGH', ttl: `${ttl}s` },
  };
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    let stage = 'read_firebase_credentials';
    if (path === '/health' && request.method === 'GET') {
      return reply({
        ok: true,
        service: 'narahem-fcm-relay',
        workerRevision: 'fcm-registration-1',
      });
    }
    if (path === '/v1/register' && request.method === 'POST') return register(request, env);
    if (path !== '/v1/push') return reply({ ok: false, error: 'Not found' }, 404);
    const push = await readPushRequest(request, env);
    if (push.failure) return push.failure;
    try {
      const credentials = loadCredentials(env);
      const accessToken = await googleAccessToken(credentials, (value) => {
        stage = value;
      });
      stage = 'send_fcm_request';
      const response = await fetch(
        `https://fcm.googleapis.com/v1/projects/${credentials.project_id}/messages:send`,
        {
          method: 'POST',
          redirect: 'manual',
          headers: {
            Authorization: `Bearer ${accessToken}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ message: fcmMessage(push.intent, push.token, push.ttl) }),
        },
      );
      let providerError = {};
      if (response.ok) return reply({ ok: true, acceptedByFcm: true, fcmStatus: response.status });
      stage = 'parse_fcm_response';
      try {
        providerError = await response.json();
      } catch {
        // Never return raw provider error data.
      }
      return reply(
        {
          ok: false,
          acceptedByFcm: false,
          stage,
          fcmStatus: response.status,
          reason: safeFcmReason(providerError),
        },
        502,
      );
    } catch (error) {
      return reply(safeDiagnostic(error, stage), 502);
    }
  },
};
