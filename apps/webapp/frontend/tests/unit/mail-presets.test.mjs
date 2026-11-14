// Email provider presets: guessing from an address or a saved server, and the Outlook.com block.
import assert from 'node:assert/strict';
import {
  MAIL_PROVIDERS,
  mailProvider,
  providerForEmail,
  providerForHost,
} from '../../src/mail-presets.mjs';

assert.equal(providerForEmail('sam@gmail.com').host, 'smtp.gmail.com');
assert.equal(providerForEmail(' Sam@GoogleMail.com ').id, 'gmail');
assert.equal(providerForEmail('sam@me.com').host, 'smtp.mail.me.com');
assert.equal(providerForEmail('sam@yahoo.com').mode, 'tls');
assert.equal(providerForEmail('sam@family.example').id, 'other');
assert.equal(providerForEmail('not an address').id, 'other');
assert.ok(providerForEmail('sam@hotmail.com').blocked.includes('Outlook.com'));
assert.equal(providerForHost('SMTP.office365.com').id, 'microsoft365');
assert.equal(providerForHost('mail.family.example').id, 'other');
assert.equal(mailProvider('missing').id, 'other');
for (const provider of MAIL_PROVIDERS) {
  if (provider.blocked || provider.id === 'other') continue;
  assert.ok(provider.host && provider.port && /^(starttls|tls)$/.test(provider.mode), provider.id);
  assert.ok(provider.steps.length && provider.passwordHint, provider.id);
}
console.log('Email provider presets passed.');
