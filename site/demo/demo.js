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
  const places = Object.fromEntries(D.places.map((p) => [p.name, [p.lat, p.lon]]));
  let map = null;
  let ticker = null;
  let member = null;

  const timeFormat = { hour: 'numeric', minute: '2-digit' };
  /** A time of day, the way the app shows it. */
  const clock = (date, seconds) =>
    date.toLocaleTimeString('en-US', seconds ? { ...timeFormat, second: '2-digit' } : timeFormat);

  /** Replaces the recording date in captured screens with today's date. */
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
          const then = new Date(S.recorded.at);
          then.setHours((Number(h) % 12) + (half === 'PM' ? 12 : 0), Number(m), Number(s || 0));
          return clock(new Date(then.getTime() + shift), s !== undefined);
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
          <div class="links">${linkButton('Join the beta on TestFlight', SITE.testflight)}</div>
          <p class="subtle">Needs iOS 17 or later. Install Apple's TestFlight app first, then
          open the invitation link on the iPhone.</p>
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
          <div class="links">${linkButton('Download the Android app', SITE.android)}</div>
          <p class="subtle">Needs Android 8.0 or later. Open the download on the phone and allow
          your browser to install apps when Android asks.</p>
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
      'Join the public TestFlight beta, then sign in with the server address and account ' +
        'from your invitation.',
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
    const body = EXTRA[screen]
      ? EXTRA[screen]()
      : screen === 'trips' && options.member && S.tripsByMember?.[options.member]
        ? today(S.tripsByMember[options.member])
        : today(snap.view);
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
    if (screen === 'map') liveMap();
    if (screen === 'trips') trips(options.member);
    if (screen === 'places') {
      const status = app.querySelector('#map-status');
      if (status) status.textContent = '';
    }
    tell(screen, options.member ? { member: options.member } : {});
    app.scrollTop = 0;
    window.scrollTo(0, 0);
  }

  /** Puts the site's GitHub and Install buttons where Sign out is, and adds the extra tabs. */
  function siteHeader() {
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
    const nav = app.querySelector('#app-nav');
    if (!nav || nav.querySelector('#open-ios')) return;
    nav.insertAdjacentHTML(
      'beforeend',
      '<button id="open-ios" class="secondary">iPhone</button>' +
        '<button id="open-android" class="secondary">Android</button>' +
        '<button id="open-alexa" class="secondary">Alexa</button>',
    );
  }

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

  /** Shows the household map with members' photos and two members driving. */
  function liveMap() {
    const old = app.querySelector('#household-map');
    const people = [];
    if (!old) return;
    const holder = document.createElement('div');
    holder.id = 'household-map';
    holder.setAttribute('aria-label', 'Household location map');
    old.replaceWith(holder);
    app.querySelector('#load-tiles')?.setAttribute('hidden', '');
    map = L.map(holder, { scrollWheelZoom: false });
    tiles(map);
    for (const place of D.places) {
      L.circle([place.lat, place.lon], { radius: place.radius, color: MINT })
        .addTo(map)
        .bindPopup(place.name);
    }
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
      const marker = L.marker(start, {
        icon: L.divIcon({
          html: icon,
          className: 'person-marker',
          iconSize: [96, 70],
          iconAnchor: [48, 52],
        }),
      }).addTo(map);
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
    map.on('click', () => {
      for (const p of people) p.icon.classList.remove('is-open');
      if (member) {
        member = null;
        tell('map');
      }
    });
    const everyone = () =>
      map.fitBounds(
        L.latLngBounds([
          ...people.map((p) => p.marker.getLatLng()),
          ...D.places.map((p) => [p.lat, p.lon]),
        ]),
        { padding: [40, 40] },
      );
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
        person.marker.setLatLng(along(person.live.path, fraction));
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
      button.addEventListener('click', (event) => {
        event.stopImmediatePropagation();
        openTrip(card, trip, title);
      });
    }
  }

  /** Opens the trip dialog with the route on a map. */
  function openTrip(card, trip, title) {
    const dialog = document.createElement('dialog');
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
    const route = L.map(large, { scrollWheelZoom: false });
    tiles(route);
    L.polyline(trip.path, { color: '#0f1720', weight: 8, opacity: 0.9 }).addTo(route);
    const line = L.polyline(trip.path, { color: '#a3e9bc', weight: 5 }).addTo(route);
    L.circleMarker(trip.path[0], {
      radius: 7,
      color: '#0f1720',
      weight: 2,
      fillColor: '#7fb4ee',
      fillOpacity: 1,
    })
      .addTo(route)
      .bindTooltip(trip.origin);
    L.circleMarker(trip.path[trip.path.length - 1], {
      radius: 7,
      color: '#0f1720',
      weight: 2,
      fillColor: '#e5b677',
      fillOpacity: 1,
    })
      .addTo(route)
      .bindTooltip(trip.destination);
    setTimeout(() => {
      route.invalidateSize();
      route.fitBounds(line.getBounds(), { padding: [30, 30] });
    }, 50);
    const done = () => {
      route.remove();
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
