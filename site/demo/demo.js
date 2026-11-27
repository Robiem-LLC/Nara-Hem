// The showcase site's home page: the real web app's screens, captured from the showcase
// household (tools/showcase/record.cjs), brought back to life with a live map, moving
// family members, working tabs and trip routes, plus iPhone, Android and Alexa tabs and a
// short description under each screen. Nothing here talks to a server; buttons that would
// change data explain that instead.
(() => {
  'use strict';
  const { snapshots: S, data: D, site: SITE = {} } = window.NARAHEM_DEMO;
  const app = document.getElementById('app');
  const toast = document.getElementById('demo-toast');
  const TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  // OpenStreetMap serves tiles only to pages that say which site they're on. A page
  // opened straight from disk can't, so it gets a plain map and a note instead.
  const FROM_DISK = location.protocol === 'file:';
  /** Adds OpenStreetMap tiles to a map (skipped when opened from disk). */
  const tiles = (target) => {
    if (FROM_DISK) return;
    L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION, referrerPolicy: 'origin' }).addTo(
      target,
    );
  };
  const DISK_NOTE =
    '<p class="demo-disk-note">Previewing from disk: OpenStreetMap only sends map imagery to ' +
    'pages served from a web address, so the map background is blank here.</p>';
  const ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" ' +
    'rel="noopener">OpenStreetMap</a> contributors';
  const MINT = '#a5f0bc';
  // With a Google key built in, the demo shows Google Maps like a real server with a key.
  const GOOGLE_KEY = FROM_DISK ? '' : SITE.google_maps_key || '';
  let googleLoad = null;
  let googleFailed = false;
  const places = Object.fromEntries(D.places.map((p) => [p.name, [p.lat, p.lon]]));
  let map = null;
  let ticker = null;
  let member = null;

  const timeFormat = { hour: 'numeric', minute: '2-digit' };
  /** A time of day, the way the app shows it. */
  const clock = (date, seconds) =>
    date.toLocaleTimeString('en-US', seconds ? { ...timeFormat, second: '2-digit' } : timeFormat);

  // The recording's time zone: older recordings didn't say, and were made in Portland's.
  const RECORDED_ZONE = S.recorded.zone || 'America/Los_Angeles';

  /**
   * Returns the moment a captured clock time stood for: that time on the recording's day, in the
   * recording's time zone. A time later than the recording itself was the day before.
   */
  function recordedMoment(hours, minutes, seconds, day) {
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat('en-US', {
        timeZone: RECORDED_ZONE,
        hourCycle: 'h23',
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
        hour: 'numeric',
        minute: 'numeric',
        second: 'numeric',
      })
        .formatToParts(new Date(S.recorded.at))
        .map((part) => [part.type, Number(part.value)]),
    );
    const wall = Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second,
    );
    const offset = wall - Math.floor(S.recorded.at / 1000) * 1000;
    if (day) return Date.UTC(day.year, day.month, day.day, hours, minutes, seconds) - offset;
    const moment =
      Date.UTC(parts.year, parts.month - 1, parts.day, hours, minutes, seconds) - offset;
    return moment > S.recorded.at + 60000 ? moment - 86400000 : moment;
  }

  /**
   * Redates the trip list's day headings ("Fri, Nov 13, 2026") from the first time under each,
   * moved like every other time, so a trip shows under the visitor's own day.
   */
  function tripDays(html) {
    const shift = Date.now() - S.recorded.at;
    const heading = /<h3>(\w{3}, (\w{3}) (\d{1,2}), (\d{4}))<\/h3>/g;
    return html.replace(heading, (text, label, month, date, year, at) => {
      const next = /\b(\d{1,2}):(\d{2}) (AM|PM)\b/.exec(html.slice(at));
      const parsed = new Date(`${month} ${date}, ${year}`);
      if (!next || Number.isNaN(parsed.getTime())) return text;
      const hours = (Number(next[1]) % 12) + (next[3] === 'PM' ? 12 : 0);
      const day = { year: Number(year), month: parsed.getMonth(), day: Number(date) };
      const moment = new Date(recordedMoment(hours, Number(next[2]), 0, day) + shift);
      const shown = moment.toLocaleDateString('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
      return `<h3>${shown}</h3>`;
    });
  }

  /**
   * Replaces the recording date in captured screens with today's date, and moves every captured
   * time by as long as it's been since the recording, shown in the visitor's own time zone.
   */
  function today(html) {
    const shift = Date.now() - S.recorded.at;
    const now = new Date();
    html = html
      .split(S.recorded.short)
      .join(now.toLocaleDateString('en-US'))
      .split(S.recorded.long)
      .join(
        now.toLocaleDateString('en-US', {
          weekday: 'short',
          month: 'short',
          day: 'numeric',
          year: 'numeric',
        }),
      );
    return (
      html
        .replace(/\b(\d{1,2}):(\d{2})(?::(\d{2}))? (AM|PM)\b/g, (text, h, m, s, half) => {
          const hours = (Number(h) % 12) + (half === 'PM' ? 12 : 0);
          const then = recordedMoment(hours, Number(m), Number(s || 0));
          return clock(new Date(then + shift), s !== undefined);
        })
        .replace(/src="\/app-icon\.png"/g, 'src="demo/app-icon.png"')
        .replace(/src="\/nara-hem-wordmark\.png"/g, 'src="demo/nara-hem-wordmark.png"')
        // The captured household fingerprint is the throwaway demo server's; show nonsense.
        .replace(/(<code id="root-code">)[^<]*(<\/code>)/g, '$1d3m0-n0t-a-r3al-h0u5eh0ld-0000$2')
        .split(S.recorded.origin || '\u0000')
        .join('https://family.example.com')
    );
  }

  /** Shows a toast message. */
  function say(text) {
    toast.textContent = text;
    toast.hidden = false;
    clearTimeout(say.timer);
    say.timer = setTimeout(() => {
      toast.hidden = true;
    }, 3200);
  }

  /** Notifies the embedding page which screen is showing. */
  function tell(view, detail = {}) {
    try {
      parent.postMessage({ source: 'narahem-demo', view, ...detail }, '*');
    } catch {
      /* standalone */
    }
  }

  /** Creates an element from an HTML string. */
  function element(html) {
    const holder = document.createElement('div');
    holder.innerHTML = html.trim();
    return holder.firstElementChild;
  }

  /** Returns the length of a route in coordinate units. */
  function pathLength(path) {
    let total = 0;
    for (let i = 1; i < path.length; i++) {
      total += L.latLng(path[i - 1]).distanceTo(L.latLng(path[i]));
    }
    return total;
  }

  /** Returns the point at a fraction of the route's length. */
  function along(path, fraction) {
    const target = pathLength(path) * fraction;
    let walked = 0;
    for (let i = 1; i < path.length; i++) {
      const step = L.latLng(path[i - 1]).distanceTo(L.latLng(path[i]));
      if (walked + step >= target) {
        const t = step ? (target - walked) / step : 0;
        return [
          path[i - 1][0] + (path[i][0] - path[i - 1][0]) * t,
          path[i - 1][1] + (path[i][1] - path[i - 1][1]) * t,
        ];
      }
      walked += step;
    }
    return path[path.length - 1];
  }

  const SCREENS = {
    map: 'map',
    trips: 'trips',
    places: 'places',
    household: 'household',
    settings: 'settings',
    ios: 'map',
    android: 'map',
    alexa: 'map',
  };
  const NAV = {
    'open-map': 'map',
    'open-trips': 'trips',
    'open-places': 'places',
    'open-household': 'household',
    'open-settings': 'settings',
    'open-ios': 'ios',
    'open-android': 'android',
    'open-alexa': 'alexa',
  };
  const NAME = SITE.name || 'Nära Hem';

  /** Escapes text for HTML. */
  const escape = (text) =>
    String(text).replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
    );

  /** A button that opens a link, styled like the app's own buttons. */
  const linkButton = (label, href, secondary = false, external = true) =>
    href
      ? `<button type="button" class="${secondary ? 'secondary' : ''}" data-href="${escape(href)}"` +
        `${external ? ' data-external' : ''}>${escape(label)}</button>`
      : '';

  /** The official badges: the site.json link each opens, its image and its words. */
  const BADGES = {
    app_store: ['app-store.svg', 'Download on the App Store'],
    google_play: ['google-play.png', 'Get it on Google Play'],
    alexa_skill: ['just-ask-alexa.png', 'Just ask Alexa'],
  };

  /** A badge linking to its listing, or nothing without a link in site.json. */
  const storeBadge = (store) => {
    const [image, words] = BADGES[store];
    return SITE[store]
      ? `<a class="store-badge" href="${escape(SITE[store])}" target="_blank" rel="noopener">` +
          `<img src="badges/${image}" alt="${words}" height="40" /></a>`
      : '';
  };

  /** The real app, filmed on a phone, playing inside a phone frame. */
  const phoneVideo = (name, label) =>
    SITE.media?.[name]
      ? `<figure class="site-phone"><div class="phone phone-${name}">` +
        `<video src="media/${name}.mp4" poster="media/${name}.png" autoplay muted loop ` +
        `playsinline preload="metadata" aria-label="${escape(label)}"></video></div></figure>`
      : '';

  /** The extra screens that aren't part of the web app: the phone apps and Alexa. */
  const EXTRA = {
    ios: () => `
      <section class="card site-app">
        ${phoneVideo('ios', `${NAME} on an iPhone`)}
        <div>
          <p class="eyebrow">iPhone</p>
          <h2>${escape(NAME)} for iPhone</h2>
          <p>The phone shares where it is, even in the background, records each drive as a
          trip and tells the family when someone arrives at or leaves a saved place. It can
          ring at full volume when someone asks your server to find it.</p>
          <ul>
            <li>Every location is encrypted on the phone before it leaves.</li>
            <li>Battery-friendly: precise only while moving.</li>
            <li>Choose who in the household can see you.</li>
          </ul>
          ${
            SITE.app_store
              ? `<div class="links">${storeBadge('app_store')}</div>
          <p class="subtle">Needs iOS 17 or later.</p>`
              : `<div class="links">${linkButton('Join the beta on TestFlight', SITE.testflight)}</div>
          <p class="subtle">Needs iOS 17 or later. Install Apple's TestFlight app first, then
          open the invitation link on the iPhone.</p>`
          }
        </div>
      </section>`,
    android: () => `
      <section class="card site-app">
        ${phoneVideo('android', `${NAME} on an Android phone`)}
        <div>
          <p class="eyebrow">Android</p>
          <h2>${escape(NAME)} for Android</h2>
          <p>The same app for Android: live location in the background, trips, arrival and
          departure alerts, and Find my phone that rings even on silent.</p>
          <ul>
            <li>Every location is encrypted on the phone before it leaves.</li>
            <li>Works with or without Google services.</li>
            <li>Choose who in the household can see you.</li>
          </ul>
          ${
            SITE.on_google_play
              ? `<div class="links">${storeBadge('google_play')}${linkButton(
                  'Download the APK',
                  SITE.github && `${SITE.github}/releases/latest`,
                  true,
                )}</div>
          <p class="subtle">Needs Android 8.0 or later. For a phone without Google Play, open the
          APK on the phone and allow your browser to install apps when Android asks.</p>`
              : `<div class="links">${linkButton('Download the Android app', SITE.android)}</div>
          <p class="subtle">Needs Android 8.0 or later. Open the download on the phone and allow
          your browser to install apps when Android asks.</p>`
          }
        </div>
      </section>`,
    alexa: () => `
      <section class="card site-app site-alexa">
        <div>
          <p class="eyebrow">Alexa integration</p>
          <h2>Ask Alexa where everyone is</h2>
          <div class="site-chat" aria-label="Example conversations">
            <p class="you">Alexa, ask ${escape(SITE.alexa_name || NAME)} where Maya is.</p>
            <p class="alexa">Maya has been at Lincoln Middle School since 2:45 PM.</p>
            <p class="you">Alexa, ask ${escape(SITE.alexa_name || NAME)} where Alex is.</p>
            <p class="alexa">Alex is driving near Hawthorne Boulevard.</p>
            <p class="you">Alexa, ask ${escape(SITE.alexa_name || NAME)} to find Leo's phone.</p>
            <p class="alexa">Ringing Leo's phone now.</p>
          </div>
        </div>
        <div>
          <h3>How it works</h3>
          <ul>
            <li>Off unless your server's administrator turns it on.</li>
            <li>Alexa signs in to your own server as its administrator, and can be unlinked
            there at any time.</li>
            <li>Mishear a name? Alexa asks "Did you mean Maya?"</li>
            <li>Rings only phones that have Find my phone turned on.</li>
            <li>Spoken answers pass through Amazon; everything else stays end-to-end encrypted
            on your server.</li>
          </ul>
          <div class="links">
            ${linkButton('Alexa setup guide', SITE.github && SITE.github + '/blob/main/docs/alexa.md', true)}
          </div>
          <div class="links site-alexa-badge">${storeBadge('alexa_skill')}</div>
        </div>
      </section>`,
  };

  /** The short description shown under each screen. */
  const ABOUT = {
    map: [
      'Everyone, on one map',
      'Family members who share their location appear with their photo, live, along with ' +
        'the places that matter to you. Tap someone to see where they are and when they last ' +
        'checked in. Two of this made-up family are driving right now.',
    ],
    trips: [
      'Every drive, remembered',
      'Each phone records its drives as trips: where it started and ended, the route, the ' +
        'distance and top speed, and how long someone stayed in between. Pick a family member ' +
        'and open a trip to see its route.',
    ],
    places: [
      'Places that matter',
      "Save Home, school, work or Grandma's house. When someone arrives or leaves, the " +
        'family gets a notification, worked out on your own server.',
    ],
    household: [
      'Your household, your rules',
      "Invite people by email or text message, approve their phones, and see each phone's " +
        'permissions and battery. Remove a person or a phone at any time.',
    ],
    settings: [
      'You run the server',
      `${NAME} runs on a server you own, in a Docker container. Connect email and text ` +
        'messages for invitations, push notifications for the phones, and Alexa if you want ' +
        "it. Nobody else, not even us, can read your family's locations.",
    ],
    ios: [
      'iPhone app',
      (SITE.app_store ? 'Get it on the App Store' : 'Join the public TestFlight beta') +
        ', then sign in with the server address and account from your invitation.',
    ],
    android: [
      'Android app',
      'Download the app directly, then sign in with the server address and account from ' +
        'your invitation.',
    ],
    alexa: [
      'Alexa integration',
      'An optional skill that answers where household members are and rings their phones, ' +
        'from your own server.',
    ],
  };

  /** Switches the demo to a screen. */
  function show(screen, options = {}) {
    if (screen === 'trips' && !options.member && S.tripsByMember) {
      options = { ...options, member: Object.keys(S.tripsByMember)[0] };
    }
    if (map) {
      map.remove();
      map = null;
    }
    clearInterval(ticker);
    const snap = S[SCREENS[screen]] || S.map;
    const body = Object.hasOwn(EXTRA, screen)
      ? EXTRA[screen]()
      : screen === 'trips' && options.member && S.tripsByMember?.[options.member]
        ? today(tripDays(S.tripsByMember[options.member]))
        : today(screen === 'trips' ? tripDays(snap.view) : snap.view);
    const [title, text] = ABOUT[screen] || ABOUT.map;
    app.innerHTML =
      today(snap.header) +
      S.map.nav +
      '<div id="message" role="status" aria-live="polite" hidden></div><div id="view">' +
      body +
      '</div>' +
      `<section class="site-about"><h2>${escape(title)}</h2><p>${escape(text)}</p></section>` +
      siteFooter();
    siteHeader();
    for (const button of app.querySelectorAll('#app-nav button')) {
      const active = NAV[button.id] === screen;
      button.classList.toggle('secondary', !active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
    for (const image of app.querySelectorAll('img[src^="https://tile.openstreetmap.org"]')) {
      image.referrerPolicy = 'origin';
      if (FROM_DISK) image.remove();
    }
    if (FROM_DISK) {
      for (const area of app.querySelectorAll('#household-map, #place-list')) {
        area.insertAdjacentHTML('beforebegin', DISK_NOTE);
      }
    }
    mapProvider(GOOGLE_KEY && !googleFailed);
    if (screen === 'map') liveMap();
    if (screen === 'household') householdLocations();
    if (screen === 'trips') trips(options.member);
    if (screen === 'places') {
      const status = app.querySelector('#map-status');
      if (status) status.textContent = '';
      googlePlaceThumbnails();
    }
    tell(screen, options.member ? { member: options.member } : {});
    app.scrollTop = 0;
    window.scrollTo(0, 0);
  }

  /** Puts the site's GitHub and Install buttons where Sign out is, and adds the extra tabs. */
  function siteHeader() {
    // The site says what Nära Hem is; the app's own tagline stays in the app.
    app
      .querySelector('header .eyebrow')
      ?.replaceWith(
        element(
          '<div class="site-tagline"><p>A self-hosted family location tracking ecosystem.</p>' +
            '<p>Take back your data.</p>' +
            '<p class="site-license">Free and open source (AGPL-3.0). ' +
            'You pay only for your own server.</p></div>',
        ),
      );
    app
      .querySelector('#logout')
      ?.replaceWith(
        element(
          '<div class="site-actions">' +
            linkButton('GitHub', SITE.github, true) +
            linkButton('Install', SITE.install || 'setup.html', false, false) +
            '</div>',
        ),
      );
    const title = app.querySelector('header h1');
    if (title && !app.querySelector('.site-stores')) {
      const badges = Object.keys(BADGES).map(storeBadge).join('');
      if (badges) {
        title.insertAdjacentHTML('afterend', `<div class="site-stores">${badges}</div>`);
        const row = element('<div class="site-title"></div>');
        title.before(row);
        row.append(title, app.querySelector('.site-stores'));
        alignStores();
      }
    }
    const nav = app.querySelector('#app-nav');
    if (!nav || nav.querySelector('#open-ios')) return;
    nav.insertAdjacentHTML(
      'beforeend',
      '<button id="open-ios" class="secondary">iPhone</button>' +
        '<button id="open-android" class="secondary">Android</button>' +
        '<button id="open-alexa" class="secondary">Alexa</button>',
    );
  }

  /** Starts the header's badges where the Admin settings tab starts, when they fit beside the
   * wordmark; on a narrow screen they sit under it. */
  function alignStores() {
    const stores = app.querySelector('.site-stores');
    const title = app.querySelector('header h1');
    const tab = app.querySelector('#open-settings');
    if (!stores || !title) return;
    stores.style.marginLeft = '';
    if (!tab?.offsetParent || window.innerWidth <= 760) return;
    // The row already leaves 16px between the wordmark and the badges.
    const extra = tab.getBoundingClientRect().left - title.getBoundingClientRect().right - 16;
    if (extra > 0) stores.style.marginLeft = `${extra}px`;
  }
  window.addEventListener('resize', alignStores);

  /** The site's footer, in place of the app's. */
  function siteFooter() {
    const links = [
      ['Install', SITE.install || 'setup.html'],
      ['Privacy', 'privacy.html'],
      ['Terms', 'terms.html'],
      ['GitHub', SITE.github],
    ]
      .filter(([, href]) => href)
      .map(([label, href]) => `<a href="${escape(href)}">${label}</a>`)
      .join(' · ');
    return (
      '<footer>Every person, place and trip on this page is made up. ' +
      `${links}${SITE.contact ? ` · <a href="mailto:${escape(SITE.contact)}">${escape(SITE.contact)}</a>` : ''}</footer>`
    );
  }

  /** Loads Google Maps once; rejects when there is no key or it can't load. */
  function loadGoogle() {
    if (!GOOGLE_KEY || googleFailed) return Promise.reject(new Error('No Google Maps'));
    googleLoad ??= new Promise((resolve, reject) => {
      // With loading=async, Google sets up its map classes only once they're imported.
      window.naraHemDemoGoogle = () => {
        const maps = window.google.maps;
        Promise.all([maps.importLibrary('maps'), maps.importLibrary('marker')])
          .then(() => resolve(maps))
          .catch(reject);
      };
      // A refused key shows up only after the map is made: go back to OpenStreetMap.
      window.gm_authFailure = () => {
        googleFailed = true;
        if (map?.google) show('map');
      };
      const script = document.createElement('script');
      script.src =
        'https://maps.googleapis.com/maps/api/js?' +
        new URLSearchParams({
          key: GOOGLE_KEY,
          loading: 'async',
          callback: 'naraHemDemoGoogle',
          v: 'quarterly',
        });
      script.async = true;
      script.onerror = () => {
        googleFailed = true;
        reject(new Error('Google Maps could not load'));
      };
      document.head.append(script);
    });
    return googleLoad;
  }

  /**
   * Makes a map in holder: Google Maps when the site has a key, otherwise OpenStreetMap. Returns
   * the same small interface either way: circle, person, onClick, fit, line, dot and remove.
   */
  async function demoMap(holder) {
    try {
      return googleMap(await loadGoogle(), holder);
    } catch {
      return leafletMap(holder);
    }
  }

  /** The OpenStreetMap (Leaflet) version of the demo map. */
  function leafletMap(holder) {
    const leaflet = L.map(holder, { scrollWheelZoom: false });
    tiles(leaflet);
    return {
      google: false,
      circle(place) {
        L.circle([place.lat, place.lon], { radius: place.radius, color: MINT })
          .addTo(leaflet)
          .bindPopup(place.name);
      },
      person(start, icon) {
        const marker = L.marker(start, {
          icon: L.divIcon({
            html: icon,
            className: 'person-marker',
            iconSize: [96, 70],
            iconAnchor: [48, 52],
          }),
        }).addTo(leaflet);
        return {
          move: (point) => marker.setLatLng(point),
          position: () => [marker.getLatLng().lat, marker.getLatLng().lng],
        };
      },
      onClick: (handler) => leaflet.on('click', handler),
      fit(points) {
        leaflet.invalidateSize();
        leaflet.fitBounds(L.latLngBounds(points), { padding: [40, 40] });
      },
      line(path, color, weight, opacity = 1) {
        L.polyline(path, { color, weight, opacity }).addTo(leaflet);
      },
      dot(point, fill, label) {
        L.circleMarker(point, {
          radius: 7,
          color: '#0f1720',
          weight: 2,
          fillColor: fill,
          fillOpacity: 1,
        })
          .addTo(leaflet)
          .bindTooltip(label);
      },
      remove: () => leaflet.remove(),
    };
  }

  /** The Google Maps version of the demo map, styled like the real web app. */
  function googleMap(maps, holder) {
    holder.replaceChildren();
    const gmap = new maps.Map(holder, {
      center: { lat: 0, lng: 0 },
      zoom: 2,
      gestureHandling: 'cooperative',
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: false,
      styles: SITE.google_styles || [],
      backgroundColor: '#1f2a36',
    });
    const info = new maps.InfoWindow();
    const overlays = [];
    return {
      google: true,
      circle(place) {
        const circle = new maps.Circle({
          map: gmap,
          center: { lat: place.lat, lng: place.lon },
          radius: place.radius,
          strokeColor: MINT,
          strokeWeight: 3,
          fillColor: MINT,
          fillOpacity: 0.12,
        });
        circle.addListener('click', () => {
          info.setContent(place.name);
          info.setPosition(circle.getCenter());
          info.open(gmap);
        });
      },
      person(start, icon) {
        let at = new maps.LatLng(start[0], start[1]);
        const wrapper = document.createElement('div');
        wrapper.className = 'person-marker';
        wrapper.style.cssText =
          'position:absolute;z-index:10;width:96px;height:70px;transform:translate(-48px,-52px)';
        wrapper.append(icon);
        /** Keeps the member's photo at their position on the map. */
        class Person extends maps.OverlayView {
          onAdd() {
            this.getPanes().overlayMouseTarget.append(wrapper);
            maps.OverlayView.preventMapHitsAndGesturesFrom(wrapper);
          }

          draw() {
            const pixel = this.getProjection()?.fromLatLngToDivPixel(at);
            if (pixel) {
              wrapper.style.left = `${pixel.x}px`;
              wrapper.style.top = `${pixel.y}px`;
            }
          }

          onRemove() {
            wrapper.remove();
          }
        }
        const overlay = new Person();
        overlay.setMap(gmap);
        overlays.push(overlay);
        return {
          move(point) {
            at = new maps.LatLng(point[0], point[1]);
            overlay.draw();
          },
          position: () => [at.lat(), at.lng()],
        };
      },
      onClick: (handler) => gmap.addListener('click', handler),
      fit(points) {
        const bounds = new maps.LatLngBounds();
        for (const [lat, lng] of points) bounds.extend({ lat, lng });
        gmap.fitBounds(bounds, 40);
      },
      line(path, color, weight, opacity = 1) {
        new maps.Polyline({
          map: gmap,
          path: path.map(([lat, lng]) => ({ lat, lng })),
          strokeColor: color,
          strokeWeight: weight,
          strokeOpacity: opacity,
        });
      },
      dot(point, fill, label) {
        new maps.Marker({
          map: gmap,
          position: { lat: point[0], lng: point[1] },
          title: label,
          icon: {
            path: maps.SymbolPath.CIRCLE,
            scale: 7,
            fillColor: fill,
            fillOpacity: 1,
            strokeColor: '#0f1720',
            strokeWeight: 2,
          },
        });
      },
      remove() {
        for (const overlay of overlays) overlay.setMap(null);
        maps.event.clearInstanceListeners(gmap);
      },
    };
  }

  // Google pictures for the trip and place cards (Maps Static API), drawn the way the web app
  // draws its thumbnails. The recorded OpenStreetMap pictures stay if Google refuses.
  const TILE = 256;

  /** A point's pixel position on the Web Mercator world map at a zoom. */
  function mercator(lat, lon, zoom) {
    const size = TILE * 2 ** zoom;
    const sin = Math.sin((lat * Math.PI) / 180);
    return [
      ((lon + 180) / 360) * size,
      (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * size,
    ];
  }

  /** The latitude and longitude of a pixel position. */
  function unproject(x, y, zoom) {
    const size = TILE * 2 ** zoom;
    return [
      (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / size))) * 180) / Math.PI,
      (x / size) * 360 - 180,
    ];
  }

  /** The highest zoom, and its top-left pixel, where every point fits in width by height. */
  function frameView(points, width, height, pad) {
    for (let zoom = 17; zoom >= 1; zoom--) {
      const px = points.map((p) => mercator(p[0], p[1], zoom));
      const xs = px.map((p) => p[0]);
      const ys = px.map((p) => p[1]);
      const fits =
        Math.max(...xs) - Math.min(...xs) <= width - 2 * pad &&
        Math.max(...ys) - Math.min(...ys) <= height - 2 * pad;
      if (fits || zoom === 1) {
        return {
          zoom,
          width,
          height,
          left: Math.round((Math.min(...xs) + Math.max(...xs)) / 2 - width / 2),
          top: Math.round((Math.min(...ys) + Math.max(...ys)) / 2 - height / 2),
        };
      }
    }
    return null;
  }

  /** A Static Maps address for a view, in the web app's dark style, with optional paths. */
  function staticUrl(view, paths = []) {
    const [lat, lon] = unproject(view.left + view.width / 2, view.top + view.height / 2, view.zoom);
    const params = new URLSearchParams({
      center: lat.toFixed(6) + ',' + lon.toFixed(6),
      zoom: String(view.zoom),
      size: view.width + 'x' + view.height,
      scale: '2',
      key: GOOGLE_KEY,
    });
    for (const rule of SITE.google_styles || []) {
      const style = [
        rule.featureType && 'feature:' + rule.featureType,
        rule.elementType && 'element:' + rule.elementType,
        ...rule.stylers.map((s) =>
          s.color ? 'color:0x' + s.color.slice(1) : 'visibility:' + s.visibility,
        ),
      ];
      params.append('style', style.filter(Boolean).join('|'));
    }
    for (const path of paths) params.append('path', path);
    return 'https://maps.googleapis.com/maps/api/staticmap?' + params;
  }

  /** Loads a Google picture and hands it over once it has loaded; nothing changes otherwise. */
  function googlePicture(url, onLoad) {
    const picture = new Image();
    picture.alt = '';
    picture.referrerPolicy = 'origin';
    picture.onload = () => onLoad(picture);
    picture.src = url;
  }

  /** Redraws a trip card's map with Google behind the recorded route. */
  function googleTripThumbnail(card, trip) {
    const target = card.querySelector('.trip-route-thumbnail');
    const old = target?.querySelector('svg');
    if (!GOOGLE_KEY || googleFailed || !old || trip.path.length < 2) return;
    const [, , fullWidth, fullHeight] = (old.getAttribute('viewBox') || '').split(' ').map(Number);
    if (!fullWidth || !fullHeight) return;
    const width = Math.min(640, fullWidth);
    const height = Math.round((fullHeight * width) / fullWidth);
    const view = frameView(trip.path, width, height, 18);
    if (!view) return;
    googlePicture(staticUrl(view), (picture) => {
      if (!target.isConnected) return;
      picture.className = 'trip-tiles';
      const svg = old.cloneNode(false);
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      const points = trip.path
        .map((p) => mercator(p[0], p[1], view.zoom))
        .map(([x, y]) => [x - view.left, y - view.top]);
      const text = points.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
      const casing = old.querySelector('path')?.cloneNode(false);
      const line = old.querySelector('polyline')?.cloneNode(false);
      casing?.setAttribute('d', 'M' + text.replaceAll(' ', ' L'));
      line?.setAttribute('points', text);
      const dots = [...old.querySelectorAll('circle')].map((dot, index) => {
        const copy = dot.cloneNode(false);
        const [x, y] = index ? points.at(-1) : points[0];
        copy.setAttribute('cx', x.toFixed(1));
        copy.setAttribute('cy', y.toFixed(1));
        return copy;
      });
      svg.append(...[casing, line, ...dots].filter(Boolean));
      target.replaceChildren(picture, svg);
    });
  }

  /** Redraws each place card's picture with Google and the place's circle. */
  function googlePlaceThumbnails() {
    if (!GOOGLE_KEY || googleFailed) return;
    for (const card of app.querySelectorAll('.place-card')) {
      const holder = card.querySelector('.place-card-photo');
      const name = card.querySelector('.place-card-details strong')?.textContent;
      const place = D.places.find((p) => p.name === name);
      if (!holder || !place) continue;
      const width = Math.min(640, Math.round(holder.clientWidth || 180));
      const height = Math.min(640, Math.round(holder.clientHeight || 98));
      const delta = Math.max((place.radius * 2.5) / 111320, 0.00065);
      const across = delta / Math.max(0.2, Math.cos((place.lat * Math.PI) / 180));
      const corners = [
        [place.lat - delta, place.lon - across],
        [place.lat + delta, place.lon + across],
      ];
      const view = frameView(corners, width, height, 8);
      if (!view) continue;
      const ring = [];
      for (let i = 0; i <= 36; i++) {
        const angle = (i * Math.PI) / 18;
        ring.push(
          (place.lat + (place.radius / 111320) * Math.sin(angle)).toFixed(6) +
            ',' +
            (
              place.lon +
              ((place.radius / 111320) * Math.cos(angle)) / Math.cos((place.lat * Math.PI) / 180)
            ).toFixed(6),
        );
      }
      const circle = 'color:0xa5f0bcff|weight:2|fillcolor:0xa5f0bc33|' + ring.join('|');
      googlePicture(staticUrl(view, [circle]), (picture) => {
        if (!holder.isConnected) return;
        picture.style.cssText = 'width:100%;height:100%;object-fit:cover;display:block';
        holder.replaceChildren(picture);
      });
    }
  }

  /** Shows the household map with members' photos and two members driving. */
  async function liveMap() {
    const old = app.querySelector('#household-map');
    const people = [];
    if (!old) return;
    const holder = document.createElement('div');
    holder.id = 'household-map';
    holder.setAttribute('aria-label', 'Household location map');
    old.replaceWith(holder);
    app.querySelector('#load-tiles')?.setAttribute('hidden', '');
    const shown = await demoMap(holder);
    // Another screen may have opened while Google Maps was loading.
    if (!holder.isConnected) {
      shown.remove();
      return;
    }
    map = shown;
    mapProvider(map.google);
    for (const place of D.places) map.circle(place);
    for (const html of S.map.markers) {
      const icon = element(html);
      const name = icon.dataset.memberName;
      const live = D.live.find((l) => l.member === name);
      const parked = D.parked[name];
      const start = live ? live.path[0] : places[parked];
      if (!start) continue;
      icon.classList.remove('is-open');
      const lines = [...icon.querySelectorAll('.member-map-popup p')];
      lines.slice(1).forEach((line) => line.remove());
      const tip = lines[0];
      const marker = map.person(start, icon);
      icon.addEventListener('click', (event) => {
        event.stopPropagation();
        const open = !icon.classList.contains('is-open');
        for (const other of people) other.icon.classList.remove('is-open');
        icon.classList.toggle('is-open', open);
        member = open ? name : null;
        tell(open ? 'member' : 'map', open ? { member: name } : {});
      });
      people.push({ name, icon, tip, marker, live, parked });
    }
    map.onClick(() => {
      for (const p of people) p.icon.classList.remove('is-open');
      if (member) {
        member = null;
        tell('map');
      }
    });
    const everyone = () =>
      map.fit([...people.map((p) => p.marker.position()), ...D.places.map((p) => [p.lat, p.lon])]);
    everyone();
    const status = app.querySelector('#map-status');
    const began = Date.now();
    const drive = 60;
    const rest = 15;
    const tick = () => {
      const elapsed = ((Date.now() - began) / 1000) % (drive + rest);
      for (const person of people) {
        if (!person.live) {
          if (person.tip) {
            const fourMinutesAgo = new Date(Date.now() - 4 * 60000);
            person.tip.textContent = `At ${person.parked} · last update ${clock(fourMinutesAgo)}`;
          }
          continue;
        }
        const fraction = Math.min(1, elapsed / drive);
        person.marker.move(along(person.live.path, fraction));
        const mph = Math.round(24 + 6 * Math.sin(elapsed / 4 + person.name.length));
        if (person.tip) {
          person.tip.textContent =
            fraction < 1
              ? `Driving · ${mph} mph · last update ${clock(new Date())}`
              : `At ${person.live.destination} · last update ${clock(new Date())}`;
        }
      }
      if (status) {
        const refreshed = clock(new Date(), true);
        status.textContent = `${people.length} shared locations · refreshed ${refreshed}`;
      }
    };
    tick();
    ticker = setInterval(tick, 1000);
    app.querySelector('#fit-users')?.addEventListener('click', (event) => {
      event.stopImmediatePropagation();
      everyone();
    });
    app.querySelector('#refresh-map')?.addEventListener('click', (event) => {
      event.stopImmediatePropagation();
      tick();
      say('Up to date. In the real app, new locations also arrive on their own.');
    });
  }

  /** Names the map that's actually showing in the privacy note under it. */
  function mapProvider(google) {
    for (const slot of app.querySelectorAll('[data-slot="provider-name"]')) {
      slot.textContent = google ? 'Google' : 'OpenStreetMap';
    }
  }

  /**
   * Makes Manage household's location lines match the map: the two driving members are driving
   * now, and everyone else was last seen where the map shows them, four minutes ago.
   */
  function householdLocations() {
    for (const line of app.querySelectorAll('.member-location')) {
      const name = line.closest('.member-info')?.querySelector('h3')?.textContent;
      if (D.live.some((l) => l.member === name)) {
        line.textContent = `Driving · ${new Date().toLocaleString('en-US')}`;
      } else if (D.parked[name]) {
        const seen = new Date(Date.now() - 4 * 60000).toLocaleString('en-US');
        line.textContent = `${D.parked[name]} · ${seen}`;
      }
    }
  }

  /** Shows the recorded trip cards for a member. */
  function trips(selected) {
    const form = app.querySelector('#trip-filters');
    const select = form?.querySelector('select[name=member]');
    if (select && selected) {
      for (const option of select.options) option.selected = option.textContent === selected;
    }
    const chosen = select ? select.options[select.selectedIndex]?.textContent : selected;
    form?.addEventListener('submit', (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      show('trips', { member: select.options[select.selectedIndex].textContent });
    });
    select?.addEventListener('change', () =>
      show('trips', { member: select.options[select.selectedIndex].textContent }),
    );
    for (const card of app.querySelectorAll('.timeline-card')) {
      const button = [...card.querySelectorAll('button')].find(
        (b) => b.textContent.trim() === 'Open trip',
      );
      const title = card.querySelector('h3')?.textContent || '';
      const [origin, destination] = title.split(' → ');
      const trip = D.trips.find(
        (t) => t.member === chosen && t.origin === origin && t.destination === destination,
      );
      if (!button || !trip) continue;
      googleTripThumbnail(card, trip);
      button.addEventListener('click', (event) => {
        event.stopImmediatePropagation();
        openTrip(card, trip, title);
      });
    }
  }

  /** Opens the trip dialog with the route on a map. */
  function openTrip(card, trip, title) {
    const dialog = document.createElement('dialog');
    let route = null;
    dialog.className = 'trip-dialog';
    const close = document.createElement('button');
    close.textContent = 'Close';
    const heading = document.createElement('h3');
    heading.textContent = title;
    const large = document.createElement('div');
    large.className = 'trip-map trip-map-large';
    const facts = document.createElement('p');
    const time = card.querySelector('p')?.textContent || '';
    const stats = [...card.querySelectorAll('.trip-stats span')].map((s) => s.textContent);
    facts.textContent = [time, stats[0], stats[2]].filter(Boolean).join(' · ');
    const note = document.createElement('p');
    note.textContent = 'Recorded path; gaps are not connected.';
    dialog.append(close, heading, large, facts, note);
    app.querySelector('#view').append(dialog);
    dialog.showModal();
    demoMap(large).then((made) => {
      route = made;
      if (!dialog.open) {
        route.remove();
        return;
      }
      route.line(trip.path, '#0f1720', 8, 0.9);
      route.line(trip.path, '#a3e9bc', 5);
      route.dot(trip.path[0], '#7fb4ee', trip.origin);
      route.dot(trip.path[trip.path.length - 1], '#e5b677', trip.destination);
      setTimeout(() => route.fit(trip.path), 50);
    });
    const done = () => {
      route?.remove();
      dialog.remove();
      tell('trips', { member: trip.member });
    };
    close.addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', done);
    tell('trip', { member: trip.member, title });
  }

  app.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (
      !button ||
      button.closest('.trip-dialog') ||
      button.closest('.leaflet-container') ||
      button.closest('#household-map, .trip-map') ||
      button.closest('#trip-filters')
    ) {
      return;
    }
    if (NAV[button.id]) {
      event.preventDefault();
      show(NAV[button.id]);
      return;
    }
    if (button.dataset.href) {
      event.preventDefault();
      if (button.dataset.external === undefined) location.href = button.dataset.href;
      else window.open(button.dataset.href, '_blank', 'noopener');
      return;
    }
    if (button.closest('summary')) return;
    event.preventDefault();
    say('This is a demo with a made-up family, so nothing is saved.');
  });
  app.addEventListener('submit', (event) => {
    event.preventDefault();
    say('This is a demo with a made-up family, so nothing is saved.');
  });
  window.addEventListener('message', (event) => {
    if (event.data?.source === 'narahem-site' && SCREENS[event.data.view]) show(event.data.view);
  });
  const start = location.hash.slice(1);
  show(SCREENS[start] ? start : 'map');
  window.addEventListener('hashchange', () => {
    const screen = location.hash.slice(1);
    if (SCREENS[screen]) show(screen);
  });
})();
