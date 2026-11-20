// The Amazon-hosted forwarder: it passes Alexa's request to the relay and returns the answer.
const assert = require('node:assert/strict');
const https = require('node:https');
const { EventEmitter } = require('node:events');
const test = require('node:test');

/** Replaces https.request with a fake relay that answers with status and body. */
function fakeRelay(status, body, seen) {
  https.request = (url, options, callback) => {
    const request = new EventEmitter();
    request.destroy = (error) => request.emit('error', error);
    request.end = (sent) => {
      seen.push({ url, options, sent });
      const response = new EventEmitter();
      response.statusCode = status;
      response.setEncoding = () => {};
      callback(response);
      response.emit('data', body);
      response.emit('end');
    };
    return request;
  };
}

test('forwards the request to the relay with its secret and returns the answer', async () => {
  const seen = [];
  const answer = { version: '1.0', response: { outputSpeech: { text: 'Hi' } } };
  fakeRelay(200, JSON.stringify(answer), seen);
  const { handler } = require('./index.js');
  const event = { request: { type: 'LaunchRequest' } };
  assert.deepEqual(await handler(event), answer);
  assert.equal(seen[0].url, 'https://PASTE-RELAY-ADDRESS-HERE/forward');
  assert.match(seen[0].options.headers.Authorization, /^Bearer /);
  assert.deepEqual(JSON.parse(seen[0].sent), event);
  fakeRelay(401, '{}', seen);
  const said = await handler(event);
  assert.match(said.response.outputSpeech.text, /couldn't reach the Nära Hem relay/);
  // Alexa asking whether to send a request here without the skill's name gets a quiet no.
  const asking = { request: { type: 'CanFulfillIntentRequest' } };
  assert.deepEqual((await handler(asking)).response, { canFulfillIntent: { canFulfill: 'NO' } });
});
