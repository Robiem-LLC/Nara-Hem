// Device access: browsers, member phones and each phone's Find My Phone controls.

import * as C from '../crypto.mjs';
import {
  deviceApi,
  el,
  findTimers,
  node,
  reconcileRevokedMembership,
  roster,
  run,
  sync,
} from './core.mjs';
import { state } from './state.mjs';

/** Updates a location or notification permission badge from the phone's last report. */
function paintPrivilege(badge, kind, device, status) {
  const cap = device.permissions;
  const now = Date.now() / 1000;
  const at = (ms) => new Date(ms * 1000).toLocaleString();
  let state = 'unknown';
  let help = 'This phone has not reported its OS permissions yet.';
  if (kind === 'gps') {
    if (cap) {
      const ready = cap.foreground_location && cap.background_location && cap.sharing;
      state = ready ? 'allowed' : 'denied';
      help = ready
        ? 'Background location and sharing are allowed.'
        : 'Background location or sharing is off on this phone.';
    } else if (device.last_location && now - device.last_location < 600) {
      state = 'observed';
      help =
        'GPS received from this phone at ' +
        at(device.last_location) +
        '; its location permission is not confirmed.';
    }
  } else if (cap) {
    state = cap.notifications ? 'allowed' : 'denied';
    help = cap.notifications
      ? 'Notifications are allowed for Nära Hem.'
      : 'Notifications are off for Nära Hem on this phone.';
  } else if (status?.last_poll && now - status.last_poll < 180) {
    state = 'observed';
    help =
      'The phone checked in at ' +
      at(status.last_poll) +
      '; its notification permission is not confirmed.';
  }
  const name = kind === 'gps' ? 'Location' : 'Notifications';
  const label =
    (device.name || 'Phone') +
    ' · ' +
    name +
    ': ' +
    help +
    (cap?.reported_at ? ' Reported ' + at(cap.reported_at) + '.' : '');
  badge.dataset.state = state;
  badge.title = label;
  badge.setAttribute('aria-label', label);
  badge.textContent =
    (kind === 'gps' ? '📍' : '🔔') +
    ' ' +
    (state === 'allowed' ? '✓' : state === 'denied' ? '×' : state === 'observed' ? '•' : '?');
}

/** Adds permission badges and a Ring phone button for a member's phone. Admin only. */
function findPhoneControls(row, device, epoch) {
  let revision = 0;
  let feedbackTimeout = null;
  if (state.user.role !== 'admin' || device.status !== 'approved') return;
  const expected = state.vault;
  const badges = node('div');
  badges.className = 'member-permission-badges';
  const gps = node('span');
  const bell = node('span');
  gps.className = bell.className = 'member-permission-badge';
  badges.append(gps, bell);
  const buttons = node('div');
  buttons.className = 'find-phone-actions';
  const ring = node('button', 'Ring phone');
  ring.className = 'secondary';
  ring.disabled = true;
  buttons.append(ring);
  const feedback = node('span');
  feedback.className = 'phone-action-feedback';
  feedback.setAttribute('role', 'status');
  const statusArea = row.closest('.member-card')?.querySelector('.member-status-indicators');
  if (statusArea) statusArea.append(badges);
  else row.append(badges);
  row.append(buttons);
  const notices = row.closest('.member-card')?.querySelector('.member-find-notice');
  if (notices) notices.append(feedback);
  else row.append(feedback);
  /** Shows a short status message that clears itself. */
  function say(text) {
    feedback.textContent = text;
    if (feedbackTimeout) clearTimeout(feedbackTimeout);
    feedbackTimeout = setTimeout(() => {
      if (feedback.textContent === text) feedback.textContent = '';
    }, 4600);
  }
  /** Reloads the phone's Find My Phone status and updates the badges and button. */
  async function refreshStatus() {
    const request = ++revision;
    const value = await state.api('/api/find-phone/status/' + device.id);
    if (
      epoch !== state.renderEpoch ||
      state.vault !== expected ||
      !row.isConnected ||
      request !== revision
    ) {
      return null;
    }
    paintPrivilege(gps, 'gps', device, value);
    paintPrivilege(bell, 'bell', device, value);
    // iOS has no Do Not Disturb access permission, so it never disables the ring button there.
    const denied =
      Boolean(device.permissions) &&
      (!device.permissions.remote_alarm ||
        (value.platform !== 'ios' &&
          (!device.permissions.dnd_access || !device.permissions.notifications)));
    ring.disabled = !value.enabled || Boolean(denied);
    row.title =
      (value.last_poll
        ? 'Last phone contact ' + new Date(value.last_poll * 1000).toLocaleTimeString() + '. '
        : '') +
      (value.status === 'idle'
        ? 'No recent ring commands.'
        : 'Last command: ' + value.status + '.');
    return value;
  }
  row.__refreshStatus = async (updated) => {
    if (updated) device = updated;
    return refreshStatus();
  };
  const send = (action) =>
    run(async () => {
      ring.disabled = true;
      say(action === 'ring' ? 'Sending ring request…' : 'Sending stop request…');
      try {
        await sendFindCommand(expected, device, action);
        say(action === 'ring' ? 'Ring request sent.' : 'Stop request sent.');
        await refreshStatus();
      } catch (error) {
        say('Could not send the ' + action + ' request.');
        await refreshStatus().catch(() => {
          ring.disabled = false;
        });
        throw error;
      }
      watchRing(
        () => epoch === state.renderEpoch && state.vault === expected && row.isConnected,
        refreshStatus,
        say,
      );
    });
  ring.onclick = send('ring');
  row.__disposePhone = () => {
    if (feedbackTimeout) clearTimeout(feedbackTimeout);
    badges.remove();
    feedback.remove();
  };
  paintPrivilege(gps, 'gps', device, null);
  paintPrivilege(bell, 'bell', device, null);
  return refreshStatus();
}

/**
 * Adds, updates or removes each member's phone rows on the household page. Uses the admin API
 * rather than the vault, so revoking works even if the vault is locked.
 */
export async function refreshHouseholdMemberPhones(root) {
  if (!root || state.user?.role !== 'admin') return;
  const epoch = state.renderEpoch;
  const result = await state.api('/api/devices');
  if (epoch !== state.renderEpoch || !root.isConnected) return;
  const cards = [...root.querySelectorAll('.member-card')];
  const updates = [];
  for (const card of cards) {
    const host = card.querySelector('.member-phone-controls');
    const revokeHost = card.querySelector('.member-phone-revokes');
    if (!host) continue;
    const phones = result.devices.filter(
      (d) =>
        d.account_id === card.dataset.accountId &&
        d.status === 'approved' &&
        (d.platform === 'ios' || d.platform === 'android'),
    );
    const names = new Set(phones.map((d) => d.id));
    for (const old of [...host.querySelectorAll('.member-phone')]) {
      if (!names.has(old.dataset.deviceId)) {
        old.__disposePhone?.();
        old.remove();
      }
    }
    for (const old of [...(revokeHost?.querySelectorAll('.member-phone-revoke') || [])]) {
      if (!names.has(old.dataset.deviceId)) old.remove();
    }
    for (const phone of phones) {
      let row = [...host.querySelectorAll('.member-phone')].find(
        (e) => e.dataset.deviceId === phone.id,
      );
      if (!row) {
        row = node('div');
        row.className = 'member-phone';
        row.dataset.deviceId = phone.id;
        const name = node('small', phone.name || 'Phone');
        name.className = 'member-phone-name';
        name.hidden = phones.length < 2;
        row.append(name);
        host.append(row);
        if (state.vault && state.chain) updates.push(findPhoneControls(row, phone, epoch));
      } else {
        const name = row.querySelector('.member-phone-name');
        if (name) {
          name.textContent = phone.name || 'Phone';
          name.hidden = phones.length < 2;
        }
        if (state.vault && state.chain && row.__refreshStatus) {
          updates.push(row.__refreshStatus(phone));
        }
      }
      if (revokeHost && !revokeHost.querySelector('[data-device-id="' + phone.id + '"]')) {
        revokeHost.append(phoneRevokeButton(phone, phones.length, root));
      }
    }
  }
  await Promise.allSettled(updates);
}

/** Fills the device lists on the browser access screen. */
export async function devices() {
  const epoch = state.renderEpoch;
  const result = await state.api('/api/devices');
  if (epoch !== state.renderEpoch || !state.vault || !state.chain || !el('device-list')) return;
  el('device-list').replaceChildren();
  el('pending-browser-approvals')?.replaceChildren();
  el('browser-access-devices')?.replaceChildren();
  el('membership-repair')?.replaceChildren();
  showMembershipRepair(result.devices);
  for (const d of result.devices.filter(
    (d) =>
      d.status !== 'revoked' &&
      d.platform !== 'server' &&
      !(d.status === 'pending' && (d.platform === 'ios' || d.platform === 'android')),
  )) {
    if (d.status === 'pending') {
      el('pending-browser-approvals')?.append(pendingBrowserRow(d, result.devices));
    } else if (
      d.status === 'approved' &&
      d.platform === 'web' &&
      d.id !== state.vault.id &&
      (state.user.role === 'admin' || d.account_id === state.user.id)
    ) {
      el('browser-access-devices')?.append(approvedBrowserRow(d));
    }
    el('device-list').append(deviceRow(d));
  }
}

/** Signs and sends a ring or stop command to a phone. */
async function sendFindCommand(expected, device, action) {
  const issued = Math.floor(Date.now() / 1000);
  const body = {
    domain: 'narahem.find-phone.v1',
    household: expected.household,
    id: C.uuid(),
    issuer: expected.id,
    target: device.id,
    action,
    issued_at: issued,
    expires_at: issued + 120,
  };
  await sync();
  if (state.vault !== expected) throw new Error('Browser session changed.');
  await deviceApi('/api/find-phone/commands', 'POST', {
    body,
    signature: C.sign(body, expected.signing_secret),
  });
}

/**
 * Polls the ring status every 2 seconds, for up to about 2 minutes, until the phone reports a
 * result.
 */
function watchRing(stillShowing, refreshStatus, say) {
  let attempts = 0;
  const poll = async () => {
    if (!stillShowing() || attempts++ >= 65) return;
    try {
      const current = await refreshStatus();
      if (
        current &&
        ['stopped', 'failed', 'blocked', 'expired', 'cancelled'].includes(current.status)
      ) {
        if (current.status === 'failed' || current.status === 'blocked') {
          say('Phone could not play the alarm.');
        } else if (current.status === 'expired') {
          say('The ring request expired.');
        }
        return;
      }
    } catch (_) {
      return;
    }
    const timeout = setTimeout(() => {
      findTimers.delete(timeout);
      poll();
    }, 2000);
    findTimers.add(timeout);
  };
  poll();
}

/** Creates a Revoke phone button. */
function phoneRevokeButton(phone, phoneCount, root) {
  const revoke = node(
    'button',
    phoneCount > 1 ? 'Revoke ' + (phone.name || 'phone') : 'Revoke phone',
  );
  revoke.dataset.deviceId = phone.id;
  revoke.className = 'danger member-phone-revoke';
  revoke.title =
    'Permanently revoke this phone; it must register a fresh device identity to return.';
  revoke.onclick = run(async () => {
    if (
      !confirm(
        'Permanently revoke ' +
          (phone.name || 'this phone') +
          ' for this member? This phone identity can never be reapproved. A ' +
          'replacement must be freshly registered and verified by email. The member ' +
          'account remains active.',
      )
    ) {
      return;
    }
    revoke.disabled = true;
    try {
      await state.api('/api/phones/' + phone.id + '/revoke', 'POST', {});
      await refreshHouseholdMemberPhones(root);
      state.notice(
        'Phone identity permanently revoked. User sign-in is unchanged; a replacement ' +
          'must verify its email code.',
      );
    } catch (error) {
      revoke.disabled = false;
      throw error;
    }
  });
  return revoke;
}

/** Offers the admin a button to remove revoked or deleted devices from the signed roster. */
function showMembershipRepair(serverDevices) {
  const known = new Set(serverDevices.map((d) => d.id));
  const removed = new Set([
    ...serverDevices.filter((d) => d.status === 'revoked').map((d) => d.id),
    ...state.chain.current.devices.filter((d) => !known.has(d.id)).map((d) => d.id),
  ]);
  if (state.user.role !== 'admin' || !state.chain.current.devices.some((d) => removed.has(d.id))) {
    return;
  }
  const reconcile = node('button', 'Apply account revocations to encryption membership');
  reconcile.onclick = run(async () => {
    await roster(state.chain.current.devices.filter((d) => !removed.has(d.id)));
    await devices();
    state.notice('Revoked accounts removed from future encryption.');
  });
  el('membership-repair')?.append(reconcile);
}

/** Creates a device list entry: owner, enrollment date and last activity. */
function deviceRow(d) {
  const row = node('section');
  const adminBrowser =
    state.user.role === 'admin' &&
    d.account_id === state.user.id &&
    (d.name === 'My browser' || d.name === 'Admin');
  const hidden = d.activity_visible === false;
  const when = (seconds, never) => (seconds ? new Date(seconds * 1000).toLocaleString() : never);
  const seen = hidden ? 'Not shared with you' : when(d.seen, 'Never');
  const lastGPS = hidden ? 'Not shared with you' : when(d.last_location, 'Never');
  const enrolled = d.created ? new Date(d.created * 1000).toLocaleDateString() : 'Unknown';
  const owner = d.owner_name || 'Member';
  const ownerEmail = d.owner_email ? ' · ' + d.owner_email : '';
  row.className = 'device-row';
  row.append(node('h4', `${adminBrowser ? 'Admin' : d.name} · ${d.status}`));
  if (adminBrowser && d.id === state.vault.id && state.vault.anchor) {
    const fingerprint = node('p');
    const value = node('code', C.hash(C.unb64(state.vault.anchor)));
    fingerprint.className = 'device-root-fingerprint';
    fingerprint.append(node('strong', 'Household root fingerprint (legacy recovery): '));
    value.id = 'root-code';
    fingerprint.append(value);
    row.append(fingerprint);
  }
  row.append(node('p', `${owner}${ownerEmail} · Enrolled ${enrolled}`));
  row.append(
    node('p', `Last device request: ${seen} · Last location received from this phone: ${lastGPS}`),
  );
  if (d.status === 'approved' && d.seen && Date.now() / 1000 - d.seen > 7 * 86400) {
    const note = node(
      'p',
      'This device has not connected in over 7 days. Review before revoking; inactivity ' +
        'alone does not mean the device is unused.',
    );
    note.className = 'subtle';
    row.append(note);
  }
  return row;
}

/** Creates an entry for a browser waiting to join, with its pairing code and an Approve button. */
function pendingBrowserRow(d, serverDevices) {
  const browserRow = node('section');
  const code = C.pairingCode(d.registration, state.vault.anchor);
  const registrationHash = C.hash(C.canonical(d.registration));
  const possibleReplacements = serverDevices.filter(
    (old) =>
      old.id !== d.id &&
      old.status === 'approved' &&
      old.account_id === d.account_id &&
      old.name === d.name,
  );
  const short = node('strong', code);
  const approve = node('button', 'Approve device');
  browserRow.className = 'device-row';
  browserRow.append(node('h4', d.name + ' · browser approval pending'));
  if (possibleReplacements.length) {
    const seen = (old) =>
      old.seen ? new Date(old.seen * 1000).toLocaleString() : 'never connected';
    browserRow.append(
      node(
        'p',
        'Possible reinstall: ' +
          possibleReplacements.map((old) => old.name + ' (' + seen(old) + ')').join(', ') +
          '. Compare the pairing code; matching phone names do not prove identity.',
      ),
    );
  }
  browserRow.append(
    node('p', 'Compare the six-digit code with the requesting device. No fingerprint transfer.'),
  );
  short.className = 'pairing-code';
  short.setAttribute('aria-label', 'Pairing code');
  browserRow.append(short);
  approve.onclick = run(async () => {
    if (!C.verify(d.registration, d.registration_signature, d.signing_key)) {
      throw new Error('Device registration rejected.');
    }
    if (
      !confirm(
        'Does code ' + code + ' match the requesting device? Only approve a device you recognize.',
      )
    ) {
      return;
    }
    const replace =
      possibleReplacements.length === 1 &&
      confirm(
        'Replace the previous registration for ' +
          d.name +
          '? This revokes its old cryptographic identity and cannot be undone without ' +
          'pairing again. Choose Cancel to keep both approved.',
      );
    const retained = replace
      ? state.chain.current.devices.filter((old) => old.id !== possibleReplacements[0].id)
      : state.chain.current.devices;
    await roster(
      [
        ...retained,
        { id: d.id, account_id: d.account_id, signing_key: d.signing_key, box_key: d.box_key },
      ],
      { pairing_target: d.id, pairing_hash: registrationHash },
    );
    await devices();
    state.notice('Device approved with a signed proof. The requesting device can open the map.');
  });
  browserRow.append(approve);
  return browserRow;
}

/** Creates an entry for another approved browser with a Revoke button. */
function approvedBrowserRow(d) {
  const browserRow = node('section');
  const revoke = node('button', 'Revoke browser');
  browserRow.className = 'device-row';
  browserRow.append(node('h4', (d.name || 'Browser') + ' · approved'));
  revoke.className = 'danger';
  revoke.onclick = run(async () => {
    if (
      !confirm(
        'Revoke this approved browser identity? A replacement browser must be freshly paired.',
      )
    ) {
      return;
    }
    // A deleted user can leave a stale device in an older signed roster. Clear out the ones
    // the server says are gone first, or the whole revocation gets rejected.
    await reconcileRevokedMembership();
    await roster(state.chain.current.devices.filter((item) => item.id !== d.id));
    await devices();
    state.notice('Browser revoked. A replacement browser must pair again.');
  });
  browserRow.append(revoke);
  return browserRow;
}
