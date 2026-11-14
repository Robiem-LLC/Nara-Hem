# Running a Nära Hem server

One stack is one household: the Nära Hem server and its PostgreSQL database. HTTPS is up to you
(a Cloudflare Tunnel or a reverse proxy); the server itself only listens on plain HTTP.

## Install with Portainer

Paste [`portainer-stack.yaml`](portainer-stack.yaml) into **Portainer → Stacks → Add stack → Web
editor** and set these in the stack's environment variables (never in the YAML):

| Variable              | Value                                                                 |
| --------------------- | --------------------------------------------------------------------- |
| `NARAHEM_IMAGE`       | The published server image, without a tag: `ghcr.io/<owner>/nara-hem` |
| `NARAHEM_PUBLIC_URL`  | Your exact HTTPS address, e.g. `https://narahem.example.com`          |
| `NARAHEM_DB_PASSWORD` | A long random password. Never change it after the first start.        |

Everything marked `#optional` in the file has a default: the image tag (`latest`), the base folder
(`/opt/docker/narahem`, holding `server-data`, `database-data` and `exports`), the port (`8186`),
a Google Maps key, a Textbelt key for text messages, Alexa, and your own push relays.

Point your tunnel or proxy at the port, keeping the original `Host` header. Don't expose the port
to the internet directly.

**Moving an existing install:** keep the same base folder. `server-data` holds the encryption
keys; an empty folder starts a fresh household.

## Or: Docker Compose

Save [`compose.yaml`](compose.yaml) and [`prepare.py`](prepare.py) in a folder, then:

```bash
python3 prepare.py --image ghcr.io/<owner>/nara-hem --url https://narahem.example.com
```

```bash
docker compose up -d
```

`prepare.py` writes a private `.env` with a random database password and never overwrites it. The
port is bound to localhost; `--bind <LAN-IP>` binds it to your LAN address for a proxy in another
container.

### Cloudflare Tunnel

A tunnel makes the server reachable without opening a port or publishing your home's IP:

1. In Cloudflare Zero Trust, create a tunnel and route your hostname to `http://narahem:8080`.
2. Put the tunnel token in `.env` as `NARAHEM_CLOUDFLARE_TUNNEL_TOKEN`, and the hostname in
   `NARAHEM_PUBLIC_URL`.
3. Start with both files, and keep using both for later `pull`, `up` and `down`:

   ```bash
   docker compose -f compose.yaml -f compose.tunnel.yaml up -d
   ```

Remove any old DNS record that points this hostname at your home's IP.

## First start

1. Open your HTTPS address. Get the setup token with:

   ```bash
   docker compose exec narahem python manage.py bootstrap-token
   ```

   In Portainer, run `python manage.py bootstrap-token` in the container's console.

2. Name the household and create the administrator. Setup then closes for good.
3. Sign in, set up email in **Admin settings**, and send yourself a test.
4. Trust this browser in **Manage household** and follow the steps on screen.
5. Invite your household. Their invitation has the app download links and your server's address.

## Optional settings

- **Google Maps:** set `NARAHEM_GOOGLE_MAPS_API_KEY` to a browser key with Maps JavaScript API and
  Geocoding API, restricted to your address (`https://narahem.example.com/*`). Without one, maps
  use OpenStreetMap.
- **Text messages:** add a Textbelt key in **Admin settings**, or set `NARAHEM_TEXTBELT_KEY`.
- **Alexa:** see [docs/alexa.md](../docs/alexa.md).
- **Push notifications:** official images know the push relays, and the server registers with
  them by itself the first time. To run your own relays, see
  [cloudflare/README.md](cloudflare/README.md) and set `NARAHEM_PUSH_RELAY_URL` and
  `NARAHEM_FCM_RELAY_URL` (and their `_TOKEN`s if your relay issues them by hand).
- **Street addresses in alerts:** the server looks up an address for places that aren't saved,
  with your Google key if it works from the server, otherwise OpenStreetMap.
  `NARAHEM_ALERT_ADDRESSES=0` turns lookups off.
- **History:** kept 14 days by default; shorten it in **Admin settings**.

## Updates

Pull the new image and redeploy the same stack (in Portainer: **Update the stack** with **Re-pull
image** on), or:

```bash
docker compose pull && docker compose up -d
```

`latest` is the release channel and `dev` the test channel (`NARAHEM_TAG`). The database is
upgraded automatically on start. An upgraded database may not work with an older image, so back
up before switching from `dev` back to `latest`.

`docker compose down` keeps your data; **`docker compose down -v` deletes it.**

## Backups

Back up the database **and** `server-data` together: the database alone can't be decrypted
without the keys in `server-data`. Stop the server while you copy them:

```bash
docker compose stop narahem
docker compose exec -T database pg_dump -U narahem -d narahem > database.sql
docker compose cp --archive narahem:/data server-data
docker compose start narahem
```

Keep backups encrypted and off the server. To restore, start an empty stack's database, import
`database.sql` with `psql`, copy `server-data` back into `/data` with `docker compose cp
--archive`, then start the server.

## When something goes wrong

- **Forgot the administrator password:**
  `docker compose exec narahem python manage.py reset-owner-password`.
- **Diagnostics:** **Admin settings → Storage and retention → Save to exports folder** writes a
  redacted report (no locations, keys or emails) to the `exports` folder.
- **Every trusted device lost:** approve a new one from any other trusted device. If there is
  none, `python manage.py reset-encryption` starts a new household identity; it deletes all
  shared data and can't be undone.
- **Remove someone:** **Manage household → Revoke** blocks them; **Delete user and data** removes
  their account and data.

## What the server can see

The server is the household's source of truth: it can read everyone's locations, trips, places
and photos. See [docs/security-model.md](../docs/security-model.md).
