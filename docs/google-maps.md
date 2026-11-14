# Google Maps

Without a key, the web app uses OpenStreetMap, which needs nothing from you. With a Google Maps key
it shows Google maps, and address search uses Google too. The phone apps have their own maps built
in; this key is only for your server's web app.

## Make the key

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project (or pick one)
   and turn on billing. Google gives a free monthly allowance; a household stays well inside it.
2. **APIs & Services → Library**: enable **Maps JavaScript API** and **Geocoding API**. Optionally
   also **Maps Static API**, for Google map thumbnails on trip cards (otherwise they use
   OpenStreetMap).
3. **APIs & Services → Credentials → Create credentials → API key**, then edit the key:
   - **Application restrictions → Websites**: add your server's address followed by `/*`, e.g.
     `https://family.example.com/*`.
   - **API restrictions → Restrict key**: tick the APIs from step 2.
   - **Save**.
4. Optional but sensible: under each API's **Quotas**, set a daily limit so a mistake can never cost
   you money.

## Use it

1. Add `NARAHEM_GOOGLE_MAPS_API_KEY` with the key to your stack's environment variables and
   redeploy.
2. Reload the web app. On the household map, **Load Google Maps** now appears instead of **Load
   OpenStreetMap tiles**.

The key is visible to anyone signed in to your web app; that's normal for a website key, and the
website restriction stops it working anywhere else.

Street addresses in alerts are looked up by the server itself. A website-restricted key doesn't
work from a server, so those lookups use OpenStreetMap; that's expected.

If the map stays grey or shows an error, check that your exact address is in the key's websites,
that the APIs are ticked, and that billing is on. Changes to a key can take five minutes.
