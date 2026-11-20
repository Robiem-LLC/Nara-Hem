/**
 * Nära Hem Alexa forwarder, for the store skill's "Alexa-hosted (Node.js)" code (lambda/index.js).
 *
 * Amazon runs this inside Alexa, so Amazon's skill service never has to make an HTTPS
 * connection to the relay itself. It passes each request on to the Nära Hem Alexa relay, which
 * sends it to the household's own server, and hands back the answer.
 *
 * Before deploying, put your relay's address in place of PASTE-RELAY-ADDRESS-HERE and its
 * FORWARD_SECRET in place of PASTE-FORWARD-SECRET-HERE. Keep that copy only in the Alexa developer
 * console, never in a repository.
 */
const https = require('https');
const RELAY = 'https://PASTE-RELAY-ADDRESS-HERE/forward';
const FORWARD_SECRET = 'PASTE-FORWARD-SECRET-HERE';
const TIMEOUT_MS = 7000;

/** Returns an answer Alexa can say. */
function say(text) {
  return {
    version: '1.0',
    response: { outputSpeech: { type: 'PlainText', text }, shouldEndSession: true },
  };
}

/** Sends the request to the relay and resolves with its answer. */
function relay(event) {
  const body = JSON.stringify(event);
  return new Promise((resolve, reject) => {
    const request = https.request(
      RELAY,
      {
        method: 'POST',
        timeout: TIMEOUT_MS,
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
          Authorization: 'Bearer ' + FORWARD_SECRET,
        },
      },
      (response) => {
        let text = '';
        response.setEncoding('utf8');
        response.on('data', (chunk) => (text += chunk));
        response.on('end', () => {
          if (response.statusCode !== 200) {
            reject(new Error('Relay answered ' + response.statusCode));
            return;
          }
          try {
            resolve(JSON.parse(text));
          } catch (error) {
            reject(error);
          }
        });
      },
    );
    request.on('timeout', () => request.destroy(new Error('Relay timed out')));
    request.on('error', reject);
    request.end(body);
  });
}

/** The skill's entry point: every Alexa request goes to the relay. */
exports.handler = async (event) => {
  try {
    return await relay(event);
  } catch (error) {
    console.log('Nära Hem relay failed: ' + error.message);
    // Alexa asking whether to send a request here without the skill's name gets a quiet no.
    if (event?.request?.type === 'CanFulfillIntentRequest') {
      return { version: '1.0', response: { canFulfillIntent: { canFulfill: 'NO' } } };
    }
    return say("I couldn't reach the Nära Hem relay. Please try again in a moment.");
  }
};
