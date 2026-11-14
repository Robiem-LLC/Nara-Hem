'use strict';
let csrf = '';
const view = document.getElementById('view');
const message = document.getElementById('message');
const logout = document.getElementById('logout');
let currentUser;
let activeSection = 'map';

// Set from /api/setup: text messages are on, so phone numbers work as well as email.
let textingOn = false;
let navigationVersion = 0;
let deviceAlertTimer = null;
const deviceAlert = document.getElementById('device-request-alert');

// Admin settings sections the admin has opened, so a redraw after saving keeps them open.
const openSections = new Set();

// The banner's text and its close button.
const messageText = document.createElement('span');
const messageClose = document.createElement('button');
messageClose.type = 'button';
messageClose.className = 'message-close';
messageClose.setAttribute('aria-label', 'Close message');
messageClose.onclick = () => notice('');
message.append(messageText, messageClose);
message.hidden = true;

// Where the last button was pressed, so its result also shows next to it.
let lastPress = null;
let toast = null;
document.addEventListener(
  'click',
  (event) => {
    const button = event.target.closest('button');
    if (!button || button.closest('.action-toast, #message') || button.matches('.secret-toggle')) {
      return;
    }
    lastPress = { rect: button.getBoundingClientRect(), at: Date.now() };
  },
  true,
);
document.addEventListener(
  'submit',
  (event) => {
    const button = event.target.querySelector('button[type="submit"], button:not([type])');
    if (button) lastPress = { rect: button.getBoundingClientRect(), at: Date.now() };
  },
  true,
);

let guardQueued = false;

/**
 * Shows a message in the banner at the top, or clears it when text is empty. If a button was just
 * pressed, the message also appears next to it, so it's seen even when the page is scrolled.
 */
function notice(text) {
  messageText.textContent = text;
  message.hidden = !text;
  if (text && lastPress && Date.now() - lastPress.at < 20000) showToast(text, lastPress.rect);
}

/** Shows a short message by the pressed button's spot on screen for a few seconds. */
function showToast(text, rect) {
  toast?.remove();
  toast = document.createElement('div');
  toast.className = 'action-toast';
  toast.setAttribute('role', 'status');
  const words = document.createElement('span');
  const close = document.createElement('button');
  // Drawn by CSS from data-text, so the page holds the words once (in the banner); the label
  // still reads them out.
  words.dataset.text = text;
  toast.setAttribute('aria-label', text);
  close.type = 'button';
  close.className = 'message-close';
  close.setAttribute('aria-label', 'Close message');
  const shown = toast;
  close.onclick = () => shown.remove();
  toast.append(words, close);
  document.body.append(toast);
  // Below the button if there is room, otherwise above it; always inside the window.
  const below = rect.bottom + 8;
  const top =
    below + toast.offsetHeight < innerHeight
      ? below
      : Math.max(8, rect.top - toast.offsetHeight - 8);
  toast.style.top = `${top}px`;
  toast.style.left = `${Math.max(8, Math.min(rect.left, innerWidth - toast.offsetWidth - 8))}px`;
  setTimeout(() => shown.remove(), 8000);
}

/**
 * Greys out a form's submit button until its required fields are filled. Buttons disabled for
 * other reasons are left alone.
 */
function guardForms(root = document) {
  for (const form of root.querySelectorAll('form')) {
    const ready = form.checkValidity();
    for (const button of form.querySelectorAll('button[type="submit"], button:not([type])')) {
      if (!ready && !button.disabled) {
        button.disabled = true;
        button.dataset.needsFields = 'true';
      } else if (ready && button.dataset.needsFields && !button.dataset.blocked) {
        button.disabled = false;
        delete button.dataset.needsFields;
      }
    }
  }
}

/** Checks the forms again once the current change has finished drawing. */
function queueGuard() {
  if (guardQueued) return;
  guardQueued = true;
  requestAnimationFrame(() => {
    guardQueued = false;
    guardForms();
  });
}

document.addEventListener('input', queueGuard, true);
document.addEventListener('change', queueGuard, true);
new MutationObserver(queueGuard).observe(document.body, { childList: true, subtree: true });

/** Marks the current section in the navigation. */
function selectSection(section) {
  for (const name of ['map', 'household', 'settings', 'trips', 'places']) {
    const button = document.getElementById(`open-${name}`);
    const selected = name === section;
    button.classList.toggle('secondary', !selected);
    if (selected) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
}

/** Copies a template from index.html into target (the main view by default) and returns target. */
function showTemplate(templateId, target = view) {
  const template = document.getElementById(templateId);
  target.replaceChildren(template.content.cloneNode(true));
  return target;
}

/**
 * Calls the API with the session cookie and CSRF token. Throws an Error with the server's message
 * on failure.
 */
async function api(path, method = 'GET', body, extraHeaders = {}) {
  const headers = { ...extraHeaders };
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(
      typeof data.detail === 'string' ? data.detail : 'Please check the fields and try again.',
    );
    error.fields = data.fields || [];
    throw error;
  }
  return data;
}

/** Calls task with the form's values on submit and shows any error. */
function bind(id, task) {
  document.getElementById(id).addEventListener('submit', async (event) => {
    event.preventDefault();
    notice('');
    const form = event.currentTarget;
    form.querySelectorAll('.field-error').forEach((el) => el.remove());
    form.querySelectorAll('[aria-invalid]').forEach((el) => {
      el.removeAttribute('aria-invalid');
      el.removeAttribute('aria-describedby');
    });
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    try {
      await task(Object.fromEntries(new FormData(form)), form);
    } catch (error) {
      let first;
      for (const issue of error.fields || []) {
        const input = form.elements.namedItem(issue.field);
        if (!input || !input.tagName) continue;
        const hint = document.createElement('p');
        hint.className = 'field-error';
        hint.id = `${form.id}-${input.name}-error`;
        hint.textContent = issue.message;
        input.setAttribute('aria-invalid', 'true');
        input.setAttribute('aria-describedby', hint.id);
        (input.closest('.secret-control') || input).after(hint);
        first ||= input;
      }
      notice(error.message);
      first?.focus();
    } finally {
      if (button) button.disabled = false;
      guardForms(form.parentElement ?? document);
    }
  });
}

/** Shows the first-run setup form. */
function setup() {
  showTemplate('screen-setup');
  bind('setup', async (data, form) => {
    if (data.password !== data.confirm_password) throw new Error('Passwords do not match.');
    delete data.confirm_password;
    await api('/api/setup', 'POST', data);
    sessionStorage.setItem('narahem.setup-bootstrap', data.token);
    form.reset();
    await login();
    notice('Household created. Sign in to finish email setup.');
  });
}

/** Shows the sign-in form. */
async function login() {
  if (deviceAlertTimer) clearInterval(deviceAlertTimer);
  deviceAlert.hidden = true;
  currentUser = null;
  window.FamilyClient?.lock();
  document.getElementById('app-nav').hidden = true;
  logout.hidden = true;
  showTemplate('screen-login');
  if (textingOn) {
    allowPhone('#login [name=email]', 'Email or phone number');
    allowPhone('#forgot [name=recovery_email]', 'Recovery email or phone number');
    allowPhone('#request [name=invite_email]', 'Invited email or phone number');
  }
  bind('login', async (data) => {
    const result = await api('/api/login', 'POST', data);
    csrf = result.csrf;
    sessionStorage.removeItem('narahem.signed-out');
    await load();
  });
  document.getElementById('forgot-toggle').onclick = () => {
    const form = document.getElementById('forgot');
    form.hidden = !form.hidden;
    if (!form.hidden) {
      form.elements.recovery_email.value = document.querySelector('#login [name=email]').value;
      form.elements.recovery_email.focus();
    }
  };
  bind('forgot', async (data) => {
    const result = await api('/api/password/forgot', 'POST', { email: data.recovery_email });
    notice(result.message);
    document.getElementById('forgot').reset();
  });
  bind('request', async (data) => {
    const result = await api('/api/enrollment/request', 'POST', { email: data.invite_email });
    notice(result.message);
  });
}

/** Lets a sign-in field take a phone number as well as an email address. */
function allowPhone(selector, label) {
  const input = view.querySelector(selector);
  input.type = 'text';
  input.labels[0].textContent = label;
}

/** Shows the email verification page, which also sets the username and password for new members. */
async function verification(token, invitedEmail, invitedPhone) {
  history.replaceState(null, '', '/');
  showTemplate('screen-verify');
  const invited = view.querySelector('#verify [name=invited_email]');
  if (invitedEmail || invitedPhone) {
    invited.value = invitedEmail || invitedPhone;
    if (!invitedEmail) {
      invited.type = 'tel';
      invited.labels[0].textContent = 'Invited phone number';
    }
  } else {
    invited.labels[0].remove();
    invited.remove();
  }
  const deepLink = new URL('narahem://join');
  deepLink.searchParams.set('server', location.origin);
  deepLink.searchParams.set('token', token);
  const intro = document.createElement('p');
  const openApp = document.createElement('a');
  openApp.href = deepLink.toString();
  openApp.textContent = 'Open this invitation in the Nära Hem Android app';
  intro.append(
    openApp,
    document.createTextNode(
      ' · If Nära Hem is not installed, install it first and reopen this email link.',
    ),
  );
  view.querySelector('.card').prepend(intro);
  bind('verify', async (data) => {
    if ((data.password || data.confirm_password) && data.password !== data.confirm_password) {
      throw new Error('Passwords do not match.');
    }
    await api('/api/enrollment/verify', 'POST', {
      token,
      username: data.username || null,
      password: data.password || null,
    });
    token = '';
    await login();
    notice(
      'Account confirmed. Sign in on your phone and verify it with the six-digit code you are sent.',
    );
  });
}

/** Shows the password reset form. */
async function resetPassword(token) {
  history.replaceState(null, '', '/');
  showTemplate('screen-reset-password');
  bind('reset-password', async (data, form) => {
    if (data.new_password !== data.confirm_password) throw new Error('Passwords do not match.');
    await api('/api/password/reset', 'POST', { token, new_password: data.new_password });
    token = '';
    form.reset();
    await login();
    notice('Password updated. Sign in with your new password.');
  });
}

/**
 * Sets up the email form: the provider is guessed from the address, its server details are
 * filled in under Advanced, and its steps for getting an app password are shown. Returns a
 * function that gives the chosen provider.
 */
function setupMailForm(configured) {
  const presets = window.FamilyClient?.mailPresets;
  const form = document.getElementById('mail');
  const field = (name) => form.elements[name];
  const provider = document.getElementById('provider');
  const help = document.getElementById('mail-help');
  const advanced = document.getElementById('mail-advanced');
  let chosen = false;
  if (!presets) {
    provider.closest('form').querySelector('label[for="provider"]').hidden = true;
    provider.hidden = true;
    advanced.open = true;
    return () => ({});
  }
  for (const preset of presets.MAIL_PROVIDERS) provider.append(new Option(preset.name, preset.id));
  provider.value = configured
    ? presets.providerForHost(field('host').value).id
    : presets.providerForEmail(field('sender').value).id;
  const apply = () => {
    const preset = presets.mailProvider(provider.value);
    const address = field('sender').value.trim();
    help.replaceChildren();
    if (!address && !chosen && !configured) {
      const prompt = document.createElement('p');
      prompt.className = 'subtle';
      prompt.textContent = 'Type your email address and the server details are filled in for you.';
      help.append(prompt);
    } else if (preset.blocked) {
      const warning = document.createElement('p');
      warning.className = 'warn';
      warning.textContent = preset.blocked;
      help.append(warning);
    } else {
      const steps = document.createElement('ol');
      for (const step of preset.steps ?? []) {
        const item = document.createElement('li');
        item.textContent = step;
        steps.append(item);
      }
      help.append(steps);
      if (preset.link) {
        const link = document.createElement('a');
        link.href = preset.link.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = preset.link.label;
        help.append(link);
      }
    }
    if (preset.host) {
      field('host').value = preset.host;
      field('port').value = preset.port;
      field('mode').value = preset.mode;
      field('username').value = address;
    }
    const appPassword = preset.host && preset.id !== 'microsoft365';
    document.getElementById('mail-password-label').textContent =
      (appPassword ? 'App password' : 'Password') +
      (configured ? ' · blank keeps saved password' : '');
    document.getElementById('mail-password-field').hidden = Boolean(preset.blocked);
    // A first setup with a known provider needs its app password before it can be saved.
    field('password').required = !configured && Boolean(preset.host) && !preset.blocked;
    const save = document.getElementById('save-mail');
    if (preset.blocked) save.dataset.blocked = 'true';
    else delete save.dataset.blocked;
    save.disabled = Boolean(preset.blocked);
    queueGuard();
    if (preset.id === 'other' && (chosen || address)) advanced.open = true;
  };
  field('sender').addEventListener('input', () => {
    if (!chosen) provider.value = presets.providerForEmail(field('sender').value).id;
    apply();
  });
  provider.addEventListener('change', () => {
    chosen = true;
    apply();
  });
  field('host').addEventListener('invalid', () => (advanced.open = true));
  apply();
  return () => presets.mailProvider(provider.value);
}

/** Lists each push relay with whether this server is signed up with it. */
function showRelays(relays) {
  const list = document.getElementById('relay-list');
  list.replaceChildren();
  for (const relay of relays) {
    const item = document.createElement('li');
    const name = document.createElement('strong');
    name.textContent = relay.name;
    const state = document.createElement('span');
    let ok = false;
    if (!relay.address) {
      state.textContent = 'No relay address in this server';
    } else if (relay.manual_token) {
      ok = true;
      state.textContent = 'Using the token from the server settings';
    } else if (relay.registered) {
      ok = true;
      state.textContent = 'Registered ' + new Date(relay.registered_at * 1000).toLocaleDateString();
    } else if (relay.last_error) {
      state.textContent = 'Not registered: ' + relay.last_error;
    } else {
      state.textContent = 'Not registered yet: it signs up with the first notification';
    }
    state.className = ok ? 'ok' : 'warn';
    const address = document.createElement('small');
    address.textContent = relay.address || '';
    item.append(name, state, address);
    list.append(item);
  }
  const register = document.getElementById('register-relays');
  const done = relays.every((relay) => relay.manual_token || relay.registered || !relay.address);
  register.disabled = done;
  register.title = done ? 'Both relays are registered.' : '';
}

/**
 * Turns each settings card into a section that opens from its heading, closed unless the admin
 * opened it earlier. Every heading becomes the same size.
 */
function collapseSections(grid) {
  for (const card of [...grid.children]) {
    const heading = card.querySelector('h2, h3');
    if (!heading) continue;
    const name = heading.textContent.trim();
    const section = document.createElement('details');
    const summary = document.createElement('summary');
    const title = document.createElement('h2');
    const body = document.createElement('div');
    section.className = card.className + ' settings-section';
    if (card.id) section.id = card.id;
    title.textContent = name;
    summary.append(title);
    heading.remove();
    body.className = 'settings-section-body';
    body.append(...card.childNodes);
    section.append(summary, body);
    section.open = openSections.has(name);
    section.addEventListener('toggle', () => {
      if (section.open) openSections.add(name);
      else openSections.delete(name);
    });
    card.replaceWith(section);
  }
  // Two columns that grow on their own: opening a section only lengthens its column.
  const columns = [document.createElement('div'), document.createElement('div')];
  [...grid.children].forEach((section, index) => columns[index % 2].append(section));
  for (const column of columns) column.className = 'settings-column';
  grid.replaceChildren(...columns);
}

/** Fills in the Text messages card and wires up its buttons. */
function textingCard(texting, user) {
  const card = document.getElementById('texting-card');
  if (!texting) {
    card.remove();
    return;
  }
  const pill = document.getElementById('texting-status');
  const key = document.getElementById('texting-key');
  const source = document.getElementById('texting-source');
  pill.className = 'pill ' + (texting.enabled ? 'ok' : texting.error ? 'warn' : '');
  pill.textContent = texting.enabled
    ? `On · ${texting.quota} texts left`
    : texting.error
      ? `Off: ${texting.error}`
      : 'Off · email only';
  if (texting.source === 'environment') {
    // The environment variable wins, so the key can't be changed here.
    key.type = 'text';
    key.value = texting.key_hint;
    key.disabled = true;
    card.querySelector('.secret-toggle').hidden = true;
    document.getElementById('save-texting').hidden = true;
    source.hidden = false;
    source.textContent =
      'Set by NARAHEM_TEXTBELT_KEY on the server, which overrides this card. Change it there.';
  } else if (texting.source === 'settings') {
    key.placeholder = `Saved ${texting.key_hint} · enter a new key to replace it`;
    document.getElementById('remove-texting').hidden = false;
  }
  document.getElementById('check-texting').disabled = !texting.source;
  const refresh = async (message) => {
    textingOn = (await api('/api/setup')).texting;
    await dashboard(user);
    notice(message);
  };
  const saved = (result) =>
    result.enabled
      ? `Text messages are on: ${result.quota} texts left.`
      : result.error
        ? `Text messages are off: ${result.error}`
        : 'Text messages are off.';
  bind('texting', async (data) => {
    if (!data.key.trim()) throw new Error('Enter your Textbelt key.');
    await refresh(saved(await api('/api/texting', 'PUT', { key: data.key })));
  });
  document.getElementById('check-texting').onclick = async () => {
    try {
      await refresh(saved(await api('/api/texting/check', 'POST', {})));
    } catch (e) {
      notice(e.message);
    }
  };
  document.getElementById('remove-texting').onclick = async () => {
    try {
      await refresh(saved(await api('/api/texting', 'PUT', { key: '' })));
    } catch (e) {
      notice(e.message);
    }
  };
  bind('texting-test', async (data) => {
    const result = await api('/api/texting/test', 'POST', { phone: data.phone });
    notice(`Test text sent. ${result.quota} texts left.`);
  });
}

/** Fills in the Alexa card, or removes it when the server doesn't allow Alexa. */
function alexaCard(alexa, user) {
  const card = document.getElementById('alexa-card');
  if (!alexa) {
    card.remove();
    return;
  }
  const when = (time) => (time ? new Date(time * 1000).toLocaleString() : 'never');
  const pill = document.getElementById('alexa-status');
  pill.className = 'pill ' + (alexa.links.length ? 'ok' : '');
  pill.textContent = alexa.links.length
    ? 'Linked'
    : alexa.store
      ? 'Not linked · enable the Nära Hem skill in the Alexa app'
      : "Not available · this server wasn't built with the Alexa relay";
  const store = document.getElementById('alexa-store');
  store.hidden = !alexa.store;
  store.querySelector('[data-slot="alexa-address"]').textContent = alexa.address;
  document.getElementById('alexa-links').replaceChildren(
    ...alexa.links.map((link) => {
      const item = document.createElement('li');
      const text = document.createElement('span');
      const revoke = document.createElement('button');
      text.textContent = `Linked ${when(link.created)} · last used ${when(link.last_used)}`;
      revoke.className = 'secondary';
      revoke.textContent = 'Unlink';
      revoke.onclick = async () => {
        if (!confirm('Unlink this Alexa account? It will need to sign in again.')) return;
        try {
          await api(`/api/alexa/links/${link.id}/revoke`, 'POST', {});
          await dashboard(user);
          notice('Alexa unlinked.');
        } catch (e) {
          notice(e.message);
        }
      };
      item.append(text, revoke);
      return item;
    }),
  );
}

/** Shows the admin settings page. */
async function dashboard(user) {
  const navigation = ++navigationVersion;
  if (sessionStorage.getItem('narahem.signed-out')) return;
  selectSection('settings');
  window.FamilyClient?.suspend();
  if (user.role !== 'admin') {
    await manageHousehold(user);
    return;
  }
  const [status, mail, relays, texting, alexa] = await Promise.all([
    api('/api/admin'),
    api('/api/mail'),
    api('/api/push/relays').catch(() => ({ relays: [] })),
    api('/api/texting').catch(() => null),
    api('/api/alexa').catch(() => null),
  ]);
  if (
    activeSection !== 'settings' ||
    navigation !== navigationVersion ||
    sessionStorage.getItem('narahem.signed-out')
  ) {
    return;
  }
  showTemplate('screen-admin-settings');
  view.querySelector('[data-slot="household"]').textContent = status.household;
  view.querySelector('[data-slot="public-url"]').textContent = status.public_url;
  const mailStatus = view.querySelector('[data-slot="mail-status"]');
  mailStatus.classList.add(status.mail_tested ? 'ok' : 'warn');
  mailStatus.textContent = status.mail_tested ? 'Email tested' : 'Email setup needed';
  const notApplicable = user.email_verified ? 'email-unconfirmed' : 'email-confirmed';
  view.querySelectorAll(`[data-slot="${notApplicable}"]`).forEach((element) => element.remove());
  if (mail.configured) {
    for (const key of ['host', 'port', 'mode', 'username', 'sender']) {
      document.querySelector(`#mail [name="${key}"]`).value = mail[key];
    }
  }
  const mailPreset = setupMailForm(mail.configured);
  document.getElementById('test-mail').disabled = !mail.configured;
  document.getElementById('retry-mail').disabled = !mail.configured;
  showRelays(relays.relays);
  textingCard(texting, user);
  alexaCard(alexa, user);
  document.getElementById('register-relays').onclick = async () => {
    try {
      showRelays((await api('/api/push/relays/register', 'POST', {})).relays);
      notice('Checked both push relays.');
    } catch (e) {
      notice(e.message);
    }
  };
  bind('mail', async (data) => {
    data.port = Number(data.port);
    data.password = data.password || null;
    if (mailPreset().host) data.username = data.sender.trim();
    await api('/api/mail', 'PUT', data);
    await dashboard(user);
    notice('Email settings saved. Send a test next.');
  });
  document.getElementById('test-mail').onclick = async () => {
    try {
      await api('/api/mail/test', 'POST', {});
      await dashboard(user);
      notice('Test email sent. Check your inbox.');
    } catch (e) {
      const hint = e.message.includes('username or password') ? mailPreset().passwordHint : '';
      notice(hint ? `${e.message} ${hint}` : e.message);
    }
  };
  document.getElementById('retry-mail').onclick = async () => {
    try {
      const result = await api('/api/mail/retry', 'POST', {});
      await dashboard(user);
      notice(`${result.sent} emails sent; delivery ${result.delivery}.`);
    } catch (e) {
      notice(e.message);
    }
  };
  bind('change-password', async (data, form) => {
    if (data.new_password !== data.repeat_password) {
      throw new Error('The new passwords do not match.');
    }
    await api('/api/admin/change-password', 'POST', {
      current_password: data.current_password,
      new_password: data.new_password,
    });
    form.reset();
    notice('Password changed. Other sessions and remembered phone sign-ins have been revoked.');
  });
  await operationalSettings();
  collapseSections(document.getElementById('admin-settings-grid'));
  if (!user.email_verified) {
    document.getElementById('confirm-owner').onclick = async () => {
      try {
        const fresh = await api('/api/session');
        if (fresh.email_verified) {
          currentUser = fresh;
          await dashboard(fresh);
          notice('Administrator email already confirmed.');
          return;
        }
        const result = await api('/api/enrollment/request', 'POST', { email: user.email });
        notice(result.message);
      } catch (e) {
        notice(e.message);
      }
    };
  }
}

/** Adds the storage, retention, mail and push settings sections to the admin page. */
async function operationalSettings() {
  const storage = await api('/api/storage');
  const section = document.createElement('section');
  section.className = 'card';
  showTemplate('card-storage', section);
  document
    .getElementById('admin-settings-grid')
    .insertBefore(section, document.getElementById('change-password').closest('section'));
  section.querySelector('#storage-summary').textContent =
    `${storage.records} records · ${(storage.bytes / 1048576).toFixed(2)} MiB of ` +
    `${(storage.quota_bytes / 1048576).toFixed(0)} MiB`;
  section.querySelector('#days').value = storage.retention_days;
  bind('retention', async (data) => {
    await api('/api/storage/retention', 'PUT', { days: Number(data.days) });
    await dashboard(currentUser);
    notice('Retention saved and expired data deleted.');
  });
  document.getElementById('cleanup-storage').onclick = async () => {
    try {
      await api('/api/storage/cleanup', 'POST', {});
      await dashboard(currentUser);
      notice('Expired data cleaned.');
    } catch (e) {
      notice(e.message);
    }
  };
  const exportButton = section.querySelector('#export-diagnostics');
  exportButton.hidden = section.querySelector('#diagnostic-export-note').hidden =
    !storage.exports_available;
  exportButton.onclick = async () => {
    exportButton.disabled = true;
    try {
      const r = await api('/api/admin/diagnostics/export', 'POST', {
        category: section.querySelector('#diagnostic-kind').value,
        hours: Number(section.querySelector('#diagnostic-hours').value),
      });
      notice('Saved ' + r.saved + ' to the exports folder.');
    } catch (e) {
      notice(e.message);
    } finally {
      exportButton.disabled = false;
    }
  };
  section.querySelector('#download-diagnostics').onclick = () => {
    const category = section.querySelector('#diagnostic-kind').value;
    const hours = section.querySelector('#diagnostic-hours').value;
    const link = document.createElement('a');
    link.href =
      '/api/admin/diagnostics?category=' +
      encodeURIComponent(category) +
      '&hours=' +
      encodeURIComponent(hours);
    link.download = 'narahem-' + category + '-' + hours + 'h.txt';
    document.body.append(link);
    link.click();
    link.remove();
  };
}

/** Shows a banner when a device is waiting for approval. */
async function refreshDeviceAlerts() {
  if (document.hidden || !currentUser?.verified || !window.FamilyClient?.canApprove()) {
    deviceAlert.hidden = true;
    return;
  }
  try {
    const response = await api('/api/devices');
    if (!window.FamilyClient?.canApprove()) {
      deviceAlert.hidden = true;
      return;
    }
    const count = response.devices.filter(
      (d) => d.status === 'pending' && d.platform !== 'ios' && d.platform !== 'android',
    ).length;
    document.getElementById('device-request-count').textContent =
      count === 1 ? '1 browser needs approval' : count + ' browsers need approval';
    deviceAlert.hidden = count === 0;
  } catch {
    deviceAlert.hidden = true;
  }
}

document.getElementById('review-device-requests').onclick = async () => {
  try {
    await navigate('household');
    const access = [...document.querySelectorAll('details')].find((item) =>
      item.querySelector(':scope > summary')?.textContent.startsWith('Device access'),
    );
    if (access) {
      access.open = true;
      access.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    await refreshDeviceAlerts();
  } catch (error) {
    notice(error.message);
  }
};

let refreshingMemberPhones = false;

/** Updates each member card with the latest location, battery and status. */
function updateMemberDetails() {
  const shared = new Map((window.FamilyClient?.summaries() || []).map((p) => [p.id, p]));
  for (const card of view.querySelectorAll('.member-card')) {
    const p = shared.get(card.dataset.accountId);
    const location = card.querySelector('.member-location');
    const photo = card.querySelector('.member-photo');
    const fresh = p
      ? window.FamilyClient.freshness({
          captured_at: p.captured_at,
          still_since: p.still_since,
          last_contact: p.last_contact,
          data: p.location,
        })
      : null;
    const suffix = p ? ` · ${new Date(p.captured_at).toLocaleString()}${fresh.suffix}` : '';
    const fix = p?.location;
    const fallback = p
      ? `${Number(fix.lat).toFixed(5)}, ${Number(fix.lon).toFixed(5)}` + suffix
      : card.dataset.memberStatus === 'active' && currentUser?.role === 'admin'
        ? 'No location shared with this browser. On the phone, enable Share with approved ' +
          'household owner browser in Settings.'
        : 'No location shared with this browser';
    const fixKey = p ? `${p.captured_at}:${fix.lat}:${fix.lon}` : 'none';
    if (location.dataset.fixKey !== fixKey) {
      location.dataset.fixKey = fixKey;
      location.textContent = fallback;
      if (p) {
        window.FamilyClient.locationLabel(p.id)
          .then((label) => {
            if (
              card.isConnected &&
              location.dataset.fixKey === fixKey &&
              location.textContent !== label + suffix
            ) {
              location.textContent = label + suffix;
            }
          })
          .catch(() => {});
      }
    } else if (p && !location.textContent.endsWith(suffix)) {
      location.textContent = fallback;
    }
    const desiredPhoto =
      p?.photo?.startsWith('data:image/jpeg;base64,') &&
      p.photo.length < 30000 &&
      /^[A-Za-z0-9+/=]+$/.test(p.photo.slice('data:image/jpeg;base64,'.length))
        ? p.photo
        : null;
    const existingPhoto = photo.querySelector('img');
    if (desiredPhoto) {
      if (existingPhoto?.getAttribute('src') !== desiredPhoto) {
        const image = document.createElement('img');
        image.src = desiredPhoto;
        image.alt = '';
        photo.replaceChildren(image);
      }
    } else if (
      existingPhoto ||
      photo.textContent !== (card.dataset.username || '?').slice(0, 1).toUpperCase()
    ) {
      photo.textContent = (card.dataset.username || '?').slice(0, 1).toUpperCase();
    }
  }
}

window.addEventListener('narahem.locations', () => {
  if (activeSection !== 'household') return;
  updateMemberDetails();
  if (
    currentUser?.role === 'admin' &&
    !refreshingMemberPhones &&
    view.querySelector('.member-card')
  ) {
    refreshingMemberPhones = true;
    window.FamilyClient?.refreshHouseholdMemberPhones(view)
      .catch(() => {})
      .finally(() => {
        refreshingMemberPhones = false;
      });
  }
});
let verificationRefreshRunning = false;
let householdTimer = null;

/** Returns what the household page shows about each account, to notice when it changes. */
function accountsSignature(accounts) {
  return JSON.stringify(
    accounts.map((a) => [a.id, a.status, a.verified, a.username, a.email, a.phone]),
  );
}

/**
 * Keeps the household page current while it is open: phone details every 15 seconds, and the
 * whole page when someone's account status changes. It never redraws while a form is in use.
 */
function watchHousehold(user, accounts, navigation) {
  clearInterval(householdTimer);
  if (user.role !== 'admin') return;
  const shown = accountsSignature(accounts);
  const left = () => activeSection !== 'household' || navigation !== navigationVersion;
  householdTimer = setInterval(async () => {
    if (left()) {
      clearInterval(householdTimer);
      return;
    }
    if (document.hidden) return;
    try {
      const fresh = (await api('/api/accounts')).filter((a) => a.role !== 'admin');
      // The page may have changed while the list loaded; never draw over another page.
      if (left()) return;
      const typing =
        view.contains(document.activeElement) &&
        document.activeElement.matches('input, textarea, select');
      if (accountsSignature(fresh) !== shown && !typing) {
        await manageHousehold(user);
        return;
      }
      await window.FamilyClient?.refreshHouseholdMemberPhones(view);
    } catch {
      // A missed refresh is retried on the next tick.
    }
  }, 15000);
}

/** Adds a form for changing the user's display name. */
function addUsernameEditor(parent, user) {
  const box = document.createElement('section');
  box.className = 'card';
  showTemplate('card-username', box);
  parent.prepend(box);
  box.querySelector('[name="new_username"]').value = user.username || '';
  bind('my-username', async (data) => {
    const result = await api('/api/account/username', 'PUT', {
      username: data.new_username.trim(),
    });
    currentUser.username = result.username;
    user.username = result.username;
    notice('Username changed to ' + result.username + '.');
  });
}

/** Shows the household page: member cards, invitations and admin actions. */
async function manageHousehold(user) {
  const navigation = ++navigationVersion;
  if (sessionStorage.getItem('narahem.signed-out')) return;
  selectSection('household');
  activeSection = 'household';
  window.FamilyClient?.suspend();
  const accounts =
    user.role === 'admin' ? (await api('/api/accounts')).filter((a) => a.role !== 'admin') : [user];
  if (
    activeSection !== 'household' ||
    navigation !== navigationVersion ||
    sessionStorage.getItem('narahem.signed-out')
  ) {
    return;
  }
  showTemplate('screen-household');
  if (user.role !== 'admin') view.querySelector('#invite').remove();
  if (user.role !== 'admin') addUsernameEditor(view, user);
  for (const account of accounts) {
    document.getElementById('members').append(memberCard(account, user));
  }
  if (user.role === 'admin') {
    if (textingOn) inviteByPhone();
    bind('invite', async (data) => {
      if (!data.phone) delete data.phone;
      const r = await api('/api/invitations', 'POST', data);
      await manageHousehold(user);
      notice(invitationNotice(r));
    });
  }
  updateMemberDetails();
  try {
    await window.FamilyClient.mount({
      api,
      user,
      notice,
      view: document.getElementById('crypto-tools'),
      mode: 'tools',
    });
  } catch (error) {
    notice('Browser access needs repair: ' + error.message);
  }
  updateMemberDetails();
  if (user.role === 'admin') {
    await window.FamilyClient.refreshHouseholdMemberPhones(view).catch((error) => {
      for (const slot of view.querySelectorAll('.member-phone-controls')) {
        if (!slot.hasChildNodes()) slot.title = 'Phone status unavailable: ' + error.message;
      }
    });
  }
  watchHousehold(user, accounts, navigation);
}

/** Creates an element with an optional class name and text. */
function element(tag, className, text) {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text !== undefined) made.textContent = text;
  return made;
}

/** Creates a member card. Its phone controls are filled in later by the household client. */
function memberCard(account, user) {
  const row = element('article', 'member member-card');
  const info = element('div', 'member-info');
  const location = element('p', 'member-location');
  const status = element('small');
  const indicators = element('div', 'member-status-indicators');
  const actions = element('div', 'links member-primary-actions');
  const noticeArea = element('div', 'member-find-notice');
  const destructive = element('div', 'links member-destructive-actions');
  const accountRevokes = element('div', 'member-account-revokes');
  row.dataset.accountId = account.id;
  row.dataset.username = account.username || '';
  row.dataset.memberStatus = account.status || 'active';
  row.append(element('div', 'member-photo'));
  info.append(
    element('h3', '', account.username || contactOf(account)),
    element('small', 'member-contact', 'Email: ' + (account.email || 'None')),
    element(
      'small',
      'member-contact',
      'Phone: ' + (account.phone || (textingOn ? 'None' : 'Unavailable (text messages are off)')),
    ),
    ...(account.username ? [] : [element('strong', '', 'Pending invitation')]),
    location,
  );
  if (account.status !== 'active') {
    status.textContent = account.status === 'revoked' ? 'Access revoked' : 'Account pending';
    info.append(status);
  } else if (!account.verified) {
    status.textContent = 'Email verification pending';
    info.append(status);
  }
  indicators.setAttribute('aria-label', 'Last reported phone status');
  noticeArea.setAttribute('aria-live', 'polite');
  actions.append(element('div', 'member-phone-controls'));
  destructive.append(element('div', 'member-phone-revokes'), accountRevokes);
  row.append(info, indicators, actions, noticeArea, destructive);
  if (user.role === 'admin' && account.role !== 'admin') {
    addAdminActions(row, actions, accountRevokes, account, user);
  }
  return row;
}

/** With text messages on, the invite form takes a phone number, or an email and a phone. */
function inviteByPhone() {
  const contact = view.querySelector('#invite [name=email]');
  const extra = document.getElementById('invite-phone-field');
  contact.type = 'text';
  contact.labels[0].textContent = 'Member email or phone number';
  contact.addEventListener('input', () => {
    extra.hidden = !contact.value.includes('@');
    if (extra.hidden) extra.querySelector('input').value = '';
  });
}

/** Describes where an invitation went. */
function invitationNotice(result) {
  const sent = { email: 'emailed', text: 'texted' };
  const how = (result.channels ?? []).map((channel) => sent[channel]).join(' and ');
  if (!how) return 'Invitation created. Set up email or text messages to send it.';
  if (result.delivery === 'pending') {
    return `Invitation ${how}, but sending is still being retried.`;
  }
  return `Invitation ${how}. Account setup continues from the link.`;
}

/** Returns how to name an account: its email address, or its phone number. */
function contactOf(account) {
  return account.email || account.phone || 'Member';
}

/** Adds the admin's actions for another member's account. */
function addAdminActions(row, actions, accountRevokes, account, user) {
  const canEmail = Boolean(account.email || account.phone);
  if (account.status === 'active') {
    const feedback = element('span', 'member-push-feedback');
    feedback.setAttribute('role', 'status');
    feedback.setAttribute('aria-live', 'polite');
    actions.prepend(testPushButton(account, feedback));
    row.append(feedback);
  }
  if (account.status !== 'revoked') {
    accountRevokes.append(
      accountButton('Revoke user', 'danger', {
        question:
          `Revoke user ${contactOf(account)}? Their sign-in will stop, and all registered ` +
          `phones will be permanently revoked. Unrevoke user restores only account ` +
          `sign-in; phones must re-register with new identities. To revoke just one ` +
          `phone, use its separate Revoke phone button.`,
        disable: false,
        action: async () => {
          await api(`/api/accounts/${account.id}/revoke`, 'POST', {});
          await manageHousehold(user);
          notice('Account revoked. Apply signed membership changes in Browser location access.');
        },
      }),
    );
  } else {
    accountRevokes.append(
      accountButton('Unrevoke user', 'secondary', {
        question:
          `Restore password sign-in for ${contactOf(account)}? Previously revoked phones will ` +
          `remain revoked and require fresh enrollment.`,
        action: async () => {
          await api(`/api/accounts/${account.id}/restore`, 'POST', {});
          await manageHousehold(user);
          notice(
            'Account restored. The member can sign in and register a replacement phone; ' +
              'old phone credentials remain revoked.',
          );
        },
      }),
    );
  }
  accountRevokes.append(
    accountButton('Delete user and data', 'danger', {
      question:
        `Permanently delete ${contactOf(account)} and their location/event/profile data? ` +
        `Household places remain until an admin deletes them. Backups and downloaded ` +
        `copies remain.`,
      action: async () => {
        const r = await api(`/api/accounts/${account.id}`, 'DELETE', {});
        await manageHousehold(user);
        notice(
          r.membership_reconciliation_required
            ? 'User deleted. Apply the signed membership change in Browser location access.'
            : 'User and server data deleted. You can invite the same contact again.',
        );
      },
    }),
  );
  if (account.status === 'active' && canEmail) {
    actions.append(
      accountButton('Send password reset', 'secondary', {
        question: 'Send a reset link to ' + contactOf(account) + '?',
        disable: false,
        action: async () => {
          await api('/api/accounts/' + account.id + '/password-reset', 'POST', {});
          notice('Password reset link queued for ' + contactOf(account) + '.');
        },
      }),
    );
  }
  if (account.status === 'pending' && canEmail) {
    actions.append(
      accountButton('Resend', 'secondary', {
        disable: false,
        action: async () => {
          notice(
            (await api('/api/enrollment/request', 'POST', { email: contactOf(account) })).message,
          );
        },
      }),
    );
  }
}

/**
 * Creates a button that optionally confirms, runs action and shows any error. With disable, the
 * button stays disabled while running and after success.
 */
function accountButton(label, className, { question, action, disable = true }) {
  const made = element('button', className, label);
  made.onclick = async () => {
    if (question && !confirm(question)) return;
    if (disable) made.disabled = true;
    try {
      await action();
    } catch (e) {
      notice(e.message);
      made.disabled = false;
    }
  };
  return made;
}

/** Creates the admin's Test notification button for a member. */
function testPushButton(account, feedback) {
  const testPush = element('button', 'secondary', 'Test notification');
  testPush.title = 'Temporary diagnostic: send one generic push to an approved device';
  testPush.onclick = async () => {
    testPush.disabled = true;
    feedback.textContent = 'Checking push registration…';
    try {
      await sendTestPush(account, feedback);
    } catch (error) {
      feedback.textContent = `Test failed: ${error.message} Check Logs → Notifications.`;
    } finally {
      testPush.disabled = false;
    }
  };
  return testPush;
}

/** Sends a test push to one of the member's phones, asking which if there are several. */
async function sendTestPush(account, feedback) {
  const status = await api('/api/push/status');
  const choices = (status.devices || []).filter(
    (device) => device.account_id === account.id && device.registered,
  );
  let selected = choices[0];
  if (!choices.length) {
    throw new Error('No approved phone with a push subscription is registered for this member.');
  }
  if (choices.length > 1) {
    const options = choices
      .map((d, i) => i + 1 + '. ' + (d.name || d.provider || 'Phone') + ' (' + d.provider + ')')
      .join('\n');
    const response = prompt('Select the device for a generic test notification:\n' + options, '1');
    if (response === null) return;
    const index = Number(response) - 1;
    if (!Number.isInteger(index) || index < 0 || index >= choices.length) {
      throw new Error('Choose a valid device number.');
    }
    selected = choices[index];
  }
  feedback.textContent = 'Sending test push to ' + (selected.name || 'phone') + '…';
  const outcome = await api('/api/push/test', 'POST', { device_id: selected.id });
  feedback.textContent =
    outcome.sent === 1
      ? 'Push accepted for ' +
        (selected.name || 'phone') +
        '. Confirm on handset; acceptance does not prove delivery.'
      : 'Push not accepted. Check the phone subscription and Logs → Notifications.';
}

/** Switches to a section. */
async function navigate(section) {
  navigationVersion++;
  activeSection = section;
  history.replaceState(null, '', `#${section}`);
  selectSection(section);
  notice('');
  if (section === 'settings') {
    await dashboard(currentUser);
  } else if (section === 'household') {
    await manageHousehold(currentUser);
  } else if (section === 'trips') {
    await window.FamilyClient.mount({ api, user: currentUser, notice, view, mode: 'trips' });
  } else if (section === 'places') {
    await window.FamilyClient.mount({ api, user: currentUser, notice, view, mode: 'places' });
  } else {
    await window.FamilyClient.mount({ api, user: currentUser, notice, view, mode: 'map' });
  }
}

/** Starts the app: shows setup, sign-in, an email link page or the signed-in app. */
async function load() {
  window.FamilyClient?.suspend();
  const status = await api('/api/setup');
  textingOn = Boolean(status.texting);
  if (!status.configured) return setup();
  if (sessionStorage.getItem('narahem.signed-out')) return login();
  try {
    currentUser = await api('/api/session');
  } catch (e) {
    return login();
  }
  csrf = currentUser.csrf;
  logout.hidden = false;
  document.getElementById('app-nav').hidden = false;
  document.getElementById('open-settings').hidden = currentUser.role !== 'admin';
  api('/api/version')
    .then((v) => {
      document.getElementById('server-version').textContent =
        'Server ' +
        [v.channel, v.build && 'build ' + v.build, v.commit, v.built && v.built.slice(0, 10)]
          .filter(Boolean)
          .join(' · ');
    })
    .catch(() => {});
  if (deviceAlertTimer) clearInterval(deviceAlertTimer);
  deviceAlertTimer = setInterval(() => {
    refreshDeviceAlerts().catch(() => {});
  }, 15000);
  for (const name of ['map', 'household', 'settings', 'trips', 'places']) {
    document.getElementById(`open-${name}`).onclick = async () => {
      try {
        await navigate(name);
      } catch (e) {
        notice(e.message);
      }
    };
  }
  const selected = location.hash.slice(1);
  await navigate(
    ['map', 'household', 'settings', 'trips', 'places'].includes(selected) ? selected : 'map',
  );
  await refreshDeviceAlerts();
}

window.addEventListener('focus', async () => {
  if (
    !currentUser ||
    currentUser.email_verified ||
    verificationRefreshRunning ||
    sessionStorage.getItem('narahem.signed-out')
  ) {
    return;
  }
  verificationRefreshRunning = true;
  try {
    const fresh = await api('/api/session');
    if (fresh.email_verified && !currentUser.email_verified) {
      currentUser = fresh;
      csrf = fresh.csrf;
      await navigate(activeSection);
      notice('Administrator email confirmed.');
    }
  } catch (_) {
    /* Network hiccups should not interrupt onboarding. */
  } finally {
    verificationRefreshRunning = false;
  }
});
logout.onclick = async () => {
  sessionStorage.setItem('narahem.signed-out', '1');
  window.FamilyClient?.lock();
  try {
    await api('/api/logout', 'POST', {});
    notice('');
  } catch (e) {
    notice('Signed out locally; the server session could not be ended.');
  } finally {
    csrf = '';
    await login();
  }
};
const inviteLink = new URLSearchParams(location.hash.slice(1));
const token = inviteLink.get('verify');
const resetToken = inviteLink.get('reset');

/** Opens the page an email or text link points to, or the app. */
async function start() {
  // Links skip load(), but their sign-in form still needs to know whether phones work.
  textingOn = Boolean((await api('/api/setup').catch(() => ({}))).texting);
  if (resetToken) return resetPassword(resetToken);
  if (token) return verification(token, inviteLink.get('email'), inviteLink.get('phone'));
  return load();
}

start().catch((error) => notice(error.message));

view.addEventListener('click', (event) => {
  const button = event.target.closest('.secret-toggle');
  if (!button) return;
  const input = button.parentElement.querySelector('input');
  const visible = input.type === 'password';
  input.type = visible ? 'text' : 'password';
  button.textContent = visible ? 'Hide' : 'Show';
  button.setAttribute('aria-pressed', String(visible));
  const label = input.labels?.[0]?.textContent || 'password';
  button.setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} ${label}`);
});
