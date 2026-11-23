# Troubleshooting

Commands below are run on the server. With Docker Compose, run them from the stack's folder as
shown. In Portainer, open **Containers** → the `narahem` container → **Console** → **Connect**,
and run just the part from `python` on.

## The setup token

First-time setup asks for a token. The server prints it in its log on first start (`NARAHEM
FIRST-RUN SETUP TOKEN: …`). If the log has rotated:

```bash
docker compose exec narahem python manage.py bootstrap-token
```

It only exists until setup is done.

## The device bootstrap token

Trusting your first browser asks for this token (or a six-digit code by email, once email works):

```bash
docker compose exec narahem python manage.py device-bootstrap-token
```

## Forgotten administrator password

Password-reset emails only work once email is set up in **Admin settings**. Otherwise, set a new
password on the server (it asks twice; nothing shows while you type):

```bash
docker compose exec -it narahem python manage.py reset-owner-password
```

This signs the administrator out everywhere. A member who forgot theirs: **Manage household →
Send password reset**.

## Your trusted browser is lost

Phones never need this: a member just signs in again on the app with their email or text code. A
new **browser** is approved from another trusted browser (**Manage household → Device access**).

If no trusted browser is left, start a new household identity. This deletes every shared location,
trip, place and profile photo, and every phone and browser has to join again. Accounts and email
settings stay. It can't be undone:

```bash
docker compose exec -it narahem python manage.py reset-encryption
```

## The server won't start

Check the server's log:

- **"Server key does not match stored credentials"**: the `server-data` folder doesn't belong to
  this database. Restore the matching `server-data`, or start both fresh.
- **"Bootstrap token file is missing"**: `server-data` was lost before setup finished. Restore it.
- **Database password errors**: `NARAHEM_DB_PASSWORD` changed after the first start. Put the
  original back.

## The page won't load or sign-in fails

`NARAHEM_PUBLIC_URL` must be exactly the address in the browser, with `https://` and no trailing
slash. The server refuses requests for any other address. Your tunnel or proxy must also keep the
original `Host` header.

## Emails don't arrive

**Admin settings → Email → Send test.** Many providers need an app password rather than your normal
one. Check the spam folder too.

## Texts and links

Textbelt refuses links, a bare address like `family.example.com` included, so Nära Hem's texts
never contain any. An invitation text writes your server's address with each dot as `<.>`
(`family<.>example<.>com`), which the apps accept as typed, and says to get the app from the
phone's store; in
the app, **Register new account** sets up the account, and the six-digit code texted when the
phone is approved confirms it. Password reset links go by email only, so a member with only a
phone number can't reset their password by text yet. **Admin settings → Text messages → Send test
text** checks the key.

## No notifications on phones

- **Admin settings → Push relays** should show both relays as registered; if not, **Register
  now**.
- On the phone, notifications must be allowed for Nära Hem. On Android, also turn off battery
  optimisation for the app.

## The map is grey or won't load

See the end of [Google Maps](google-maps.md). Without a key, the map uses OpenStreetMap.

## Alexa

See [Alexa troubleshooting](alexa.md#troubleshooting).

## Sending a diagnostic report

**Admin settings → Storage and retention → Save to exports folder** writes a redacted report (no
locations, keys or emails) to the `exports` folder, or run:

```bash
docker compose exec narahem python manage.py diagnostics
```
