# Installing a Nära Hem server

One server is one household: Nära Hem and its PostgreSQL database, running in Docker. Once it's
running, [first-time setup](../docs/setup.md) walks you through the household, email and phones.
If something goes wrong, see [troubleshooting](../docs/troubleshooting.md).

## Before you start

- **A computer that runs Docker** around the clock, such as a home server or NAS.
- **A domain name** for the server's HTTPS address, e.g. `family.example.com`. The phone apps only
  connect over HTTPS (see [Reaching your server](#reaching-your-server)).
- **An email account that can send mail by SMTP**, such as your provider's SMTP server with an app
  password. Nära Hem emails invitations and sign-in codes.
- **Optional: a Google Maps key** for Google maps and address search; without one, maps use
  OpenStreetMap. See [Google Maps](../docs/google-maps.md).
- **Optional: a [Textbelt](https://textbelt.com) key** to send invitations and codes by text
  message as well as email.

## Install with Docker

<details>
<summary><strong>Portainer</strong></summary>

1. **Stacks → Add stack → Web editor**, and paste [`portainer-stack.yaml`](portainer-stack.yaml).
2. Under **Environment variables**, add the [needed variables](#needed), and any
   [optional ones](#optional) you want. Keep them there, never in the YAML.
3. **Deploy the stack.**

Your data is kept in `/opt/docker/narahem` (`server-data`, `database-data` and `exports`). To
update later: **Update the stack** with **Re-pull image and redeploy** on.

</details>

<details>
<summary><strong>Docker Compose</strong></summary>

1. Save [`compose.yaml`](compose.yaml) and [`prepare.py`](prepare.py) in a new folder.
2. Create the private `.env` file, with a random database password:

   ```bash
   python3 prepare.py --image ghcr.io/<owner>/nara-hem --url https://family.example.com
   ```

   Add any [optional variables](#optional) to `.env` as `NAME=value` lines.

3. Start it:

   ```bash
   docker compose up -d
   ```

The port is only reachable from the server itself; `prepare.py --bind <LAN-IP>` opens it to your
network instead, e.g. for a proxy on another machine. To update later:
`docker compose pull && docker compose up -d`.

</details>

The server listens on port `8186` with plain HTTP. Don't forward that port on your router: put
HTTPS in front of it (next section).

## Variables

### Needed

| Variable              | Value                                                                      |
| --------------------- | -------------------------------------------------------------------------- |
| `NARAHEM_IMAGE`       | The server image, without a tag: `ghcr.io/<owner>/nara-hem`                |
| `NARAHEM_PUBLIC_URL`  | The exact HTTPS address people will use, e.g. `https://family.example.com` |
| `NARAHEM_DB_PASSWORD` | A long random password. Never change it after the first start.             |

### Optional

| Variable                                         | Default                    | What it does                                                                              |
| ------------------------------------------------ | -------------------------- | ----------------------------------------------------------------------------------------- |
| `NARAHEM_TAG`                                    | `latest`                   | Image channel: `latest` (releases) or `dev` (test builds).                                |
| `NARAHEM_DIR`                                    | `/opt/docker/narahem`      | Folder for the data (Portainer stack).                                                    |
| `NARAHEM_PORT`                                   | `8186`                     | Port the server listens on.                                                               |
| `NARAHEM_GOOGLE_MAPS_API_KEY`                    | none: OpenStreetMap        | Google Maps browser key ([Google Maps](../docs/google-maps.md)).                          |
| `NARAHEM_TEXTBELT_KEY`                           | none                       | Textbelt key for text messages. You can also add it in **Admin settings**; this one wins. |
| `NARAHEM_ALLOW_ALEXA`                            | `false`                    | `true` lets you link the Alexa skill ([Alexa](../docs/alexa.md)).                         |
| `NARAHEM_ALERT_ADDRESSES`                        | on                         | `0` stops street-address lookups for alerts and trips ("left an unsaved place").          |
| `NARAHEM_STORAGE_QUOTA_MIB`                      | `512`                      | Most space encrypted records may use, in MiB.                                             |
| `NARAHEM_SETUP_TOKEN`                            | generated                  | Your own first-run setup token (8–256 characters). Only used until setup is done.         |
| `NARAHEM_IOS_APP_URL`, `NARAHEM_ANDROID_APP_URL` | built into official images | If you build your own apps, point the invitation links to them; `none` leaves one out.    |
| `NARAHEM_ALLOW_HTTP`                             | `0`                        | `1` allows plain HTTP for testing on your own network only. Never for normal use.         |

Docker Compose also reads `NARAHEM_BIND_ADDRESS` (where the port listens) and
`NARAHEM_EXPORTS_PATH` (the diagnostic reports folder).

## Reaching your server

The apps and browsers need an HTTPS address that leads to port `8186` on your server. How you do
that is up to you, and the steps depend on what you use; follow its own instructions. Two common,
easy options:

- **Cloudflare Tunnel:** no open ports on your router, and your home's IP stays hidden.
- **A reverse proxy** such as Nginx Proxy Manager, with a free Let's Encrypt certificate.

Whichever you choose:

- `NARAHEM_PUBLIC_URL` must be exactly that HTTPS address; the server refuses requests for any
  other.
- Keep the original `Host` header when forwarding.
- Don't forward port `8186` itself to the internet.

## Updates

Pull the new image and redeploy the same stack. The database is upgraded automatically on start.
An upgraded database may not work with an older image, so back up before switching from `dev` back
to `latest`. `docker compose down` keeps your data; **`docker compose down -v` deletes it.**

## Backups

Back up the database **and** `server-data` together: the database can't be read without the keys
in `server-data`. Stop the server while you copy them:

```bash
docker compose stop narahem
docker compose exec -T database pg_dump -U narahem -d narahem > database.sql
docker compose cp --archive narahem:/data server-data
docker compose start narahem
```

Keep backups encrypted and off the server. To restore, start an empty stack's database, import
`database.sql` with `psql`, copy `server-data` back into `/data` with `docker compose cp
--archive`, then start the server.
