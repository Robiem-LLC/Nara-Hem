// The browser access screen: enabling, unlocking or forgetting this browser.

import * as C from '../crypto.mjs';
import * as T from '../trusted-vault.mjs';
import { bind, button, lock, save, showTemplate, stop } from './core.mjs';
import { emptyMap, screen } from './map-screen.mjs';
import { state } from './state.mjs';

/**
 * Shows the browser access screen while the keys are locked: enable, unlock or forget this browser.
 */
export async function locked() {
  stop();
  const saved = localStorage.getItem(state.storeKey);
  if (state.mode === 'trips') {
    showTemplate('screen-trips-locked');
    return;
  }
  if (state.mode === 'map') {
    await emptyMap('Location access needs one-time setup in Manage household.');
    return;
  }
  const missing = saved && JSON.parse(saved).trusted;
  const variant = !crypto.subtle
    ? 'https-required'
    : saved && !missing
      ? 'migrate'
      : missing
        ? 'missing'
        : 'enable';
  showTemplate('screen-browser-access');
  for (const element of state.view.querySelectorAll('[data-slot]')) {
    const slot = element.dataset.slot;
    if (slot !== variant && !(slot === 'forget' && saved)) element.remove();
  }
  if (saved) {
    button('forget-vault', async () => {
      if (
        !confirm(
          'Forget this browser device? Revoke its old identity using a trusted device, then ' +
            'enroll again.',
        )
      ) {
        return;
      }
      localStorage.removeItem(state.storeKey);
      await T.deleteKey(state.context);
      lock();
      await locked();
    });
  }
  if (!crypto.subtle) return;
  if (saved && !missing) {
    bind('vault-form', async (data) => {
      const opened = await C.openVault(JSON.parse(saved), data['vault-password'], state.context);
      state.vault = opened.value;
      state.key = opened.key;
      state.salt = opened.salt;
      await T.putKey(state.context, state.key);
      await save();
      await screen();
    });
  }
  if (!saved) {
    button('enable-browser', async () => {
      if (!state.user.verified) {
        const latest = await state.api('/api/session');
        if (!latest.verified) {
          throw new Error(
            'Confirm your account email in Admin settings before enabling a browser.',
          );
        }
        state.user.verified = true;
      }
      const h = await state.api('/api/household');
      state.key = await T.createKey();
      state.salt = crypto.getRandomValues(new Uint8Array(16));
      state.vault = C.keys(state.user.id, h.id, state.user.role === 'admin' ? 'Admin' : 'Browser');
      const registration = {
        domain: 'narahem.device.v1',
        household: h.id,
        ...C.identity(state.vault),
        platform: 'web',
      };
      await T.putKey(state.context, state.key);
      const result = await state.api('/api/devices/register', 'POST', {
        id: state.vault.id,
        name: state.vault.name,
        signing_key: state.vault.signing_key,
        box_key: state.vault.box_key,
        platform: 'web',
        signature: C.sign(registration, state.vault.signing_secret),
      });
      state.vault.credential = result.credential;
      await save();
      await screen();
    });
  }
}
