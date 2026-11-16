// Films the showcase household in a real browser. Driven by run.py.
//   node record.cjs bootstrap   sign in and trust this browser as the first device
//   node record.cjs tour        sign in again and film a tour of the app
const path = require('node:path');
const fs = require('node:fs');

const { chromium } = require(
  path.join(__dirname, '../../apps/webapp/frontend/node_modules/playwright'),
);

const env = process.env;
const viewport = { width: 1280, height: 800 };

/** Waits ms milliseconds. */
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Launches the browser for recording in the showcase family's time zone. */
async function open(video) {
  // The showcase family lives in Portland, so the app shows Portland times.
  const options = {
    viewport,
    deviceScaleFactor: 1,
    timezoneId: 'America/Los_Angeles',
    locale: 'en-US',
  };
  if (env.SHOWCASE_BROWSER) options.executablePath = env.SHOWCASE_BROWSER;
  if (video) options.recordVideo = { dir: env.SHOWCASE_OUTPUT, size: viewport };
  const context = await chromium.launchPersistentContext(env.SHOWCASE_PROFILE, options);
  if (env.SHOWCASE_OFFLINE_TILES) {
    // Development without internet access: plain tiles instead of OpenStreetMap.
    const tile = fs.readFileSync(env.SHOWCASE_OFFLINE_TILES);
    await context.route('https://tile.openstreetmap.org/**', (route) =>
      route.fulfill({
        contentType: 'image/png',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: tile,
      }),
    );
  }
  const page = context.pages()[0] || (await context.newPage());
  const tiles = { loaded: 0, failed: 0 };
  page.on('response', (response) => {
    if (new URL(response.url()).hostname === 'tile.openstreetmap.org') {
      tiles[response.ok() ? 'loaded' : 'failed']++;
    }
  });
  page.on('requestfailed', (request) => {
    if (new URL(request.url()).hostname === 'tile.openstreetmap.org') tiles.failed++;
  });
  return { context, page, tiles };
}

/** Signs in as the showcase admin. */
async function signIn(page, slow) {
  await page.goto(env.SHOWCASE_ORIGIN);
  await page.getByRole('heading', { name: 'Welcome home.' }).waitFor();
  await page
    .locator('#login [name=email]')
    .pressSequentially(env.SHOWCASE_EMAIL, { delay: slow ? 45 : 0 });
  await page
    .locator('#login [name=password]')
    .pressSequentially(env.SHOWCASE_PASSWORD, { delay: slow ? 30 : 0 });
  if (slow) await pause(400);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
}

/** Sets up the admin's browser keys before recording. */
async function bootstrap() {
  const { context, page } = await open(false);
  await signIn(page, false);
  await page.getByLabel('Device bootstrap token', { exact: true }).fill(env.SHOWCASE_DEVICE_TOKEN);
  await page.getByRole('button', { name: 'Trust this first device', exact: true }).click();
  await page.getByRole('heading', { name: 'Household map', exact: true }).waitFor();
  // The trusted browser signs the phone-enrollment service into the roster on load.
  await pause(3000);
  // Sign out so the filmed tour starts at the sign-in page; the trusted keys stay.
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByRole('heading', { name: 'Welcome home.' }).waitFor();
  await context.close();
}

/** Records the app tour and saves screenshots and screen snapshots for the site. */
async function tour() {
  const { context, page, tiles } = await open(true);
  // Chapter marks (seconds into the video) let the site cut one short clip per feature.
  const start = Date.now();
  const chapters = [];
  const now = () => (Date.now() - start) / 1000;
  const mark = (name) => {
    if (chapters.length) chapters.at(-1).end = now();
    if (name) chapters.push({ name, start: now() });
  };
  const still = (name) => page.screenshot({ path: path.join(env.SHOWCASE_OUTPUT, `${name}.png`) });
  // The rendered app, screen by screen, for the interactive demo on the site (site/demo).
  const snapshots = {};
  const snapshot = async (name) => {
    snapshots[name] = await page.evaluate(async () => {
      // Trip-card map backgrounds are blob: URLs that die with the page; keep their pixels.
      // The page revokes those URLs once drawn, so copy the pixels already on screen.
      for (const image of document.querySelectorAll('#view img[src^="blob:"]')) {
        if (!image.complete || !image.naturalWidth) continue;
        const canvas = document.createElement('canvas');
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        try {
          canvas.getContext('2d').drawImage(image, 0, 0);
          image.src = canvas.toDataURL('image/jpeg', 0.85);
        } catch {
          /* leave it; the card still shows its route */
        }
      }
      return {
        header: document.querySelector('main > header').outerHTML,
        nav: document.querySelector('#app-nav').outerHTML,
        view: document.querySelector('#view').innerHTML,
        markers: [...document.querySelectorAll('.person-marker .map-person')].map(
          (m) => m.outerHTML,
        ),
      };
    });
  };
  // Every member's trip list, as the Trips page shows it when that member is chosen.
  // Trips load a day at a time; earlier days arrive as the list scrolls.
  const openTrip = () => page.getByRole('button', { name: 'Open trip', exact: true });
  const loadTrips = async () => {
    for (let i = 0; i < 12 && !(await openTrip().count()); i++) {
      await page.mouse.wheel(0, 1500);
      await pause(700);
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    return (await openTrip().count()) > 0;
  };
  const tripLists = async () => {
    const lists = {};
    const members = await page
      .locator('#trip-filters select[name=member] option')
      .evaluateAll((options) => options.map((option) => [option.value, option.textContent]));
    for (const [value, name] of members) {
      await page.locator('#trip-filters select[name=member]').selectOption(value);
      await page.locator('#trip-filters button[type=submit]').click();
      await pause(2500);
      await loadTrips();
      await snapshot('trips');
      lists[name] = snapshots.trips.view;
    }
    snapshots.tripsByMember = lists;
  };
  await signIn(page, true);
  await page.getByRole('heading', { name: 'Household map', exact: true }).waitFor();
  mark('map');
  await pause(5000);
  await still('map');
  await snapshot('map');
  await pause(7000);
  for (const [tab, name, heading, wait] of [
    ['Trips', 'trips', null, 8000],
    ['Places', 'places', null, 6000],
    ['Household map', 'live', 'Household map', 14000],
  ]) {
    await page.getByRole('button', { name: tab, exact: true }).click();
    if (heading) await page.getByRole('heading', { name: heading, exact: true }).waitFor();
    if (name === 'trips') await loadTrips();
    mark(name);
    await pause(wait / 2);
    await still(name);
    await snapshot(name);
    await page.mouse.wheel(0, 500);
    await pause(wait / 2);
    await page.mouse.wheel(0, -1000);
    if (name === 'trips' && (await openTrip().count())) {
      // The full route of one trip, as the family member drove it.
      await openTrip().first().click();
      mark('trip');
      await pause(6000);
      await still('trip');
      await page.getByRole('button', { name: 'Close', exact: true }).click();
    }
  }
  mark(null);
  await page.getByRole('button', { name: 'Trips', exact: true }).click();
  await pause(2000);
  await tripLists();
  for (const [tab, name] of [
    ['Manage household', 'household'],
    ['Admin settings', 'settings'],
  ]) {
    await page.getByRole('button', { name: tab, exact: true }).click();
    await pause(4000);
    await snapshot(name);
  }
  // How this browser wrote today's date, so the demo can show the visitor's today instead.
  snapshots.recorded = await page.evaluate(() => ({
    at: Date.now(),
    origin: location.origin,
    short: new Date().toLocaleDateString(),
    long: new Date().toLocaleDateString(undefined, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    }),
  }));
  fs.writeFileSync(path.join(env.SHOWCASE_OUTPUT, 'snapshots.json'), JSON.stringify(snapshots));
  const video = page.video();
  await context.close();
  fs.renameSync(await video.path(), path.join(env.SHOWCASE_OUTPUT, 'web-tour.webm'));
  fs.writeFileSync(
    path.join(env.SHOWCASE_OUTPUT, 'chapters.json'),
    JSON.stringify(chapters, null, 2),
  );
  fs.writeFileSync(
    path.join(env.SHOWCASE_OUTPUT, 'tiles.txt'),
    `loaded ${tiles.loaded}, failed ${tiles.failed}`,
  );
}

({ bootstrap, tour })[process.argv[2]]().catch((error) => {
  console.error(error);
  process.exit(1);
});
