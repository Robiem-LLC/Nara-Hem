import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initials } from '../../src/client/initials.mjs';

test('initials are the first letter of up to two words', () => {
  assert.equal(initials('John Doe'), 'JD');
  assert.equal(initials(' kim '), 'K');
  assert.equal(initials('åsa  o’neil'), 'ÅO');
  assert.equal(initials(''), '?');
  assert.equal(initials(undefined), '?');
});
