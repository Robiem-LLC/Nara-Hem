# Nära Hem relays on Cloudflare Workers

Every household runs its own server, but Apple, Google and Amazon each want one fixed service to
talk to. These three small Cloudflare Workers are that service. They pass messages along and
keep nothing about households: no locations, names, addresses or message text ever reach them.

Official server images have the relays' addresses built in at build time (from CI secrets, see
`ci/relay_defaults.py`), so nothing here names them. To run your own, deploy these Workers and
point your server at them with the environment variables below.

| Worker                                             | For                   | Server setting            |
| -------------------------------------------------- | --------------------- | ------------------------- |
| [`apns-relay-worker.mjs`](apns-relay-worker.mjs)   | iPhone push (APNs)    | `NARAHEM_PUSH_RELAY_URL`  |
| [`fcm-relay-worker.mjs`](fcm-relay-worker.mjs)     | Android push (FCM)    | `NARAHEM_FCM_RELAY_URL`   |
| [`alexa-relay-worker.mjs`](alexa-relay-worker.mjs) | The Alexa store skill | `NARAHEM_ALEXA_RELAY_URL` |

Each is a module Worker: **Workers & Pages → Create → Worker**, paste the file, **Deploy**, then
add the secrets below under **Settings → Variables and Secrets**. `GET /health` shows the
deployed `workerRevision`.

## Push relays (iPhone and Android)

The server never sends the push providers anything readable. When something happens (a new
location, a household alert, a ring), it asks the relay to send one of a few fixed kinds of push
to a device token; the phone then fetches and decrypts the real data from its own server.

- `update`: a generic "something changed" notification.
- `alert`: a placeholder the phone replaces with the decrypted household alert ("Sam left
  Home") before it's shown: on iPhone through the notification service extension
  (`mutable-content`), on Android as a data-only message the app shows itself. Expires after 15
  minutes.
- `find-phone`: the app's built-in ringtone as a Time Sensitive notification on iPhone (not a
  Critical Alert, so Silent Mode still applies), a high-priority message on Android. Sent only
  after the server has stored a signed ring command for a phone that allows ringing. Expires
  after two minutes.

The relays accept no free text, sound names or priorities from the caller.

### Who may send

A relay only accepts `POST /v1/push` with a token it knows:

- **Self-registration:** bind a Workers KV namespace as **`RELAY_KV`** and servers register
  themselves with `POST /v1/register`, getting their own token. The relay stores only the
  token's SHA-256, the dates it was issued and last used, and the registering IP. Unused tokens
  expire after 90 days, and each IP may register 5 times a day. To cut off one server, delete
  its `token:…` record or add `"blocked": true`; add `blocked-ip:<address>` to stop an address
  registering.
- **Tokens issued by hand:** the secret `RELAY_AUTH_TOKENS`, one `label:token` per line (lines
  starting with `#` are ignored, tokens under 20 characters refused), or a single
  `RELAY_AUTH_TOKEN`. The server sets them as `NARAHEM_PUSH_RELAY_TOKEN` and
  `NARAHEM_FCM_RELAY_TOKEN`.

### iPhone (APNs) settings

- Secrets: `APNS_PRIVATE_KEY` and `APNS_KEY_ID` (development), `APNS_PROD_PRIVATE_KEY` and
  `APNS_PROD_KEY_ID` (production), `APNS_TEAM_ID`.
- Variable: `APNS_BUNDLE_ID`, the iPhone app's bundle identifier.
- The server says whether each iPhone runs a development or production build, and the relay
  picks the matching Apple host. Redirects from Apple are refused, so keys and tokens never go anywhere
  else.
- `POST /v1/diagnose` (with a relay token) checks the Worker can reach Apple, without sending a
  push.

### Android (FCM) settings

- Secret: `FCM_SERVICE_ACCOUNT_JSON`, a Firebase service account allowed to send messages for
  the app's Firebase project. The relay signs in to Google with it and sends through FCM HTTP v1.

## Alexa relay

The Alexa store skill has one address and one sign-in, but each household has its own server.
The relay sits in between:

```text
Echo → Amazon → forwarder (Alexa-hosted, inside Amazon) → this relay → the household's server
```

- **Linking** (`/link`, `/callback`, `/token`): the relay asks for the household's server address
  and sends the administrator to that server's own sign-in page, using the server's sign-in with
  a PKCE check. It keeps no database: the server's address and its tokens travel inside the
  tokens Amazon holds, sealed with AES-GCM under `SEAL_KEY`, so the relay can't be made to call an
  address a household didn't link.
- **Requests** arrive at `/skill` straight from Amazon (signed by Amazon), or at `/forward` from
  the skill's Alexa-hosted forwarder ([`../alexa/forwarder/index.js`](../alexa/forwarder/index.js)),
  which proves itself with `FORWARD_SECRET`. The forwarder exists because Amazon's skill service
  may refuse to connect to some HTTPS endpoints, while ordinary HTTPS from inside Amazon works.
- Each household server checks the skill ID and its own link token itself, and only signs in its
  own administrator.

Secrets: `CLIENT_SECRET` (also entered in the skill's account linking), `SEAL_KEY` (long random
text; changing it unlinks every household) and `FORWARD_SECRET` (also pasted into the forwarder).
Variable: `CLIENT_ID` (default `nara-hem`).

To make the skill: create an **Alexa-hosted (Node.js)** custom skill, paste
[`../alexa/interaction-model.json`](../alexa/interaction-model.json) into the JSON Editor, replace
`lambda/index.js` with the forwarder (filling in the relay's address and `FORWARD_SECRET`), and
turn on account linking (**Auth Code Grant**, Web Authorization URI `https://<relay>/link`,
Access Token URI `https://<relay>/token`, client ID `nara-hem`, scope `household`, HTTP Basic).
Servers then need `NARAHEM_ALEXA_RELAY_URL` and the skill's ID in
`NARAHEM_ALEXA_STORE_SKILL_ID`.

## Tests

```bash
node --test 'deploy/cloudflare/tests/*.test.mjs'
```

They run each Worker against fake Apple, Google and household servers; nothing is sent for real.
