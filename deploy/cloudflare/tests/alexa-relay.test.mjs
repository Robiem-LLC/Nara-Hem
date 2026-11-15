// The Alexa relay: linking a household server, swapping tokens and passing requests on.
import assert from 'node:assert/strict';
import { createHash, webcrypto } from 'node:crypto';
import test from 'node:test';
import relay from '../alexa-relay-worker.mjs';

if (!globalThis.crypto) globalThis.crypto = webcrypto;

const env = {
  CLIENT_SECRET: 'synthetic-client-secret',
  SEAL_KEY: 'k'.repeat(40),
  FORWARD_SECRET: 'f'.repeat(40),
};

const RELAY = 'https://alexa-relay.example.invalid';
const SERVER = 'https://home.example.invalid';
const AMAZON = 'https://pitangui.amazon.com/api/skill/link/M2TEST';
const basic = 'Basic ' + btoa('nara-hem:synthetic-client-secret');

const call = (path, init) => relay.fetch(new Request(RELAY + path, init), env);
const s256 = (text) => createHash('sha256').update(text).digest('base64url');

const formBody = (fields) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams(fields).toString(),
});

/** A household server with Alexa on, recording what the relay asked it. */
function household({ alexa = true } = {}) {
  const seen = { tokens: [], skill: [] };
  let challenge;
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    assert.equal(url.origin, SERVER, 'the relay only calls the linked server');
    if (url.pathname === '/alexa/info') {
      return Response.json(alexa ? { service: 'nara-hem', alexa: true, store: true } : {});
    }
    if (url.pathname === '/alexa/token') {
      const fields = Object.fromEntries(new URLSearchParams(init.body));
      seen.tokens.push(fields);
      if (fields.grant_type === 'authorization_code') {
        if (fields.code !== 'server-code' || s256(fields.code_verifier) !== challenge) {
          return Response.json({ error: 'invalid_grant' }, { status: 400 });
        }
      }
      return Response.json({
        access_token: 'server-access-' + seen.tokens.length,
        refresh_token: 'server-refresh-' + seen.tokens.length,
        expires_in: 3600,
      });
    }
    if (url.pathname === '/alexa/skill') {
      seen.skill.push({ headers: Object.fromEntries(new Headers(init.headers)), body: init.body });
      return Response.json({ version: '1.0', response: { outputSpeech: { text: 'Hi' } } });
    }
    return new Response('', { status: 404 });
  };
  return { seen, setChallenge: (value) => (challenge = value) };
}

/** Links Alexa as Amazon and the admin would, returning Amazon's tokens. */
async function link(server) {
  const start = new URLSearchParams({
    client_id: 'nara-hem',
    response_type: 'code',
    redirect_uri: AMAZON,
    state: 'amazon-state',
  });
  const page = await call('/link?' + start);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /Nära Hem server address/);
  const sent = await call(
    '/link',
    formBody({
      client_id: 'nara-hem',
      redirect_uri: AMAZON,
      state: 'amazon-state',
      server: 'home.example.invalid',
    }),
  );
  assert.equal(sent.status, 303);
  const signIn = new URL(sent.headers.get('location'));
  assert.equal(signIn.origin + signIn.pathname, SERVER + '/alexa/link');
  assert.equal(signIn.searchParams.get('client_id'), 'nara-hem-relay');
  assert.equal(signIn.searchParams.get('redirect_uri'), RELAY + '/callback');
  assert.equal(signIn.searchParams.get('code_challenge_method'), 'S256');
  server.setChallenge(signIn.searchParams.get('code_challenge'));
  const back = await call(
    '/callback?' +
      new URLSearchParams({ code: 'server-code', state: signIn.searchParams.get('state') }),
  );
  assert.equal(back.status, 302);
  const amazon = new URL(back.headers.get('location'));
  assert.equal(amazon.origin + amazon.pathname, AMAZON);
  assert.equal(amazon.searchParams.get('state'), 'amazon-state');
  const code = amazon.searchParams.get('code');
  assert.ok(!code.includes('server-code'), 'the server code is sealed');
  const swapped = await call('/token', {
    ...formBody({ grant_type: 'authorization_code', code, redirect_uri: AMAZON }),
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Authorization: basic },
  });
  assert.equal(swapped.status, 200);
  return { tokens: await swapped.json(), code };
}

const skillRequest = (token) => ({
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    SignatureCertChainUrl: 'https://s3.amazonaws.com/echo.api/echo-api-cert.pem',
    'Signature-256': 'c2lnbmF0dXJl',
  },
  body: JSON.stringify({ context: { System: { user: { accessToken: token } } }, request: {} }),
});

test('Alexa relay links a household server and passes requests to it', async () => {
  const server = household();
  const { tokens, code } = await link(server);
  assert.ok(!tokens.access_token.includes('server-access'), 'Amazon only sees sealed tokens');
  const asked = await call('/skill', skillRequest(tokens.access_token));
  assert.equal((await asked.json()).response.outputSpeech.text, 'Hi');
  const forwarded = server.seen.skill[0];
  assert.equal(forwarded.headers['x-narahem-alexa-token'], 'server-access-1');
  assert.equal(forwarded.headers['signature-256'], 'c2lnbmF0dXJl', 'Amazon signature kept');
  assert.equal(JSON.parse(forwarded.body).context.System.user.accessToken, tokens.access_token);

  const refreshed = await call('/token', {
    ...formBody({ grant_type: 'refresh_token', refresh_token: tokens.refresh_token }),
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Authorization: basic },
  });
  assert.equal(refreshed.status, 200);
  assert.equal(server.seen.tokens.at(-1).refresh_token, 'server-refresh-1');
  const again = await call('/token', {
    ...formBody({ grant_type: 'authorization_code', code: tokens.access_token }),
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Authorization: basic },
  });
  assert.equal(again.status, 400, 'an access token is not a code');
  assert.ok(code);
});

test('Alexa relay never calls IP addresses or private network names', async () => {
  globalThis.fetch = async (input) => {
    throw new Error('the relay called ' + input);
  };
  const addresses = [
    '127.0.0.1',
    'https://2130706433/',
    'https://0x7f.1/',
    '10.0.0.5:8186',
    '192.168.1.20',
    '169.254.169.254',
    '[::1]',
    'https://[fd00::1]/',
    'localhost',
    'nas.local',
    'server.internal',
    'home.lan',
    'printer.home.arpa',
    'nas',
  ];
  for (const server of addresses) {
    const reply = await call(
      '/link',
      formBody({ client_id: 'nara-hem', redirect_uri: AMAZON, state: 's', server }),
    );
    assert.equal(reply.status, 200, server);
    assert.match(await reply.text(), /Enter your server/, server);
  }
});

test('Alexa relay refuses strangers, altered tokens and servers without Alexa', async () => {
  const server = household({ alexa: false });
  const bad = new URLSearchParams({
    client_id: 'nara-hem',
    response_type: 'code',
    redirect_uri: 'https://evil.example/api/skill/link/x',
  });
  assert.equal((await call('/link?' + bad)).status, 400);
  const off = await call(
    '/link',
    formBody({ client_id: 'nara-hem', redirect_uri: AMAZON, state: 's', server: SERVER }),
  );
  assert.match(await off.text(), /doesn&#39;t have Alexa turned on/);
  const http = await call(
    '/link',
    formBody({
      client_id: 'nara-hem',
      redirect_uri: AMAZON,
      state: 's',
      server: 'http://x.example',
    }),
  );
  assert.match(await http.text(), /HTTPS address/);
  const wrong = await call('/token', {
    ...formBody({ grant_type: 'refresh_token', refresh_token: 'x' }),
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      Authorization: 'Basic ' + btoa('nara-hem:wrong'),
    },
  });
  assert.equal(wrong.status, 401);
  const unlinked = await (await call('/skill', skillRequest('not-a-sealed-token'))).json();
  assert.equal(unlinked.response.card.type, 'LinkAccount');
  assert.equal(server.seen.skill.length, 0, 'nothing reaches a server without a sealed token');
  assert.equal((await call('/callback?state=forged&code=x')).status, 400);
  const health = await (await call('/health')).json();
  assert.equal(health.workerRevision, 'alexa-3');
});

test('Alexa relay takes requests from the Amazon-hosted forwarder with its secret', async () => {
  const server = household();
  const { tokens } = await link(server);
  const request = (secret) => ({
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + secret },
    body: JSON.stringify({
      context: { System: { user: { accessToken: tokens.access_token } } },
      request: { type: 'LaunchRequest' },
    }),
  });
  assert.equal((await call('/forward', request('wrong'))).status, 401);
  assert.equal(server.seen.skill.length, 0);
  const answered = await call('/forward', request(env.FORWARD_SECRET));
  assert.equal((await answered.json()).response.outputSpeech.text, 'Hi');
  const passed = server.seen.skill[0];
  assert.equal(passed.headers['x-narahem-alexa-token'], 'server-access-1');
  assert.equal(passed.headers['signature-256'], undefined, 'nothing pretends to be signed');
  const off = await relay.fetch(new Request(RELAY + '/forward', request(env.FORWARD_SECRET)), {
    ...env,
    FORWARD_SECRET: '',
  });
  assert.equal(off.status, 401, 'no forwarder secret, no forwarding');
});
