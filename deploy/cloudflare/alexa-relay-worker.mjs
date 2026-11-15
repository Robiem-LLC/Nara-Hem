/**
 * Nära Hem Alexa relay — deploy as a Cloudflare module Worker.
 *
 * The published Nära Hem Alexa skill has one address and one sign-in, but every household runs
 * its own server. This Worker sits in between: while linking it asks for the household's server
 * address and sends the admin to that server's own sign-in page; after that it passes each
 * Alexa request to that server.
 *
 * It keeps no database. The server's address and the server's own tokens travel inside the
 * tokens Amazon holds, sealed (AES-GCM) with SEAL_KEY, so nobody can make the relay call an
 * address that a household didn't link. Each household server checks the skill ID and the link
 * token itself (and Amazon's signature when there is one), and signs in only its own
 * administrator.
 *
 * Alexa requests arrive one of two ways: straight from Amazon at /skill (signed by Amazon), or
 * from the skill's Amazon-hosted forwarder at /forward (deploy/alexa/forwarder/index.js), which
 * proves itself with FORWARD_SECRET. The forwarder exists because Amazon's skill service may
 * refuse to connect to some HTTPS addresses.
 *
 * Secrets: CLIENT_SECRET (also entered in the skill's account linking), SEAL_KEY (any long
 * random text; changing it unlinks every household) and FORWARD_SECRET (also in the forwarder).
 * Variable: CLIENT_ID (default "nara-hem").
 *
 * Addresses for the skill's settings in the Alexa developer console:
 *   Endpoint: https://<worker>/skill   Web Authorization URI: https://<worker>/link
 *   Access Token URI: https://<worker>/token
 */
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const REVISION = 'alexa-3';
const SERVER_CLIENT_ID = 'nara-hem-relay';
const AMAZON_HOSTS = ['pitangui.amazon.com', 'layla.amazon.com', 'alexa.amazon.co.jp'];
const MAX_BODY = 16384;

/** The relay's addresses. */
const ROUTES = {
  'GET /link': (request, env, url) => linkForm(url, env),
  'POST /link': (request, env) => linkSubmit(request, env),
  'GET /callback': (request, env, url) => callback(url, env),
  'POST /token': (request, env) => token(request, env),
  'POST /skill': (request, env) => skill(request, env),
  'POST /forward': (request, env) => forward(request, env),
};

/** Encodes bytes as base64url without padding. */
function b64url(bytes) {
  let text = '';
  for (const byte of new Uint8Array(bytes)) text += String.fromCharCode(byte);
  return btoa(text).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
}

/** Decodes base64url text to bytes. */
function unb64url(text) {
  const plain = atob(text.replaceAll('-', '+').replaceAll('_', '/'));
  return Uint8Array.from(plain, (c) => c.charCodeAt(0));
}

/** Returns the AES-GCM key derived from SEAL_KEY. */
async function sealKey(env) {
  if (!env.SEAL_KEY || env.SEAL_KEY.length < 32) throw new Error('SEAL_KEY is not set');
  const raw = await crypto.subtle.digest('SHA-256', encoder.encode(env.SEAL_KEY));
  return crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['encrypt', 'decrypt']);
}

/** Encrypts and authenticates value for one purpose (state, code, access or refresh). */
async function seal(env, purpose, value) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const sealed = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: encoder.encode(purpose) },
    await sealKey(env),
    encoder.encode(JSON.stringify(value)),
  );
  return b64url([...iv, ...new Uint8Array(sealed)]);
}

/** Returns the value sealed for this purpose, or null if it was altered, foreign or expired. */
async function open(env, purpose, token) {
  try {
    const bytes = unb64url(String(token || ''));
    const plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: bytes.slice(0, 12), additionalData: encoder.encode(purpose) },
      await sealKey(env),
      bytes.slice(12),
    );
    const value = JSON.parse(decoder.decode(plain));
    return value.e && value.e < Date.now() / 1000 ? null : value;
  } catch {
    return null;
  }
}

/** Compares two strings in constant time. */
function same(a, b) {
  const x = encoder.encode(String(a));
  const y = encoder.encode(String(b));
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] || 0) ^ (y[i] || 0);
  return diff === 0;
}

/** Returns true for Amazon's account-linking return address. */
function amazonReturn(uri) {
  try {
    const url = new URL(uri);
    return (
      url.protocol === 'https:' &&
      AMAZON_HOSTS.includes(url.hostname) &&
      !url.port &&
      url.pathname.startsWith('/api/skill/link/')
    );
  } catch {
    return false;
  }
}

/** Returns a household server's origin from what the admin typed, or null. */
function serverOrigin(input) {
  const text = String(input || '').trim();
  try {
    const url = new URL(/^https?:\/\//i.test(text) ? text : 'https://' + text);
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
      return null;
    }
    if (!publicName(url.hostname)) return null;
    return url.pathname === '/' ? url.origin : null;
  } catch {
    return null;
  }
}

/**
 * Returns true for a public DNS name. IP addresses (however they're written: the URL parser turns
 * "2130706433" into "127.0.0.1"), single words and names that only work inside a network are
 * refused, so the relay never calls into a private network on someone's say-so.
 */
function publicName(host) {
  return (
    host.includes('.') &&
    !host.startsWith('[') &&
    !/^[\d.]+$/.test(host) &&
    !/(^|\.)(localhost|local|internal|intranet|lan|home\.arpa)\.?$/i.test(host)
  );
}

/** Escapes text for HTML. */
function escape(text) {
  return String(text).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
}

/** Returns the page that asks for the household's server address. */
function page(fields, error = '', status = 200) {
  const hidden = ['client_id', 'redirect_uri', 'state']
    .map((k) => `<input type="hidden" name="${k}" value="${escape(fields[k] || '')}">`)
    .join('');
  const problem = error ? `<p class="error">${escape(error)}</p>` : '';
  const form = fields.redirect_uri
    ? `<form method="post" action="/link">${hidden}` +
      '<label for="server">Your Nära Hem server address</label>' +
      `<input id="server" name="server" type="url" inputmode="url" value="${escape(fields.server || '')}"` +
      ' placeholder="https://nara-hem.example.com" autocomplete="url" required>' +
      '<button type="submit">Continue</button></form>'
    : '';
  const body =
    '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' +
    '<title>Link Nära Hem to Alexa</title><style>' +
    'body{font:16px system-ui,sans-serif;background:#0a1c52;color:#fff;margin:0;padding:24px}' +
    'main{max-width:380px;margin:auto}label{display:block;margin:16px 0 6px}' +
    'input{width:100%;box-sizing:border-box;padding:12px;border-radius:8px;border:0;font-size:16px}' +
    'button{margin-top:22px;width:100%;padding:13px;border:0;border-radius:8px;' +
    'background:#f5b335;font-size:16px;font-weight:600}' +
    '.error{background:#7f1d1d;padding:10px;border-radius:8px}p{line-height:1.45}' +
    '</style></head><body><main><h1>Link Nära Hem to Alexa</h1>' +
    "<p>Enter the address of your household's Nära Hem server. You'll then sign in on your " +
    "server as the household's administrator.</p>" +
    `${problem}${form}</main></body></html>`;
  return new Response(body, {
    status,
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
      'Referrer-Policy': 'no-referrer',
      // The form goes to the household's own server, which can be any HTTPS address.
      'Content-Security-Policy':
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https:; " +
        "frame-ancestors 'none'; base-uri 'none'",
    },
  });
}

/** Returns a JSON response. */
function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

/** Returns an Alexa response that says text, optionally asking the user to link again. */
function speech(text, link = false) {
  const response = { outputSpeech: { type: 'PlainText', text }, shouldEndSession: true };
  if (link) response.card = { type: 'LinkAccount' };
  return json({ version: '1.0', response });
}

/** Reads a form body, refusing large ones. */
async function form(request) {
  const text = await request.text();
  if (text.length > MAX_BODY) throw new Error('Too large');
  return Object.fromEntries(new URLSearchParams(text));
}

/** Shows the server address page, after checking the request came from the Alexa app. */
function linkForm(url, env) {
  const fields = Object.fromEntries(url.searchParams);
  if (
    fields.client_id !== (env.CLIENT_ID || 'nara-hem') ||
    fields.response_type !== 'code' ||
    !amazonReturn(fields.redirect_uri)
  ) {
    return page({}, 'Start linking from the Nära Hem skill in the Alexa app.', 400);
  }
  return page(fields);
}

/** Checks the household server has Alexa on, then sends the admin to its sign-in page. */
async function linkSubmit(request, env) {
  const fields = await form(request);
  let info;
  if (fields.client_id !== (env.CLIENT_ID || 'nara-hem') || !amazonReturn(fields.redirect_uri)) {
    return page({}, 'Start linking from the Nära Hem skill in the Alexa app.', 400);
  }
  const server = serverOrigin(fields.server);
  if (!server) {
    return page(fields, "Enter your server's HTTPS address, e.g. https://nara-hem.example.com.");
  }
  try {
    const reply = await fetch(server + '/alexa/info', {
      redirect: 'manual',
      signal: AbortSignal.timeout(5000),
    });
    info = reply.ok ? await reply.json() : null;
  } catch {
    return page(fields, "Couldn't reach that server. Check the address and try again.");
  }
  if (!info || info.service !== 'nara-hem' || !info.alexa) {
    return page(
      fields,
      "That server doesn't have Alexa turned on. Its administrator sets NARAHEM_ALLOW_ALEXA=true.",
    );
  }
  if (!info.store) {
    return page(fields, 'That server needs a newer Nära Hem version to use this skill.');
  }
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
  const challenge = b64url(await crypto.subtle.digest('SHA-256', encoder.encode(verifier)));
  const relay = new URL(request.url).origin;
  const state = await seal(env, 'state', {
    s: server,
    r: fields.redirect_uri,
    t: fields.state || '',
    v: verifier,
    e: Math.floor(Date.now() / 1000) + 600,
  });
  const query = new URLSearchParams({
    client_id: SERVER_CLIENT_ID,
    response_type: 'code',
    redirect_uri: relay + '/callback',
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  });
  return new Response(null, {
    status: 303,
    headers: { Location: `${server}/alexa/link?${query}`, 'Cache-Control': 'no-store' },
  });
}

/** The household server sends the admin back here; pass a sealed code on to Amazon. */
async function callback(url, env) {
  const state = await open(env, 'state', url.searchParams.get('state'));
  if (!state) return page({}, 'This link has expired. Start again in the Alexa app.', 400);
  const back = new URL(state.r);
  back.searchParams.set('state', state.t);
  const code = url.searchParams.get('code');
  if (code) {
    const sealed = { s: state.s, c: code, v: state.v, e: Math.floor(Date.now() / 1000) + 300 };
    back.searchParams.set('code', await seal(env, 'code', sealed));
  } else {
    back.searchParams.set('error', 'access_denied');
  }
  return new Response(null, {
    status: 302,
    headers: { Location: back.toString(), 'Cache-Control': 'no-store' },
  });
}

/** Returns the client ID and secret Amazon sent, by HTTP Basic or in the form. */
function credentials(request, fields) {
  const header = request.headers.get('authorization') || '';
  if (header.startsWith('Basic ')) {
    try {
      const pair = atob(header.slice(6));
      const split = pair.indexOf(':');
      return [decodeURIComponent(pair.slice(0, split)), decodeURIComponent(pair.slice(split + 1))];
    } catch {
      return ['', ''];
    }
  }
  return [fields.client_id || '', fields.client_secret || ''];
}

/** Amazon swaps a code or refresh token; the relay asks the household server and reseals. */
async function token(request, env) {
  const fields = await form(request);
  const [client, secret] = credentials(request, fields);
  let reply;
  if (
    !env.CLIENT_SECRET ||
    !same(client, env.CLIENT_ID || 'nara-hem') ||
    !same(secret, env.CLIENT_SECRET)
  ) {
    return json({ error: 'invalid_client' }, 401);
  }
  const relay = new URL(request.url).origin;
  let server;
  let ask;
  if (fields.grant_type === 'authorization_code') {
    const code = await open(env, 'code', fields.code);
    if (!code) return json({ error: 'invalid_grant' }, 400);
    server = code.s;
    ask = {
      grant_type: 'authorization_code',
      code: code.c,
      redirect_uri: relay + '/callback',
      client_id: SERVER_CLIENT_ID,
      code_verifier: code.v,
    };
  } else if (fields.grant_type === 'refresh_token') {
    const refresh = await open(env, 'refresh', fields.refresh_token);
    if (!refresh) return json({ error: 'invalid_grant' }, 400);
    server = refresh.s;
    ask = { grant_type: 'refresh_token', refresh_token: refresh.k, client_id: SERVER_CLIENT_ID };
  } else {
    return json({ error: 'unsupported_grant_type' }, 400);
  }
  try {
    reply = await fetch(server + '/alexa/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(ask).toString(),
      redirect: 'manual',
      signal: AbortSignal.timeout(7000),
    });
  } catch {
    return json({ error: 'temporarily_unavailable' }, 503);
  }
  const tokens = reply.ok ? await reply.json().catch(() => null) : null;
  if (!tokens?.access_token || !tokens?.refresh_token) return json({ error: 'invalid_grant' }, 400);
  return json({
    access_token: await seal(env, 'access', { s: server, k: tokens.access_token }),
    refresh_token: await seal(env, 'refresh', { s: server, k: tokens.refresh_token }),
    token_type: 'bearer',
    expires_in: tokens.expires_in || 3600,
  });
}

/** Reads an Alexa request body, or returns the response refusing it. */
async function alexaBody(request) {
  const body = await request.text();
  if (body.length > MAX_BODY) return { refused: json({ error: 'Too large' }, 413) };
  try {
    return { body, alexa: JSON.parse(body) };
  } catch {
    return { refused: json({ error: 'Not JSON' }, 400) };
  }
}

/** Passes an Alexa request on to the household server it was linked to and returns the answer. */
async function passOn(env, body, alexa, signature) {
  const linked = await open(env, 'access', alexa?.context?.System?.user?.accessToken);
  if (!linked) {
    return speech(
      "Please link Nara Hem in the Alexa app, with your household server's address.",
      true,
    );
  }
  const headers = { 'Content-Type': 'application/json', 'X-Narahem-Alexa-Token': linked.k };
  Object.assign(headers, signature);
  try {
    const reply = await fetch(linked.s + '/alexa/skill', {
      method: 'POST',
      headers,
      body,
      redirect: 'manual',
      signal: AbortSignal.timeout(6500),
    });
    if (!reply.ok) return speech("Your Nära Hem server didn't accept that request.");
    return json(await reply.json());
  } catch {
    return speech("I couldn't reach your Nära Hem server.");
  }
}

/** A request straight from Amazon: passed on untouched, with Amazon's signature. */
async function skill(request, env) {
  const { body, alexa, refused } = await alexaBody(request);
  const signature = {};
  if (refused) return refused;
  for (const name of ['SignatureCertChainUrl', 'Signature-256', 'Signature']) {
    const value = request.headers.get(name);
    if (value) signature[name] = value;
  }
  return passOn(env, body, alexa, signature);
}

/** A request from the skill's Amazon-hosted forwarder, which proves itself with FORWARD_SECRET. */
async function forward(request, env) {
  const given = (request.headers.get('authorization') || '').replace(/^Bearer /, '');
  if (!env.FORWARD_SECRET || env.FORWARD_SECRET.length < 32 || !same(given, env.FORWARD_SECRET)) {
    return json({ error: 'Not the Nära Hem forwarder' }, 401);
  }
  const { body, alexa, refused } = await alexaBody(request);
  if (refused) return refused;
  return passOn(env, body, alexa, {});
}

export default {
  /** Routes a request to the relay. */
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (request.method === 'GET' && url.pathname === '/health') {
        return json({ ok: true, workerRevision: REVISION });
      }
      const route = ROUTES[`${request.method} ${url.pathname}`];
      if (route) return await route(request, env, url);
      return json({ error: 'Not found' }, 404);
    } catch (error) {
      return json({ error: error.message === 'Too large' ? 'Too large' : 'Relay error' }, 500);
    }
  },
};
