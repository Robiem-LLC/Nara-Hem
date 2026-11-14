// Films the web setup steps on a brand-new server, with captions, a terminal panel for the
// setup token from the server's logs, and an inbox panel showing the emails the server sends.
// Driven by run.py setup; the server captures its email and run.py copies it to SHOWCASE_INBOX.
//   step 1  server   create the household and administrator; this browser becomes trusted
//   step 2  email    connect email, send a test, confirm the administrator's address
//   step 3  invite   invite a family member, who accepts; the family then appears on the map
const path = require('node:path');
const fs = require('node:fs');

const { chromium } = require(
  path.join(__dirname, '../../apps/webapp/frontend/node_modules/playwright'),
);

const env = process.env;
const viewport = { width: 1280, height: 800 };
const STEPS = 3;

/** Waits ms milliseconds. */
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Draws the captions, the fake pointer and the side panel. Runs in the page, on every load,
 * from the state saved in sessionStorage.
 */
function overlay() {
  const css = `
    #showcase-caption { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%);
      z-index: 2147483000; max-width: 820px; padding: 14px 22px; border-radius: 16px;
      background: rgba(6, 20, 58, 0.94); color: #fdf6e3; font: 600 19px/1.4 system-ui, sans-serif;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45); border: 1px solid rgba(255, 195, 90, 0.55);
      display: flex; gap: 14px; align-items: center; pointer-events: none; }
    #showcase-caption b { flex: none; padding: 4px 10px; border-radius: 999px; background: #ffc35a;
      color: #06143a; font-size: 14px; letter-spacing: 0.04em; text-transform: uppercase; }
    #showcase-panel { position: fixed; top: 84px; right: 18px; width: 390px; max-height: 560px;
      overflow: hidden; z-index: 2147482999; border-radius: 14px; font: 14px/1.45 system-ui,
      sans-serif; box-shadow: 0 14px 40px rgba(0, 0, 0, 0.5); }
    #showcase-panel .bar { padding: 10px 14px; font-weight: 700; display: flex; gap: 8px;
      align-items: center; }
    #showcase-panel.terminal { background: #0b0f14; color: #d7e3ee;
      border: 1px solid #2c3a48; }
    #showcase-panel.terminal .bar { background: #1b2530; color: #9fb3c8; }
    #showcase-panel.terminal .bar i { width: 11px; height: 11px; border-radius: 50%;
      display: inline-block; background: #ff5f57; box-shadow: 17px 0 #febc2e, 34px 0 #28c840;
      margin-right: 40px; }
    #showcase-panel, #showcase-panel * { box-sizing: border-box; }
    #showcase-panel.terminal pre { margin: 0; border: 0; background: none; color: inherit; padding: 14px; white-space: pre-wrap;
      word-break: break-all; font: 13px/1.5 ui-monospace, Menlo, monospace; }
    #showcase-panel.terminal .prompt { color: #7ee787; }
    #showcase-panel.terminal .token { color: #ffc35a; }
    #showcase-panel.inbox { background: #ffffff; color: #1d2433; border: 1px solid #d5dbe6; }
    #showcase-panel.inbox .bar { background: #eef2f8; color: #3a4558; }
    #showcase-panel.inbox .mail { padding: 12px 14px; border-top: 1px solid #e3e8f0; }
    #showcase-panel.inbox .mail.old { color: #7a8597; }
    #showcase-panel.inbox .meta { font-size: 12px; color: #6b768a; }
    #showcase-panel.inbox .subject { font-weight: 700; margin: 2px 0 6px; }
    #showcase-panel.inbox .body { white-space: pre-wrap; word-break: break-word;
      max-height: 230px; overflow: hidden; }
    #showcase-panel.inbox a { color: #1a56db; font-weight: 600; }
    #showcase-pointer { position: fixed; z-index: 2147483001; width: 22px; height: 22px;
      margin: -11px 0 0 -11px; border-radius: 50%; background: rgba(255, 195, 90, 0.5);
      border: 2px solid #ffc35a; pointer-events: none; transition: transform 0.15s; left: -40px;
      top: -40px; }
    #showcase-pointer.down { transform: scale(0.7); background: rgba(255, 195, 90, 0.9); }
  `;
  const escape = (text) =>
    String(text).replace(
      /[&<>"]/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c],
    );
  const linkify = (text) =>
    escape(text).replace(
      /https?:\/\/[^\s<]+/g,
      (url) => `<a href="${url}" data-showcase-link>${url}</a>`,
    );

  window.__showcase = (state) => {
    if (!document.body) return;
    if (!document.getElementById('showcase-style')) {
      const style = document.createElement('style');
      style.id = 'showcase-style';
      style.textContent = css;
      document.head.append(style);
      const pointer = document.createElement('div');
      pointer.id = 'showcase-pointer';
      document.body.append(pointer);
      addEventListener('mousemove', (e) => {
        pointer.style.left = e.clientX + 'px';
        pointer.style.top = e.clientY + 'px';
      });
      addEventListener('mousedown', () => pointer.classList.add('down'));
      addEventListener('mouseup', () => pointer.classList.remove('down'));
    }
    document.getElementById('showcase-caption')?.remove();
    document.getElementById('showcase-panel')?.remove();
    if (state.caption) {
      const caption = document.createElement('div');
      caption.id = 'showcase-caption';
      caption.innerHTML =
        (state.step ? `<b>${escape(state.step)}</b>` : '') +
        `<span>${escape(state.caption)}</span>`;
      document.body.append(caption);
    }
    const panel = state.panel;
    if (!panel) return;
    const box = document.createElement('div');
    box.id = 'showcase-panel';
    box.className = panel.kind;
    if (panel.kind === 'terminal') {
      box.innerHTML =
        `<div class="bar"><i></i>${escape(panel.title)}</div><pre>` +
        panel.lines
          .map(([kind, text]) =>
            kind === 'command'
              ? `<span class="prompt">$</span> ${escape(text)}`
              : kind === 'token'
                ? `<span class="token">${escape(text)}</span>`
                : escape(text),
          )
          .join('\n') +
        '</pre>';
    } else {
      box.innerHTML =
        `<div class="bar">✉ Inbox · ${escape(panel.title)}</div>` +
        panel.messages
          .map(
            (m, i) =>
              `<div class="mail${i ? ' old' : ''}"><div class="meta">To ${escape(m.to)}</div>` +
              `<div class="subject">${escape(m.subject)}</div>` +
              (i ? '' : `<div class="body">${linkify(m.body)}</div>`) +
              '</div>',
          )
          .join('');
      for (const link of box.querySelectorAll('[data-showcase-link]')) {
        link.addEventListener('click', (event) => {
          // The app reads its invitation link on load, so open it as a fresh page.
          event.preventDefault();
          location.assign(link.href);
          location.reload();
        });
      }
    }
    document.body.append(box);
  };
  const paint = () => {
    try {
      window.__showcase(JSON.parse(sessionStorage.getItem('showcase-overlay') || '{}'));
    } catch {
      /* nothing to show yet */
    }
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', paint);
  else paint();
}

/** Returns the captured emails, newest first. */
function inbox(to) {
  let mail = [];
  try {
    mail = JSON.parse(fs.readFileSync(env.SHOWCASE_INBOX, 'utf8'));
  } catch {
    /* not written yet */
  }
  return mail.filter((m) => !to || m.to === to).reverse();
}

/** Waits until an email to the address arrives after the first count, and returns it. */
async function nextMail(to, count) {
  for (let i = 0; i < 120; i++) {
    const mail = inbox(to);
    if (mail.length > count) return mail[0];
    await pause(250);
  }
  throw new Error(`No email arrived for ${to}`);
}

/** Films the setup series and writes setup.webm and setup-chapters.json. */
async function film() {
  const context = await chromium.launchPersistentContext(env.SHOWCASE_PROFILE, {
    viewport,
    deviceScaleFactor: 1,
    timezoneId: 'America/Los_Angeles',
    locale: 'en-US',
    recordVideo: { dir: env.SHOWCASE_OUTPUT, size: viewport },
    ...(env.SHOWCASE_BROWSER ? { executablePath: env.SHOWCASE_BROWSER } : {}),
  });
  await context.addInitScript(overlay);
  if (env.SHOWCASE_OFFLINE_TILES) {
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
  const start = Date.now();
  const chapters = [];
  const now = () => (Date.now() - start) / 1000;
  const mark = (name) => {
    if (chapters.length) chapters.at(-1).end = now();
    if (name) chapters.push({ name, start: now() });
  };
  let state = {};
  const show = async (changes) => {
    state = { ...state, ...changes };
    await page.evaluate((s) => {
      sessionStorage.setItem('showcase-overlay', JSON.stringify(s));
      window.__showcase?.(s);
    }, state);
  };
  const step = (n, caption) => show({ step: `Step ${n} of ${STEPS}`, caption });
  const type = async (locator, text, delay = 55) => {
    await locator.click();
    await locator.pressSequentially(text, { delay });
  };
  const button = (name) => page.getByRole('button', { name, exact: true });
  const heading = (name) => page.getByRole('heading', { name, exact: true });
  const owner = env.SHOWCASE_EMAIL;
  const signIn = async () => {
    await heading('Welcome home.').waitFor();
    await type(page.locator('#login [name=email]'), owner, 35);
    await type(page.locator('#login [name=password]'), env.SHOWCASE_PASSWORD, 20);
    await button('Sign in').click();
  };
  const openMail = async (to, count) => {
    const mail = await nextMail(to, count);
    await show({ panel: { kind: 'inbox', title: to, messages: inbox(to).slice(0, 3) } });
    return mail;
  };
  const clickMailLink = async () => {
    await pause(1500);
    await page.locator('#showcase-panel [data-showcase-link]').first().click();
    await page.waitForLoadState('load');
  };

  try {
    await steps();
  } catch (error) {
    // What the screen showed when filming gave up, for the run's report.
    await page.screenshot({ path: path.join(env.SHOWCASE_OUTPUT, 'setup-failure.png') });
    const text = await page
      .locator('body')
      .innerText()
      .catch(() => '');
    fs.writeFileSync(path.join(env.SHOWCASE_OUTPUT, 'setup-screen.log'), text.slice(0, 4000));
    await context.close();
    throw error;
  }

  const video = page.video();
  await context.close();
  fs.renameSync(await video.path(), path.join(env.SHOWCASE_OUTPUT, 'setup.webm'));
  fs.writeFileSync(
    path.join(env.SHOWCASE_OUTPUT, 'setup-chapters.json'),
    JSON.stringify(chapters, null, 2),
  );

  /** The setup steps, in order. */
  async function steps() {
    // Step 1: the setup page of a server that has just started.
    await page.goto(env.SHOWCASE_ORIGIN);
    await heading('Make this server yours.').waitFor();
    mark('setup-server');
    await step(1, 'Open your server. The first visit asks for the setup token from its logs.');
    await pause(2500);
    await show({
      panel: {
        kind: 'terminal',
        title: 'Terminal',
        lines: [
          ['command', 'docker compose logs narahem'],
          ['text', 'NARAHEM FIRST-RUN SETUP TOKEN:'],
          ['token', env.SHOWCASE_SETUP_TOKEN],
          ['text', ''],
          ['command', 'docker compose exec narahem python manage.py bootstrap-token'],
          ['token', env.SHOWCASE_SETUP_TOKEN],
        ],
      },
    });
    await pause(3500);
    await type(page.locator('#setup [name=token]'), env.SHOWCASE_SETUP_TOKEN, 12);
    await step(1, 'Name your household and create the administrator account.');
    await show({ panel: null });
    await type(page.locator('#setup [name=household]'), env.SHOWCASE_HOUSEHOLD);
    await type(page.locator('#setup [name=email]'), owner, 40);
    await type(page.locator('#setup [name=password]'), env.SHOWCASE_PASSWORD, 25);
    await type(page.locator('#setup [name=confirm_password]'), env.SHOWCASE_PASSWORD, 25);
    await pause(800);
    await button('Create household').click();
    await step(1, 'Then sign in with that account.');
    await signIn();
    await heading('Household map').first().waitFor();
    await step(
      1,
      'Done: this browser is now trusted. It holds the keys that unlock your family’s locations.',
    );
    await pause(6000);

    // Step 2: connect email, test it, and confirm the administrator's address.
    mark('setup-email');
    await button('Admin settings').click();
    await heading('Email').waitFor();
    await page.locator('.settings-section > summary').filter({ hasText: 'Email' }).click();
    await page.locator('#mail').scrollIntoViewIfNeeded();
    await step(2, 'Connect email, so your server can send invitations and sign-in codes.');
    await pause(2500);
    await type(page.locator('#mail [name=sender]'), owner, 45);
    await step(2, 'Pick your provider. The server settings are filled in for you.');
    await pause(1200);
    await page.locator('#provider').selectOption('gmail');
    await pause(1000);
    await step(2, 'Follow the steps to make an app password, then paste it in.');
    await page.locator('#mail-help').scrollIntoViewIfNeeded();
    await pause(5000);
    await type(page.locator('#mail [name=password]'), 'abcd efgh ijkl mnop', 40);
    await pause(600);
    await button('Save email settings').click();
    await pause(2000);
    const tests = inbox(owner).length;
    await step(2, 'Send yourself a test to check it works.');
    await button('Send test to me').click();
    await openMail(owner, tests);
    await pause(4500);
    const confirmations = inbox(owner).length;
    await step(2, 'Now confirm your own address: the server emails you a link.');
    await page.locator('#confirm-owner').scrollIntoViewIfNeeded();
    await pause(1200);
    await page.locator('#confirm-owner').click();
    await openMail(owner, confirmations);
    await pause(3000);
    await step(2, 'Open the link from the email…');
    await clickMailLink();
    await heading('Confirm your email.').waitFor();
    await show({ panel: null });
    await step(2, '…and confirm. As the administrator, leave the other fields blank.');
    await pause(3000);
    await button('Confirm email').click();
    await signIn();
    await heading('Household map').first().waitFor();
    await pause(2500);

    // Step 3: invite a family member, who accepts; then the family appears on the map.
    mark('setup-invite');
    await button('Manage household').click();
    await heading('Manage household').waitFor();
    await step(3, 'Invite your family. Each person gets an email with a link to join.');
    await pause(2500);
    const invitee = env.SHOWCASE_INVITE_EMAIL;
    await type(page.locator('#invite [name=email]'), invitee, 45);
    await pause(600);
    await button('Send invitation').click();
    await openMail(invitee, 0);
    await step(3, `${env.SHOWCASE_INVITE_NAME} opens the invitation…`);
    await pause(4000);
    await clickMailLink();
    await heading('Confirm your email.').waitFor();
    await show({ panel: null });
    await step(3, '…and chooses a display name and password.');
    await type(page.locator('#verify [name=username]'), env.SHOWCASE_INVITE_NAME, 70);
    await type(page.locator('#verify [name=password]'), env.SHOWCASE_PASSWORD, 25);
    await type(page.locator('#verify [name=confirm_password]'), env.SHOWCASE_PASSWORD, 25);
    await pause(600);
    await button('Confirm email').click();
    await heading('Welcome home.').waitFor();
    fs.writeFileSync(path.join(env.SHOWCASE_SIGNALS, 'invited'), '');
    await step(3, `Next, ${env.SHOWCASE_INVITE_NAME} signs in to the Nära Hem app on their phone.`);
    await pause(3500);
    const ready = path.join(env.SHOWCASE_SIGNALS, 'family-ready');
    for (let i = 0; i < 240 && !fs.existsSync(ready); i++) await pause(250);
    if (!fs.existsSync(ready)) throw new Error('The family phones did not join');
    await step(3, 'Back on your map, everyone appears as their phone joins.');
    await signIn();
    await heading('Household map').first().waitFor();
    await pause(14000);
    await show({ step: '', caption: 'That’s it: your household is set up.' });
    await pause(4000);
    mark(null);
  }
}

film().catch((error) => {
  console.error(error);
  process.exit(1);
});
