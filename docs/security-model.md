# Security model

## What the server can see

The household server is the source of truth. It can read:

- **Locations:** every GPS fix a phone sends (position, accuracy, speed, battery, charging, drive ID), for the retention period (14 days by default).
- **Trips:** start and end times and points, distance, top speed, route outline, and the full GPS route.
- **Saved places:** names, centers, radii and alert rules.
- **Profiles:** names and photos.
- **Alerts:** it decides and writes "Sam left Home" and "Sam arrived at Work after a 7.1 mile drive" itself.

What this means:

- **Whoever runs the server can see all of the above.** So can anyone who gets into the running server, or into its data volume, which holds the keys.
- **A database dump or backup alone does not reveal coordinates.** Records are stored encrypted with keys kept on the data volume, not in the database. Back the volume up separately and keep it private.
- **Third parties see less:**
  - For somewhere that is not a saved place, the server sends that one coordinate to Google's Geocoding API (if the server's Maps key allows it) or to OpenStreetMap Nominatim, to get a street address for the alert or for a trip's start or end (once per trip). Set `NARAHEM_ALERT_ADDRESSES=0` to turn this off.
  - Apple and Google push services carry only a few fixed messages ("A household update is available", "Household alert", the Find My Phone ring) and see when each phone is woken. They never get names, places, alert text or locations: the phone fetches those from your server and decrypts them itself.
  - Map tile providers see the regions viewed in the apps and the web app.
- **The server enforces who sees what.** It only shows a member's location, trips and alerts to the accounts that member's phone shares with, and only trips from the day each account joined. A server bug or a malicious operator can bypass that.
- **Records are still signed and encrypted for each approved device.** That gives sender authentication, tamper and replay protection, and device approval. It no longer keeps data from the server.

## What protects your data

- **In transit:** HTTPS, and every location record is signed by the phone that sent it, so it
  can't be forged, changed or replayed.
- **New devices:** a phone or browser gets nothing until it's approved, and approvals are signed,
  so a server can't quietly add a device on its own.
- **Removing someone:** revoking or deleting a member stops their sessions and devices straight
  away. What they already saw can't be taken back.
- **Sign-in:** email or text codes only prove who you are; they never hand out household keys.

## Limits

- Anyone who can see a member's location in the app can also record it.
- The server sees ordinary metadata even for encrypted data: IP addresses, emails, device IDs,
  timing and sizes.
- Nära Hem has not had an independent security audit.
