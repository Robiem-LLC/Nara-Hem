import { test } from 'node:test';
import assert from 'node:assert/strict';
import { differentZone, knownZone, zoneTime } from '../../src/client/zones.mjs';

// This browser is in New York (Node applies TZ when it changes); 2026-11-20 01:00 UTC is 8:00 PM
// there.
process.env.TZ = 'America/New_York';
const evening = Date.UTC(2026, 10, 20, 1, 0);

const plain = (text) => text.replaceAll(String.fromCharCode(0x202f), ' ');

test('another zone shows both times, this browser first', () => {
  assert.equal(plain(zoneTime(evening, 'America/Los_Angeles')), '8:00 PM EST / 5:00 PM PST');
  assert.equal(
    plain(zoneTime(evening, 'Asia/Tokyo', { withDate: true })),
    '11/19/2026, 8:00 PM EST / 11/20/2026, 10:00 AM GMT+9',
  );
});

test('the same clock, no zone or an unknown one shows one time', () => {
  for (const zone of ['America/New_York', 'America/Toronto', null, undefined, 'Not/AZone', 7]) {
    assert.equal(plain(zoneTime(evening, zone)), '8:00 PM');
    assert.equal(differentZone(evening, zone), false);
  }
  assert.equal(knownZone('x'.repeat(65)), null);
});
