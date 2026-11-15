// Synthetic setup/login checks. No email is sent and no production data is used.
/* global testGoogleMaps, MapRegression -- defined in the page by the Maps stub and map bundle. */
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');

// The server and its Python fixtures run from the backend folder.
const BACKEND = path.resolve(__dirname, '../../../backend');

(async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'narahem-browser-'));
  const socket = net.createServer();
  await new Promise((resolve) => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise((resolve) => socket.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  // The server's own log and requests, shown only if the test fails.
  const serverLog = path.join(directory, 'server.log');
  const logFile = require('node:fs').openSync(serverLog, 'w');
  const server = spawn(
    process.env.NARAHEM_TEST_PYTHON || 'python3',
    [
      '-m',
      'uvicorn',
      'narahem.app:create_app',
      '--factory',
      '--host',
      '127.0.0.1',
      '--port',
      String(port),
      '--no-proxy-headers',
    ],
    {
      cwd: BACKEND,
      env: {
        ...process.env,
        DATABASE_URL: `sqlite:///${directory}/test.db`,
        NARAHEM_DATA_DIR: directory,
        NARAHEM_PUBLIC_URL: origin,
        NARAHEM_ALLOW_HTTP: '1',
        NARAHEM_ALERT_ADDRESSES: '0',
        NARAHEM_GOOGLE_MAPS_API_KEY:
          process.env.NARAHEM_TEST_MAP_PROVIDER === 'google' ? 'synthetic-browser-key' : '',
      },
      stdio: ['ignore', logFile, logFile],
    },
  );
  let browser;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      if (server.exitCode !== null) throw new Error('Synthetic web server exited');
      try {
        ready = (await fetch(`${origin}/healthz`)).ok;
      } catch {
        // Not listening yet; try again shortly.
      }
      if (ready) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.ok(ready, 'Synthetic web server ready');
    browser = await chromium.launch(
      process.env.NARAHEM_TEST_BROWSER_EXECUTABLE
        ? { executablePath: process.env.NARAHEM_TEST_BROWSER_EXECUTABLE, args: ['--no-sandbox'] }
        : {},
    );
    const page = await browser.newPage({ viewport: { width: 1100, height: 950 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.context().route('https://tile.openstreetmap.org/**', (route) =>
      route.fulfill({
        contentType: 'image/png',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: Buffer.from(
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a6ioAAAAASUVORK5CYII=',
          'base64',
        ),
      }),
    );
    await page.context().route('https://maps.googleapis.com/maps/api/staticmap?**', (route) =>
      route.fulfill({
        contentType: 'image/png',
        body: Buffer.from(
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a6ioAAAAASUVORK5CYII=',
          'base64',
        ),
      }),
    );
    await page.context().route('https://maps.googleapis.com/maps/api/js?**', async (route) =>
      route.fulfill({
        contentType: 'text/javascript',
        body: await fs.readFile(path.join(__dirname, 'google-maps-stub.js'), 'utf8'),
      }),
    );
    await page.goto(origin);
    await page.getByRole('heading', { name: 'Make this server yours.' }).waitFor();
    await page.waitForFunction(
      () => getComputedStyle(document.documentElement).backgroundColor === 'rgb(6, 20, 58)',
    );
    assert.equal(
      await page.locator('header').evaluate((e) => getComputedStyle(e).display),
      'flex',
      'Main stylesheet must load and apply',
    );
    await page
      .getByLabel('Setup token', { exact: true })
      .fill((await fs.readFile(path.join(directory, 'bootstrap-token'), 'utf8')).trim());
    await page.getByLabel('Household name', { exact: true }).fill('Synthetic Household');
    await page.getByLabel('Administrator email', { exact: true }).fill('owner@example.invalid');
    await page
      .getByLabel('Administrator password · at least 15 characters', { exact: true })
      .fill('synthetic long test password');
    await page
      .getByLabel('Confirm administrator password', { exact: true })
      .fill('synthetic long test password');
    await page
      .getByRole('button', {
        name: 'Show Administrator password · at least 15 characters',
        exact: true,
      })
      .click();
    assert.equal(await page.locator('#setup [name=password]').getAttribute('type'), 'text');
    await page
      .getByRole('button', {
        name: 'Hide Administrator password · at least 15 characters',
        exact: true,
      })
      .click();
    assert.equal(await page.locator('#setup [name=password]').getAttribute('type'), 'password');
    await page.route('**/api/setup', async (route) => {
      if (route.request().method() !== 'POST') return route.continue();
      await route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: 'Please correct the highlighted fields.',
          fields: [{ field: 'token', message: 'Use at least 20 characters.' }],
        }),
      });
    });
    await page.getByRole('button', { name: 'Create household', exact: true }).click();
    await page
      .locator('#setup-token-error')
      .getByText('Use at least 20 characters.', { exact: true })
      .waitFor();
    assert.equal(await page.locator('#setup [name=token]').getAttribute('aria-invalid'), 'true');
    await page.unroute('**/api/setup');
    await page.getByRole('button', { name: 'Create household', exact: true }).click();
    await page.getByRole('heading', { name: 'Welcome home.' }).waitFor();
    await assert.rejects(fs.access(path.join(directory, 'bootstrap-token')));
    await page.locator('#login [name=email]').fill('owner@example.invalid');
    await page.locator('#login [name=password]').fill('synthetic long test password');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    const googleMode = process.env.NARAHEM_TEST_MAP_PROVIDER === 'google';
    const png = await page.evaluate(() => {
      const c = document.createElement('canvas');
      c.width = c.height = 2;
      c.getContext('2d').fillRect(0, 0, 2, 2);
      return c.toDataURL('image/png').split(',')[1];
    });
    async function providers(p) {
      await p.route('https://tile.openstreetmap.org/**', (route) =>
        route.fulfill({
          contentType: 'image/png',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: Buffer.from(png, 'base64'),
        }),
      );
      await p.route('https://maps.googleapis.com/maps/api/js?**', async (route) => {
        assert.equal(
          new URL(route.request().url()).searchParams.get('key'),
          'synthetic-browser-key',
        );
        await route.fulfill({
          contentType: 'text/javascript',
          body: await fs.readFile(path.join(__dirname, 'google-maps-stub.js'), 'utf8'),
        });
      });
    }
    await providers(page);
    // Sign-in already happened above; provider interception is also installed
    // on the browser context before its first sign-in (see initialization).
    await page.getByRole('heading', { name: 'Household map', exact: true }).waitFor();
    assert.equal(await page.locator('#mail').count(), 0, 'Map excludes email settings');
    assert.equal(await page.locator('#members').count(), 0, 'Map excludes member administration');
    await page.getByRole('button', { name: 'Admin settings', exact: true }).click();
    await page.getByRole('heading', { name: 'Admin settings', exact: true }).waitFor();
    await page.getByRole('heading', { name: 'Storage and retention', exact: true }).waitFor();
    assert.equal(await page.locator('#mail').isVisible(), false, 'Settings sections start closed');
    // Opened sections stay open when the page redraws after a save.
    for (const name of ['Email', 'Storage and retention']) {
      await page.locator('.settings-section > summary').filter({ hasText: name }).click();
    }
    assert.equal(await page.locator('#push-form, #test-push, #push-summary').count(), 0);
    assert.equal(await page.locator('#retention').count(), 1);
    assert.equal(
      await page
        .locator('#retention')
        .evaluate((el) => Boolean(el.closest('#admin-settings-grid'))),
      true,
      'Storage shares the responsive grid with Email',
    );
    const mail = page.locator('#mail');
    // A known address fills in the server details and shows that provider's steps.
    await mail.locator('[name=sender]').fill('owner@gmail.com');
    assert.equal(await mail.locator('[name=host]').inputValue(), 'smtp.gmail.com');
    assert.equal(await mail.locator('[name=username]').inputValue(), 'owner@gmail.com');
    await page.getByRole('link', { name: 'Open Google App passwords' }).waitFor();
    // Outlook.com cannot be used, so saving is turned off.
    await mail.locator('[name=sender]').fill('owner@hotmail.com');
    await page.getByText('Microsoft no longer lets apps send', { exact: false }).waitFor();
    assert.equal(await page.locator('#save-mail').isDisabled(), true);
    // Any other address opens the server details for manual entry.
    await mail.locator('[name=sender]').fill('owner@example.invalid');
    await mail.locator('[name=host]').fill('smtp.example.invalid');
    await mail.locator('[name=username]').fill('synthetic');
    await mail.locator('[name=password]').fill('synthetic-smtp-secret');
    await page.getByRole('button', { name: 'Save email settings', exact: true }).click();
    await page.getByText('Email settings saved. Send a test next.', { exact: true }).waitFor();
    assert.equal(await page.locator('#mail [name=password]').inputValue(), '');
    assert.equal(await page.locator('#members').count(), 0, 'Admin excludes member list');
    const fixture = (sql) =>
      spawnSync(
        process.env.NARAHEM_TEST_PYTHON || 'python3',
        [
          '-c',
          `from sqlalchemy import create_engine,text; import os; ` +
            `e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); ` +
            `c.execute(text(${JSON.stringify(sql)})); c.commit(); c.close()`,
        ],
        {
          cwd: BACKEND,
          env: { ...process.env, DATABASE_URL: `sqlite:///${directory}/test.db` },
          encoding: 'utf8',
        },
      );
    assert.equal(fixture('UPDATE accounts SET verified=true').status, 0);
    await page.reload();
    await page.getByRole('button', { name: 'Manage household', exact: true }).click();
    await page.getByRole('heading', { name: 'Manage household', exact: true }).waitFor();
    assert.equal(await page.locator('#mail').count(), 0, 'Household excludes SMTP');
    // The original setup token is retained for this browser session and
    // automatically establishes the administrator's first signed root.
    assert.equal(
      await page.getByRole('button', { name: 'Enable this browser', exact: true }).count(),
      0,
    );
    await page.locator('#root-code').waitFor({ state: 'attached' });
    const rootFingerprint = await page.locator('#root-code').textContent();
    assert.equal(rootFingerprint.length, 64);
    const adminDevice = page.locator('.device-row').filter({ has: page.locator('#root-code') });
    assert.match(
      await adminDevice.locator('h4').textContent(),
      /^Admin · approved$/,
      'Admin browser owns the root fingerprint display',
    );
    assert.equal(
      await page
        .locator(
          '#pause-sharing, #browser-gps, #delete-history, #location-form, #profile-form, ' +
            '#my-map-profile',
        )
        .count(),
      0,
      'Browser-only GPS, manual testing and map profile controls were removed',
    );
    assert.equal(
      await page.getByText('Advanced history and alerts', { exact: true }).count(),
      0,
      'Encrypted event history is only exposed through console diagnostics',
    );
    assert.equal(
      await page.locator('#saved-places').isVisible(),
      false,
      'Household management must not duplicate the Places editor',
    );
    await page.getByRole('button', { name: 'Places', exact: true }).click();
    await page.locator('#saved-places').waitFor({ state: 'visible' });
    const recordRequests = [];
    page.on('request', (request) => {
      if (request.url().endsWith('/api/records') && request.method() === 'POST') {
        recordRequests.push(request.postData());
      }
    });
    assert.equal(
      await page.locator('#place-form').isVisible(),
      false,
      'The add form starts closed',
    );
    await page.getByRole('button', { name: 'Add a place', exact: true }).click();
    await page.getByLabel('Place name', { exact: true }).fill('Synthetic Private Home');
    assert.equal(
      await page.locator('#place-preview').count(),
      1,
      'Saved Places has a live radius preview',
    );
    await page.route('https://nominatim.openstreetmap.org/search?**', (route) =>
      route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify([
          { display_name: 'Synthetic street address', lat: '12.3456789', lon: '-23.4567891' },
        ]),
      }),
    );
    await page
      .getByLabel('Find an address or landmark', { exact: true })
      .fill('Synthetic street address');
    await page.getByRole('button', { name: 'Find address', exact: true }).click();
    await page
      .getByText(/Found: (Synthetic street address|Synthetic address from Google Maps)/)
      .waitFor();
    assert.equal(await page.locator('#place-lat').inputValue(), '12.3456789');
    if (googleMode) {
      // Google can render a map while Geocoding API is disabled; the form must
      // show the error *inline*, offer a provider-specific fallback, and recover.
      await page.evaluate(() => {
        window.testGoogleMaps.geocodeMode = 'deny';
      });
      await page.getByRole('button', { name: 'Find address', exact: true }).click();
      await page
        .locator('#place-address-status')
        .filter({ hasText: /Google denied address lookup/ })
        .waitFor();
      assert.equal(
        await page.getByRole('button', { name: 'Find address', exact: true }).isEnabled(),
        true,
      );
      await page.getByRole('button', { name: 'Search with OpenStreetMap instead' }).click();
      await page
        .locator('#place-address-status')
        .filter({ hasText: /Found: Synthetic street address/ })
        .waitFor();
      // An unresolved geocoder Promise must not leave Searching Google forever.
      await page.evaluate(() => {
        window.testGoogleMaps.geocodeMode = 'hang';
      });
      await page.getByRole('button', { name: 'Find address', exact: true }).click();
      await page
        .locator('#place-address-status')
        .filter({ hasText: /Google address search timed out/ })
        .waitFor({ timeout: 17000 });
      await page.evaluate(() => {
        window.testGoogleMaps.geocodeMode = 'ok';
      });
      await page.getByRole('button', { name: 'Find address', exact: true }).click();
      await page
        .locator('#place-address-status')
        .filter({ hasText: /Found: Synthetic address from Google Maps/ })
        .waitFor();
    }
    await page.locator('#place-form details').evaluate((el) => {
      el.open = true;
    });
    await page.getByLabel('Place latitude', { exact: true }).fill('12.3456789');
    await page.getByLabel('Place longitude', { exact: true }).fill('-23.4567891');
    await page.getByRole('button', { name: 'Save place', exact: true }).click();
    await page.getByText('Place saved.', { exact: true }).waitFor();
    assert.equal(await page.locator('#place-form').isVisible(), false, 'Saving closes the form');
    await page.getByRole('button', { name: 'Add a place', exact: true }).click();
    await page.getByLabel('Place name', { exact: true }).fill('Duplicate Home');
    // A successful save clears the add form; explicitly create a colliding
    // second place rather than relying on stale coordinates from the first.
    await page.getByLabel('Place latitude', { exact: true }).fill('12.3456789');
    await page.getByLabel('Place longitude', { exact: true }).fill('-23.4567891');
    await page.getByRole('button', { name: 'Save place', exact: true }).click();
    await page.getByText('This area overlaps Synthetic Private Home.', { exact: false }).waitFor();
    assert.equal(
      await page
        .locator('#place-list .place-card')
        .filter({ hasText: 'Synthetic Private Home' })
        .count(),
      1,
    );
    assert.equal(
      await page
        .locator('#place-list')
        .getByText('Boundary radius: 100 m', { exact: true })
        .count(),
      1,
    );
    const readonlyPlace = page
      .locator('#place-list .place-card')
      .filter({ hasText: 'Synthetic Private Home' });
    const thumbnail = readonlyPlace.locator('.place-card-photo');
    await thumbnail.waitFor({ state: 'visible' });
    assert.equal(
      await thumbnail.getAttribute('aria-label'),
      'Read-only map preview for Synthetic Private Home',
    );
    assert.equal(await thumbnail.getAttribute('inert'), '');
    assert.equal(
      await thumbnail.evaluate((e) => getComputedStyle(e).pointerEvents),
      'none',
      'Place image cannot be clicked or dragged outside the boundary editor',
    );
    // Read-only previews carry no map controls (e.g. Google's fullscreen button) taking up the
    // tile.
    if (googleMode) {
      await page.waitForFunction(() =>
        testGoogleMaps.maps.some(
          (m) =>
            m.element.closest('.place-card-photo') &&
            m.created.disableDefaultUI === true &&
            m.created.gestureHandling === 'none',
        ),
      );
    } else {
      await page.waitForFunction(() =>
        [...document.querySelectorAll('#place-list .place-card-photo')].some((e) =>
          e.classList.contains('leaflet-container'),
        ),
      );
      assert.equal(
        await thumbnail.locator('.leaflet-control-zoom').count(),
        0,
        'Place previews have no zoom buttons',
      );
    }
    const placeLayout = await page.evaluate(() => ({
      tiles: document.querySelector('#place-list').getBoundingClientRect().top,
      overview: document.querySelector('#places-overview-map'),
      editor: document.querySelector('#place-editor').getBoundingClientRect().top,
    }));
    assert.equal(placeLayout.overview, null, 'Places has no separate overview map');
    assert.ok(
      placeLayout.tiles < placeLayout.editor,
      'Existing place tiles must appear above the add-place editor',
    );
    await readonlyPlace.getByRole('button', { name: 'Edit boundary' }).click();
    await page.getByRole('heading', { name: 'Edit Synthetic Private Home' }).waitFor();
    assert.equal(await page.locator('#cancel-place-edit').isVisible(), true);
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.getByRole('button', { name: 'Add a place', exact: true }).waitFor();
    assert.equal(await page.locator('#place-form').isVisible(), false, 'Cancel closes the form');
    assert.equal(
      await page.locator('.directions-link').count(),
      0,
      'No desktop Directions actions',
    );

    const context2 = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const second = await context2.newPage();
    second.on('pageerror', (error) => errors.push(error.message));
    await providers(second);
    await second.goto(origin);
    await second.locator('#login [name=email]').fill('owner@example.invalid');
    await second.locator('#login [name=password]').fill('synthetic long test password');
    await second.getByRole('button', { name: 'Sign in', exact: true }).click();
    // An unapproved additional browser is shown its pairing screen rather
    // than any household map, so navigate straight to the access panel.
    await second.getByRole('button', { name: 'Manage household', exact: true }).waitFor();
    await second.getByRole('button', { name: 'Manage household', exact: true }).click();
    // Additional admin browsers register automatically but still need a
    // trusted-browser signed approval, unlike member phone email enrollment.
    try {
      await second.getByRole('heading', { name: 'Approve this device', exact: true }).waitFor();
    } catch (error) {
      // Intermittent on the self-hosted runner: show where the new browser ended up instead.
      const screen = await second.evaluate(() => ({
        headings: [...document.querySelectorAll('h1,h2,h3')].map((h) => h.textContent.trim()),
        message: document.getElementById('message')?.textContent || '',
        nav: document.getElementById('app-nav')?.hidden,
        view: (document.querySelector('main')?.innerText || '').slice(0, 400),
      }));
      console.error(
        'Second browser screen: ' +
          JSON.stringify(screen) +
          ' page errors: ' +
          JSON.stringify(errors),
      );
      throw error;
    }
    const code = await second.locator('#pairing-code').textContent();
    assert.match(code, /^[0-9]{6}$/);
    // A trusted browser independently derives the same code from the new
    // device's signed public-key registration and its pinned household root.
    // Incoming device requests surface without hunting through settings.
    // Bring the approving browser forward; background tabs may suspend polling.
    await page.bringToFront();
    await page.locator('#device-request-alert').waitFor({ state: 'visible', timeout: 25000 });
    await page.getByRole('button', { name: 'Review requests', exact: true }).click();
    const access = page
      .locator('details')
      .filter({ has: page.locator('summary').filter({ hasText: 'Device access' }) })
      .first();
    await access.waitFor({ state: 'visible' });
    const joining = page.locator('.device-row').filter({ hasText: code });
    assert.equal(await joining.locator('.pairing-code').textContent(), code);
    page.once('dialog', (dialog) => dialog.accept());
    await joining.getByRole('button', { name: 'Approve device', exact: true }).click();
    await page
      .getByText('Device approved with a signed proof. The requesting device can open the map.', {
        exact: true,
      })
      .waitFor();
    // No root fingerprint input: signed approval automatically pins trust.
    await second.locator('#root-code').waitFor({ state: 'attached', timeout: 20000 });
    assert.equal(await second.locator('#root-code').textContent(), rootFingerprint);
    // Approval automatically re-encrypts the same saved place for the new device.
    await second.getByRole('button', { name: 'Places', exact: true }).click();
    await second
      .locator('#place-list .place-card')
      .filter({ hasText: 'Synthetic Private Home' })
      .waitFor({ state: 'visible' });
    assert.equal(
      await page.locator('#location-form, #profile-form').count(),
      0,
      'Household management no longer offers manual coordinate or profile publishing',
    );
    // Use only the synthetic trusted browser's vault to model Android-style offline uploads.
    const tripVault = await page.evaluate(async () => {
      const user = await (await fetch('/api/session')).json();
      const context = `${location.origin}/${user.id}`;
      const saved = JSON.parse(localStorage.getItem(`narahem.vault.${user.id}`));
      const db = await new Promise((resolve, reject) => {
        const q = indexedDB.open('narahem.device-keys', 1);
        q.onsuccess = () => resolve(q.result);
        q.onerror = reject;
      });
      const key = await new Promise((resolve, reject) => {
        const q = db.transaction('keys').objectStore('keys').get(context);
        q.onsuccess = () => resolve(q.result);
        q.onerror = reject;
      });
      db.close();
      const decode = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
      return JSON.parse(
        new TextDecoder().decode(
          await crypto.subtle.decrypt(
            {
              name: 'AES-GCM',
              iv: decode(saved.iv),
              additionalData: new TextEncoder().encode(context),
            },
            key,
            decode(saved.box),
          ),
        ),
      );
    });
    // The redesigned Ring controls intentionally exist on *member cards*, not
    // Device access or an administrator's own browser registration. Create an
    // independent approved synthetic member/phone, with a unique credential.
    const testMemberId = '22222222222222222222222222222222';
    const testPhoneId = '33333333333333333333333333333333';
    const memberFixture = spawnSync(
      process.env.NARAHEM_TEST_PYTHON || 'python3',
      [
        '-c',
        `
import base64,json,secrets,time,os
from nacl.public import PrivateKey
from nacl.signing import SigningKey
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from narahem.models import Account
from narahem.app import digest
from narahem.models import ClientDevice, ServiceState
from narahem.data_service import canonical
db=create_engine(os.environ['DATABASE_URL'])
with Session(db) as session:
  household=session.get(ServiceState,1).household_id
  member='${testMemberId}'
  device='${testPhoneId}'
  signer=SigningKey.generate()
  box=PrivateKey.generate()
  key=base64.b64encode(bytes(signer.verify_key)).decode()
  box_key=base64.b64encode(bytes(box.public_key)).decode()
  payload={'domain':'narahem.device.v1','household':household,'id':device,'account_id':member,'signing_key':key,'box_key':box_key,'platform':'android'}
  credential=secrets.token_urlsafe(32)
  session.add(Account(id=member,email='ring-fixture@example.invalid',username='Ring fixture',password=None,status='active',verified=True,role='member'))
  session.add(ClientDevice(id=device,account_id=member,name='Synthetic Android phone',signing_key=key,box_key=box_key,credential=digest(credential),registration=canonical(payload).decode(),registration_signature=base64.b64encode(signer.sign(canonical(payload)).signature).decode(),status='approved',sharing=True,created=time.time(),seen=time.time()))
  session.commit()
  print(credential)
`,
      ],
      {
        cwd: BACKEND,
        env: { ...process.env, DATABASE_URL: `sqlite:///${directory}/test.db` },
        encoding: 'utf8',
      },
    );
    assert.equal(
      memberFixture.status,
      0,
      memberFixture.stderr || 'Synthetic member phone setup failed',
    );
    const phoneCredential = memberFixture.stdout.trim();
    assert.ok(phoneCredential.length > 24, 'Fixture has independent phone credential');
    // Re-entering the household screen lists the enrolled synthetic member.
    await page.getByRole('button', { name: 'Manage household', exact: true }).click();
    const testMember = page
      .locator('.member-card')
      .filter({ hasText: 'ring-fixture@example.invalid' });
    await testMember.waitFor();
    async function phoneRequest(url, method, body) {
      return page.evaluate(
        async ({ url, method, body, credential }) => {
          const session = await (await fetch('/api/session')).json();
          const response = await fetch(url, {
            method,
            headers: {
              Authorization: 'Bearer ' + credential,
              'Content-Type': 'application/json',
              'X-CSRF-Token': session.csrf,
            },
            ...(body === undefined ? {} : { body: JSON.stringify(body) }),
          });
          if (!response.ok) throw new Error('Phone fixture HTTP ' + response.status);
          return response.json();
        },
        { url, method, body, credential: phoneCredential },
      );
    }
    await phoneRequest('/api/find-phone/capability', 'PUT', { enabled: true, platform: 'android' });
    await phoneRequest('/api/device/permissions', 'PUT', {
      foreground_location: true,
      background_location: true,
      remote_alarm: true,
      dnd_access: true,
      notifications: true,
      sharing: true,
    });
    await page.evaluate(async () =>
      window.FamilyClient.refreshHouseholdMemberPhones(document.querySelector('#view')),
    );
    const testPushButton = testMember.getByRole('button', {
      name: 'Test notification',
      exact: true,
    });
    await testPushButton.click();
    await testMember
      .locator('.member-push-feedback')
      .getByText(/No approved phone with a push subscription/)
      .waitFor();
    assert.equal(
      await testPushButton.isEnabled(),
      true,
      'Test push returns a visible local failure and re-enables its control',
    );
    const phoneRevoke = testMember.getByRole('button', { name: 'Revoke phone', exact: true });
    await phoneRevoke.waitFor({ state: 'visible' });
    assert.equal(
      await phoneRevoke.count(),
      1,
      'Registered phone has an independent permanent revocation control',
    );
    const memberActions = testMember.locator('.member-destructive-actions');
    assert.deepEqual(
      await memberActions.locator('button').allTextContents(),
      ['Revoke phone', 'Revoke user', 'Delete user and data'],
      'Destructive phone and account actions have their own lower row',
    );
    assert.deepEqual(
      await testMember.locator('.member-primary-actions button').allTextContents(),
      ['Test notification', 'Ring phone', 'Send password reset'],
      'Everyday actions appear above the destructive buttons',
    );
    assert.equal(
      await phoneRevoke
        .locator('xpath=ancestor::div[contains(@class, "member-phone-revokes")]')
        .count(),
      1,
      'Permanent phone revocation is at the lower left of the member card',
    );
    const ringPhone = testMember.getByRole('button', { name: 'Ring phone', exact: true });
    await ringPhone.waitFor({ state: 'visible' });
    await page.locator('.member-permission-badge[data-state="allowed"]').first().waitFor();
    const finderSpacing = await testMember.locator('.find-phone-actions').evaluate((el) => ({
      gap: getComputedStyle(el).columnGap,
      buttons: [...el.children].map((button) => button.textContent),
    }));
    assert.equal(
      finderSpacing.gap,
      '12px',
      'Phone action buttons have consistent touch-friendly spacing',
    );
    assert.deepEqual(finderSpacing.buttons, ['Ring phone']);
    assert.equal(
      await testMember.getByRole('button', { name: 'Stop ringing', exact: true }).count(),
      0,
    );
    assert.equal(
      await testMember.locator(':scope > .member-destructive-actions').count(),
      1,
      'Danger controls occupy their own card row',
    );
    assert.equal(
      await testMember.locator('.member-primary-actions .member-destructive-actions').count(),
      0,
      'Danger controls must never be nested with the everyday phone actions',
    );
    const cardActions = await testMember.evaluate((member) => {
      const regular = member.querySelector('.member-primary-actions').getBoundingClientRect();
      const danger = member.querySelector('.member-destructive-actions').getBoundingClientRect();
      const style = getComputedStyle(member.querySelector('.member-destructive-actions'));
      const card = getComputedStyle(member);
      return {
        regularBottom: regular.bottom,
        dangerTop: danger.top,
        divider: style.borderBottomWidth,
        topDivider: style.borderTopWidth,
        width: window.innerWidth,
        cardBorder: card.borderTopWidth,
        cardRadius: card.borderTopLeftRadius,
        cardBackground: card.backgroundColor,
      };
    });
    assert.ok(
      cardActions.dangerTop > cardActions.regularBottom,
      'Revoke and Delete must appear below normal member actions',
    );
    // Member cards are enclosed like Saved Place cards; the card edge replaces row dividers.
    assert.deepEqual(
      [cardActions.cardBorder, cardActions.cardRadius, cardActions.cardBackground],
      ['1px', '16px', 'rgb(15, 36, 89)'],
      'Member cards use the Saved Place card border, radius and background',
    );
    assert.equal(cardActions.divider, '0px', 'No row divider inside an enclosed member card');
    assert.equal(
      cardActions.topDivider,
      '0px',
      'Red buttons sit directly in the card, without a divider above',
    );
    assert.equal(
      await page.locator('#device-list button').count(),
      0,
      'Device Access is strictly read-only',
    );
    assert.equal(
      await page.locator('#device-list .find-phone-actions').count(),
      0,
      'Device access no longer duplicates household Ring/Stop',
    );
    assert.equal(
      await page.locator('.member-phone .find-phone-help').count(),
      0,
      'Troubleshooting paragraphs no longer appear in the household card',
    );
    // A GPS/contact refresh updates only the phone's badges and status, not its
    // ring button, family photo, member card or the rest of the DOM.
    const stable = await page.evaluate(async () => {
      const member = [...document.querySelectorAll('.member-card')].find((e) =>
        e.textContent.includes('ring-fixture@example.invalid'),
      );
      const ring = member.querySelector('.find-phone-actions button');
      const avatar = member.querySelector('.member-photo');
      await window.FamilyClient.refreshHouseholdMemberPhones(document.querySelector('#view'));
      return {
        member:
          [...document.querySelectorAll('.member-card')].find((e) =>
            e.textContent.includes('ring-fixture@example.invalid'),
          ) === member,
        ring: member.querySelector('.find-phone-actions button') === ring,
        photo: member.querySelector('.member-photo') === avatar,
      };
    });
    assert.deepEqual(stable, { member: true, ring: true, photo: true });
    await ringPhone.click();
    await page
      .locator('.phone-action-feedback')
      .filter({ hasText: /Ring request sent/ })
      .waitFor();
    const alarm = (await phoneRequest('/api/find-phone/command', 'GET')).command;
    assert.equal(alarm.body.action, 'ring');
    await phoneRequest('/api/find-phone/report', 'POST', {
      command_id: alarm.body.id,
      status: 'ringing',
      reason: '',
    });
    // The handset stops its own ringing; no redundant server Stop action is offered.
    await phoneRequest('/api/find-phone/report', 'POST', {
      command_id: alarm.body.id,
      status: 'stopped',
      reason: 'user_stopped',
    });
    // Reporting a revoked OS privilege disables Ring phone; no remote stop is exposed.
    await phoneRequest('/api/device/permissions', 'PUT', {
      foreground_location: true,
      background_location: true,
      remote_alarm: true,
      dnd_access: false,
      notifications: false,
      sharing: true,
    });
    await page.evaluate(async () =>
      window.FamilyClient.refreshHouseholdMemberPhones(document.querySelector('#view')),
    );
    assert.equal(await ringPhone.isDisabled(), true);
    assert.equal(await page.getByRole('button', { name: 'Stop ringing', exact: true }).count(), 0);
    assert.equal(
      (await page.locator('.member-permission-badge[data-state="denied"]').count()) > 0,
      true,
    );
    // Legacy APKs have no permission snapshot. Recent GPS or phone polling
    // proves activity, not current OS grants.
    assert.equal(
      fixture(
        "DELETE FROM device_permission_snapshots WHERE device_id='33333333333333333333333333333333'",
      ).status,
      0,
    );
    await phoneRequest('/api/find-phone/command', 'GET');
    await page.evaluate(async () =>
      window.FamilyClient.refreshHouseholdMemberPhones(document.querySelector('#view')),
    );
    const indicators = testMember.locator('.member-status-indicators');
    assert.equal(await indicators.locator('.member-permission-badge').count(), 2);
    assert.equal(
      (await indicators.locator('.member-permission-badge[data-state="observed"]').count()) > 0,
      true,
    );
    assert.match(
      await indicators.locator('.member-permission-badge').last().getAttribute('title'),
      /cannot be verified|not confirmed|has not submitted a fresh OS permission report/,
    );
    const layout = await testMember.evaluate((member) => {
      const indicators = member.querySelector('.member-status-indicators').getBoundingClientRect();
      const actions = member.querySelector('.member-primary-actions').getBoundingClientRect();
      return { badgesLeft: indicators.left, actionsLeft: actions.left, width: window.innerWidth };
    });
    if (layout.width > 1050) {
      assert.ok(
        layout.badgesLeft < layout.actionsLeft,
        'Status badges belong between member details and action buttons',
      );
    }
    assert.equal(
      await ringPhone.isEnabled(),
      true,
      'Existing APK remains ringable when server-side remote alarm opt-in is enabled',
    );

    // Remove synthetic UI-only member/device before the owner trip-history suite.
    for (const statement of [
      "DELETE FROM device_permission_snapshots WHERE device_id='33333333333333333333333333333333'",
      "DELETE FROM find_phone_commands WHERE target_id='33333333333333333333333333333333'",
      "DELETE FROM find_phone_capabilities WHERE device_id='33333333333333333333333333333333'",
      "DELETE FROM client_devices WHERE id='33333333333333333333333333333333'",
      "DELETE FROM accounts WHERE id='22222222222222222222222222222222'",
    ]) {
      assert.equal(fixture(statement).status, 0, 'Synthetic member cleanup: ' + statement);
    }
    const cryptoClient = await import(
      require('node:url').pathToFileURL(path.resolve(__dirname, '../../src/crypto.mjs')).href
    );
    await cryptoClient.ready;
    const trustedResponse = await page.evaluate(
      async (credential) =>
        (await fetch('/api/roster', { headers: { Authorization: 'Bearer ' + credential } })).json(),
      tripVault.credential,
    );
    const trustedTripRoster = cryptoClient.verifyChain(
      trustedResponse.changes,
      tripVault.household,
      tripVault.anchor,
    ).current;
    const tripEnd = Date.now() - 35 * 60000;
    const tripStart = tripEnd - 10 * 60000;
    // Like every app, the fixtures also seal each record for the server.
    const serverKey = (
      await page.evaluate(
        async (credential) =>
          (
            await fetch('/api/device', { headers: { Authorization: 'Bearer ' + credential } })
          ).json(),
        tripVault.credential,
      )
    ).trip_processing_key;
    async function uploadFixture(envelope) {
      const response = await page.evaluate(
        async ({ envelope, credential }) => {
          const session = await (await fetch('/api/session')).json();
          const r = await fetch('/api/records', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: 'Bearer ' + credential,
              'X-CSRF-Token': session.csrf,
            },
            body: JSON.stringify(envelope),
          });
          return { status: r.status, body: await r.json() };
        },
        { envelope, credential: tripVault.credential },
      );
      assert.equal(response.status, 201, JSON.stringify(response.body));
      tripVault.sequence = envelope.body.sequence;
    }
    await uploadFixture(
      cryptoClient.encryptedRecord(
        tripVault,
        trustedTripRoster,
        'profile',
        tripVault.account_id,
        { name: 'Synthetic Private Owner', photo: null },
        'upsert',
        null,
        Date.now(),
        serverKey,
      ),
    );
    await uploadFixture(
      cryptoClient.encryptedRecord(
        tripVault,
        trustedTripRoster,
        'location',
        tripVault.account_id,
        { lat: 12.3456789, lon: -23.4567891, accuracy: 5 },
        'upsert',
        null,
        tripStart + 5000,
        serverKey,
      ),
    );
    await uploadFixture(
      cryptoClient.encryptedRecord(
        tripVault,
        trustedTripRoster,
        'location',
        tripVault.account_id,
        { lat: 12.3458789, lon: -23.4567891, accuracy: 5 },
        'upsert',
        null,
        tripStart + 65000,
        serverKey,
      ),
    );
    for (const offset of [60000, 180000, 300000]) {
      await uploadFixture(
        cryptoClient.encryptedRecord(
          tripVault,
          trustedTripRoster,
          'location',
          tripVault.account_id,
          { lat: 12.3558789, lon: -23.4567891, accuracy: 5, speed_mps: 0 },
          'upsert',
          null,
          tripEnd + offset,
          serverKey,
        ),
      );
    }
    await uploadFixture(
      cryptoClient.encryptedRecord(
        tripVault,
        trustedTripRoster,
        'event',
        cryptoClient.uuid(),
        {
          type: 'trip_summary',
          account_id: tripVault.account_id,
          started_at: tripStart,
          ended_at: tripEnd,
          distance_m: 1609.344,
          max_speed_mps: 20,
          samples: 12,
          // Phones send the trip's ends and a route outline; the server lists the trip from these.
          start: [12.3456789, -23.4567891],
          end: [12.3558789, -23.4567891],
          preview: [
            [12.3456789, -23.4567891],
            [12.3458789, -23.4567891],
            [12.3558789, -23.4567891],
          ],
        },
        'upsert',
        null,
        tripEnd,
        serverKey,
      ),
    );
    // Temporarily make this synthetic owner a tracked member for the trip directory.
    assert.equal(
      fixture("UPDATE accounts SET role='member' WHERE email='owner@example.invalid'").status,
      0,
    );
    await page.getByRole('button', { name: 'Trips', exact: true }).click();
    await page.locator('#trip-status').getByText('1 completed trip ·', { exact: false }).waitFor();
    await page.locator('.timeline-card .trip-map').first().waitFor();
    assert.equal(
      await page.locator('.trip-filters').evaluate((e) => getComputedStyle(e).display),
      'flex',
      'Trip filters use their stylesheet',
    );
    assert.equal(
      await page
        .locator('.trip-stats')
        .first()
        .evaluate((e) => getComputedStyle(e).display),
      'grid',
      'Trip statistics use the styled layout',
    );
    await page.getByText('1.00 mi', { exact: true }).waitFor();
    await page.getByText('10 min', { exact: true }).waitFor();
    await page.getByText('Top speed: 45 mph', { exact: true }).waitFor();
    assert.equal(
      await page.getByRole('button', { name: 'Show received GPS samples', exact: true }).count(),
      0,
      'Diagnostics are absent from normal trip cards',
    );
    for (const text of [
      'GPS points associated',
      'moving observations',
      'Server processing disabled',
    ]) {
      assert.equal(
        await page.locator('.timeline-card').getByText(text, { exact: false }).count(),
        0,
        `Trip cards omit "${text}"`,
      );
    }
    await page
      .locator('.timeline-card h3')
      .getByText('Synthetic Private Home', { exact: true })
      .first()
      .waitFor();
    await page.getByRole('button', { name: 'Save Place', exact: true }).waitFor();
    const tripThumbnail = page.locator('.timeline-card .trip-route-thumbnail').first();
    await tripThumbnail.locator('svg polyline').waitFor({ state: 'attached' });
    await tripThumbnail.locator('img.trip-tiles').waitFor({ state: 'attached' });
    if (googleMode) {
      // With a Google key the background is a dark Google static map (basemap only; the route never
      // leaves the browser).
      const src = await tripThumbnail.locator('img.trip-tiles').getAttribute('src');
      assert.match(src, /^https:\/\/maps\.googleapis\.com\/maps\/api\/staticmap\?/);
      assert.ok(!/path=|markers=/.test(src), 'Static map request carries no route or markers');
      assert.match(
        decodeURIComponent(src),
        /style=element:geometry\|color:0x/,
        'Static map uses the dark style',
      );
    } else {
      await tripThumbnail
        .getByText('© OpenStreetMap contributors', { exact: true })
        .waitFor({ state: 'attached' });
    }
    assert.match(
      await tripThumbnail.locator('svg polyline').getAttribute('points'),
      /,/,
      'Static thumbnail depicts recorded route coordinates',
    );
    assert.equal(
      await tripThumbnail.evaluate((e) => getComputedStyle(e).pointerEvents),
      'none',
      'A trip list preview is never a live map or click handler',
    );
    assert.equal(await page.locator('#more-route-history').count(), 0);
    assert.equal(await page.locator('#refresh-routes').count(), 0);
    assert.ok((await tripThumbnail.boundingBox()).height >= 140, 'Thumbnail has a stable height');
    page.once('dialog', (d) => d.accept('Store stop'));
    await page.getByRole('button', { name: 'Save Place', exact: true }).click();
    await page.getByText('Store stop', { exact: true }).first().waitFor();
    await page.getByRole('button', { name: 'Open trip', exact: true }).first().click();
    await page.locator('.trip-dialog[open] .trip-map-large').waitFor();
    if (googleMode) {
      await page.waitForFunction(() =>
        testGoogleMaps.polylines.some((p) => p.map && p.path.length === 2),
      );
    } else {
      const routePath = page
        .locator('.trip-dialog .leaflet-overlay-pane path.leaflet-interactive')
        .first();
      await routePath.waitFor({ state: 'attached' });
      assert.match(
        await routePath.getAttribute('d'),
        /M.+L/,
        'Recorded route appears only in opened interactive map',
      );
    }
    await page.locator('.trip-dialog').getByRole('button', { name: 'Close', exact: true }).click();
    assert.equal(
      fixture("UPDATE accounts SET role='admin' WHERE email='owner@example.invalid'").status,
      0,
    );
    await page.getByRole('button', { name: 'Manage household', exact: true }).click();
    await second.getByRole('button', { name: 'Household map', exact: true }).click();
    await second
      .locator('#map-status')
      .getByText('No shared locations available.', { exact: true })
      .waitFor();
    assert.equal(
      await second.locator('.map-person').count(),
      0,
      'Server administrator is never shown as a household location',
    );
    await second.getByRole('button', { name: 'Manage household', exact: true }).click();
    assert.equal(
      await second.locator('.member-card').filter({ hasText: 'owner@example.invalid' }).count(),
      0,
      'Server administrator is managed separately from household members',
    );
    await second.setViewportSize({ width: 390, height: 844 });
    assert.ok(
      await second.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      'Member cards fit phone',
    );
    // Persisted wrapping key is non-extractable, ciphertext contains no secrets.
    const remembered = await second.evaluate(async () => {
      const u = await (await fetch('/api/session')).json();
      const db = await new Promise((r, j) => {
        const q = indexedDB.open('narahem.device-keys', 1);
        q.onsuccess = () => r(q.result);
        q.onerror = j;
      });
      const key = await new Promise((r, j) => {
        const q = db.transaction('keys').objectStore('keys').get(`${location.origin}/${u.id}`);
        q.onsuccess = () => r(q.result);
        q.onerror = j;
      });
      let rejected = false;
      db.close();
      try {
        await crypto.subtle.exportKey('raw', key);
      } catch {
        rejected = true;
      }
      return {
        extractable: key.extractable,
        rejected,
        vault: localStorage.getItem(`narahem.vault.${u.id}`),
      };
    });
    assert.equal(remembered.extractable, false);
    assert.equal(remembered.rejected, true);
    assert.ok(
      !remembered.vault.includes('credential') && !remembered.vault.includes('signing_secret'),
    );
    // Exercise one-time migration from the previous passphrase vault format.
    await second.evaluate(async () => {
      // Stop the running client first: a background save() could otherwise rewrite
      // the vault in its current format before the reload (intermittent CI failure).
      window.FamilyClient?.lock?.();
      const user = await (await fetch('/api/session')).json();
      const context = `${location.origin}/${user.id}`;
      const storeKey = `narahem.vault.${user.id}`;
      const saved = JSON.parse(localStorage.getItem(storeKey));
      const db = await new Promise((resolve, reject) => {
        const q = indexedDB.open('narahem.device-keys', 1);
        q.onsuccess = () => resolve(q.result);
        q.onerror = reject;
      });
      const wrapped = await new Promise((resolve, reject) => {
        const q = db.transaction('keys').objectStore('keys').get(context);
        q.onsuccess = () => resolve(q.result);
        q.onerror = reject;
      });
      const decode = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
      const encode = (v) =>
        btoa(Array.from(new Uint8Array(v), (x) => String.fromCharCode(x)).join(''));
      const plaintext = await crypto.subtle.decrypt(
        {
          name: 'AES-GCM',
          iv: decode(saved.iv),
          additionalData: new TextEncoder().encode(context),
        },
        wrapped,
        decode(saved.box),
      );
      const salt = crypto.getRandomValues(new Uint8Array(16));
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const base = await crypto.subtle.importKey(
        'raw',
        new TextEncoder().encode('synthetic legacy vault passphrase'),
        'PBKDF2',
        false,
        ['deriveKey'],
      );
      const key = await crypto.subtle.deriveKey(
        { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: 600000 },
        base,
        { name: 'AES-GCM', length: 256 },
        false,
        ['encrypt', 'decrypt'],
      );
      const box = await crypto.subtle.encrypt(
        { name: 'AES-GCM', iv, additionalData: new TextEncoder().encode(context) },
        key,
        plaintext,
      );
      localStorage.setItem(
        storeKey,
        JSON.stringify({ version: 1, salt: encode(salt), iv: encode(iv), box: encode(box) }),
      );
      await new Promise((resolve, reject) => {
        const tx = db.transaction('keys', 'readwrite');
        tx.objectStore('keys').delete(context);
        tx.oncomplete = resolve;
        tx.onerror = reject;
      });
      db.close();
    });
    await second.reload();
    await second
      .getByLabel('Existing browser-vault passphrase', { exact: true })
      .fill('incorrect passphrase');
    console.log(
      'Migration form',
      await second.locator('#vault-form').evaluate((f) => ({
        valid: f.checkValidity(),
        handler: typeof f.onsubmit,
        fields: [...f.elements].map((e) => ({
          name: e.name,
          type: e.type,
          length: e.value?.length,
          valid: e.validity?.valid,
        })),
      })),
    );
    await second.getByRole('button', { name: 'Remember this browser', exact: true }).click();
    try {
      await second.waitForFunction(
        () => document.getElementById('message').textContent.length > 0,
        {},
        { timeout: 5000 },
      );
    } catch (e) {
      console.log(
        'Migration state',
        await second.evaluate(() => ({
          url: location.href,
          message: document.getElementById('message').textContent,
          forms: [...document.forms].map((f) => ({
            id: f.id,
            valid: f.checkValidity(),
            handler: typeof f.onsubmit,
          })),
        })),
      );
      throw e;
    }
    assert.equal(
      await second.locator('#message').textContent(),
      'Could not unlock: check your browser-vault passphrase.',
    );
    await second
      .getByLabel('Existing browser-vault passphrase', { exact: true })
      .fill('synthetic legacy vault passphrase');
    await second.getByRole('button', { name: 'Remember this browser', exact: true }).click();
    await second.locator('#root-code').waitFor({ state: 'attached' });
    await second.getByRole('button', { name: 'Sign out', exact: true }).click();
    await second.getByRole('heading', { name: 'Welcome home.' }).waitFor();
    assert.equal(await second.locator('.map-person').count(), 0, 'Sign-out removes locations');
    await second.locator('#login [name=email]').fill('owner@example.invalid');
    await second.locator('#login [name=password]').fill('synthetic long test password');
    await second.getByRole('button', { name: 'Sign in', exact: true }).click();
    await second.getByRole('button', { name: 'Household map', exact: true }).click();
    await second
      .locator('#map-status')
      .getByText('No shared locations available.', { exact: true })
      .waitFor();
    assert.equal(
      await second.locator('.map-person').count(),
      0,
      'Restoring a trusted browser must not reveal administrator GPS',
    );
    assert.equal(
      await second.getByRole('button', { name: 'Unlock map', exact: true }).count(),
      0,
      'Trusted browser needs no extra unlock',
    );
    for (const raw of recordRequests) {
      assert.ok(!raw.includes('12.3456789'));
      assert.ok(!raw.includes('Synthetic Private Home'));
      assert.ok(!raw.includes('Synthetic Private Owner'));
    }
    if (googleMode) {
      await second.waitForFunction(() => globalThis.testGoogleMaps?.maps?.length > 0);
      assert.ok(
        await second.evaluate(() => testGoogleMaps.maps.at(-1).getZoom() <= 15),
        'Google frames shared people',
      );
    }
    assert.equal(
      fixture(
        "INSERT INTO accounts (id,email,username,password,role,status,verified) VALUES ('11111111111111111111111111111111','delete-test@example.invalid',NULL,NULL,'member','pending',false)",
      ).status,
      0,
    );
    await page.getByRole('button', { name: 'Manage household', exact: true }).click();
    const pending = page.locator('.member-card').filter({ hasText: 'delete-test@example.invalid' });
    await pending.getByText('No location shared with this browser', { exact: true }).waitFor();
    page.once('dialog', (d) => d.accept());
    await pending.getByRole('button', { name: 'Delete user and data', exact: true }).click();
    await page
      .getByText('User and server data deleted. You can invite the same contact again.', {
        exact: true,
      })
      .waitFor();
    assert.equal(await pending.count(), 0);
    if (!(await page.locator('#device-list').isVisible())) {
      await page.locator('summary').filter({ hasText: 'Device access' }).click();
    }
    assert.equal(
      await page.locator('#device-list').isVisible(),
      true,
      'Device access opens from its heading',
    );
    await page.getByRole('button', { name: 'Places', exact: true }).click();
    const placeRow = page
      .locator('#place-list .place-card')
      .filter({ hasText: 'Synthetic Private Home' });
    await placeRow.waitFor({ state: 'visible', timeout: 15000 });
    assert.equal(
      await placeRow.isVisible(),
      true,
      'Saved places are visible on the dedicated Places page',
    );
    page.once('dialog', (d) => d.dismiss());
    await placeRow.getByRole('button', { name: 'Delete place', exact: true }).click();
    assert.equal(await placeRow.count(), 1, 'Cancelling deletion preserves the place');
    page.once('dialog', (d) => d.accept());
    await placeRow.getByRole('button', { name: 'Delete place', exact: true }).click();
    await page.getByText('Place deleted.', { exact: true }).waitFor();
    assert.equal(await placeRow.count(), 0, 'Confirmed place deletion removes the place');
    await page.getByRole('button', { name: 'Manage household', exact: true }).click();
    const deviceRowsBefore = await page.locator('#device-list .device-row').count();
    page.once('dialog', (d) => d.accept());
    await page
      .locator('#browser-access-devices')
      .getByRole('button', { name: 'Revoke browser', exact: true })
      .first()
      .click();
    await page
      .getByText('Browser revoked. A replacement browser must pair again.', { exact: true })
      .waitFor()
      .catch(async (error) => {
        throw new Error(
          'Browser revoke failed: ' +
            (await page.locator('#message').textContent()) +
            '; ' +
            error.message,
        );
      });
    assert.equal(
      await page.locator('#device-list .device-row').count(),
      deviceRowsBefore - 1,
      'Revoked browser disappears from the read-only Device Access list',
    );
    assert.ok(
      await page.evaluate(async () => {
        const result = await (await fetch('/api/devices')).json();
        return result.devices.some((device) => device.status === 'revoked');
      }),
      'Revoked identity remains available for membership reconciliation',
    );
    // Diagnostics are available through the private container CLI now; the
    // web UI must not surface a Logs pane or expose plaintext record contents.
    assert.equal(
      await page.getByRole('button', { name: 'Logs', exact: true }).count(),
      0,
      'The retired Logs pane is not present in navigation',
    );
    await page.getByRole('button', { name: 'Admin settings', exact: true }).click();
    const storage = page.locator('details.settings-section').filter({
      has: page.locator('summary', { hasText: 'Storage and retention' }),
    });
    if (!(await storage.evaluate((el) => el.open))) await storage.locator('summary').click();
    await page.getByText('python manage.py diagnostics', { exact: false }).waitFor();
    const auditAvailable = await page.evaluate(async () => {
      const response = await fetch('/api/logs?category=administration');
      const result = await response.json();
      return response.ok && result.entries.length > 0;
    });
    assert.ok(auditAvailable, 'Privileged diagnostic records remain available for local export');
    await context2.close();
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await page.getByRole('heading', { name: 'Welcome home.' }).waitFor();
    // Exercise the real map adapter with a visible viewport and synthetic member coordinates.
    const mapBundle = await require('esbuild').build({
      entryPoints: [path.join(__dirname, '../../src/maps.mjs')],
      bundle: true,
      write: false,
      format: 'iife',
      globalName: 'MapRegression',
    });
    await page.evaluate(mapBundle.outputFiles[0].text);
    const framing = await page.evaluate(async (googleMode) => {
      const target = document.createElement('div');
      target.style.cssText = 'width:600px;height:400px';
      document.body.append(target);
      const m = MapRegression.createHouseholdMap(
        target,
        { provider: googleMode ? 'google' : 'openstreetmap', api_key: 'synthetic-browser-key' },
        (e) => {
          throw e;
        },
      );
      // A Google provider must not show a transient Leaflet marker before it loads.
      // Nearby people share an approximate place, but keep distinct screen
      // portraits anchored to their genuine GPS coordinates.
      const fan = MapRegression.householdAvatarFan([
        { id: 'member-a', lat: 40.0, lon: -74.0, place: 'Home' },
        { id: 'member-b', lat: 40.00022, lon: -74.00019, place: 'Home' },
        { id: 'elsewhere', lat: 40.02, lon: -74.02, place: 'Work' },
      ]);
      const fanValid =
        fan[0].clusterSize === 2 &&
        fan[1].clusterSize === 2 &&
        fan[0].dx < 0 &&
        fan[1].dx > 0 &&
        fan[2].dx === 0 &&
        fan[2].dy === 0 &&
        fan[2].clusterSize === 1;
      const fanAgain = MapRegression.householdAvatarFan([
        { id: 'member-b', lat: 40.00022, lon: -74.00019, place: 'Home' },
        { id: 'member-a', lat: 40.0, lon: -74.0, place: 'Home' },
      ]);
      const fanStable = fanAgain[1].dx === fan[0].dx;
      const before = document.createElement('div');
      before.className = 'map-person';
      const queued = m.location([40, -74], before, document.createElement('p'), false);
      const hasPrematureMarker = Boolean(target.querySelector('.map-person'));
      await m.load();
      m.resize();
      const icon = document.createElement('div');
      icon.className = 'map-person';
      const visible = m.location([40, -74], icon, document.createElement('p'), false);
      const hasLoadedMarker = Boolean(target.querySelector('.map-person'));
      const compact = document.createElement('div');
      compact.className = 'member-map-popup';
      compact.textContent = 'At Home · last update 11:02 PM';
      const memberIcon = document.createElement('div');
      memberIcon.className = 'map-person map-person-grouped';
      memberIcon.dataset.memberName = 'Test member';
      memberIcon.style.setProperty('--fan-x', '21px');
      const member = m.location([40, -74], memberIcon, compact, false);
      const shown = target.contains(compact) && compact.getAttribute('role') === 'tooltip';
      memberIcon.click();
      const opens = memberIcon.classList.contains('is-open');
      memberIcon.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      const closes = !memberIcon.classList.contains('is-open');
      m.frameHousehold([[40, -74]], true);
      const single = googleMode
        ? testGoogleMaps.maps.at(-1).options.minZoom
        : target.querySelector('.leaflet-control-zoom-out').classList.contains('leaflet-disabled');
      m.frameHousehold(
        [
          [40, -74],
          [41, -75],
        ],
        true,
      );
      const spread = googleMode
        ? testGoogleMaps.maps.at(-1).options.minZoom
        : target.querySelector('.leaflet-control-zoom-out').classList.contains('leaflet-disabled');
      queued.remove();
      visible.remove();
      member.remove();
      m.remove();
      target.remove();
      return {
        single,
        spread,
        hasPrematureMarker,
        hasLoadedMarker,
        shown,
        opens,
        closes,
        fanValid,
        fanStable,
      };
    }, googleMode);
    assert.equal(
      framing.hasPrematureMarker,
      false,
      'Map markers do not flash before provider load',
    );
    assert.equal(framing.hasLoadedMarker, true, 'A loaded provider displays the member avatar');
    assert.equal(
      framing.fanValid,
      true,
      'Nearby members fan out while distant members stay centered',
    );
    assert.equal(framing.fanStable, true, 'Fanned portraits keep stable member ordering');
    assert.equal(framing.shown, true, 'Map overlays contain a compact accessible member tooltip');
    assert.equal(framing.opens, true, 'Each member avatar opens its own tooltip');
    assert.equal(framing.closes, true, 'Escape closes the member tooltip');
    if (googleMode) {
      assert.equal(framing.single, 15);
      assert.ok(
        framing.spread > 2 && framing.spread < 15,
        'Spread-out members determine a wider minimum zoom',
      );
    } else {
      assert.equal(framing.single, true, 'One member cannot zoom out to the world');
      assert.equal(framing.spread, true, 'Zoom-out stops at household bounds');
    }
    assert.deepEqual(errors, [], 'No browser errors');
    console.log(
      'Three tabs, trusted browser keys, two-device encryption, private member cards, ' +
        'deletion, automatic map and sign-out passed.',
    );
  } catch (error) {
    const lines = (await fs.readFile(serverLog, 'utf8')).trim().split('\n');
    console.error('Server log (last 80 lines):\n' + lines.slice(-80).join('\n'));
    throw error;
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    if (server.exitCode === null) await new Promise((resolve) => server.once('exit', resolve));
    await fs.rm(directory, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
